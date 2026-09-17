import json
import logging
from datetime import datetime

from conftest import FakeBrowser, FakeHttp

from monitor import main as main_module
from monitor.main import item_keys, only_new, parse_args, run
from monitor.models import Alert, Offer
from monitor.notify import LIMA, Notifier
from monitor.state import State
from monitor.http import Blocked

LOG = logging.getLogger("test")
NOON = datetime(2026, 9, 17, 12, 7, tzinfo=LIMA).timestamp()


def make_run(cfg, store_pages, argv=(), browser=None, now=NOON, http=None):
    http = http or FakeHttp(dict(store_pages))
    args = parse_args(list(argv))
    notifier = Notifier(cfg, http, dry_run=args.sin_enviar, log=LOG)
    code = run(cfg, args, LOG, now=now, browser_factory=lambda: browser or FakeBrowser(),
               http=http, notifier=notifier)
    return code, http, notifier


def titles(http):
    return [payload["title"] for _, payload, _ in http.posts]


def test_first_run_sends_alerts_and_welcome_then_dedupes(cfg, store_pages, tmp_path):
    cfg.store_batch = 10
    code, http, _ = make_run(cfg, store_pages)
    assert code == 0
    sent = titles(http)
    assert sent[:4] == [
        "🚨 hasta -100% en Fridays Óvalo Gutiérrez",
        "🔥 -70% en Big Cheese Pizza - Miraflores",
        "🔥 hasta -66% en Chinawok Larco Miraflores",
        "🔥 -65% en Wong",
    ]
    assert sent[-1] == "✅ Monitor de ofertas activado"
    saved = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert saved["started_at"] == int(NOON) and len(saved["seen"]) == 7

    # Una hora después, las mismas ofertas no se repiten.
    code, http, _ = make_run(cfg, store_pages, now=NOON + 3600)
    assert code == 0 and http.posts == []


def test_new_offer_in_same_store_is_sent_alone(cfg, store_pages):
    cfg.store_batch = 10
    make_run(cfg, store_pages)
    browser = FakeBrowser()
    menu = browser.menus[23402]
    menu["corridors"][0]["products"][2]["discounts"] = [
        {"type": "global_offer", "value": 80, "price": 4.98, "apply_to_user": True}
    ]
    code, http, _ = make_run(cfg, store_pages, browser=browser, now=NOON + 600)
    assert titles(http) == ["🚨 -80% en Big Cheese Pizza - Miraflores"]
    assert http.posts[0][1]["message"].startswith("• -80% Flash 4en1")
    assert http.posts[0][1]["priority"] == 5


def test_test_mode_and_dry_run_do_not_touch_memory(cfg, store_pages, tmp_path, capsys):
    code, http, notifier = make_run(cfg, store_pages, argv=["--sin-enviar", "--prueba"])
    assert code == 0
    assert http.posts == []
    assert not (tmp_path / "state.json").exists()
    test_payload = notifier.printed[-1]
    assert test_payload["title"] == "🧪 Prueba del monitor de Rappi"
    assert "✅ 7 restaurantes revisados." in test_payload["message"]
    assert "falta tu ubicación" in test_payload["message"]
    assert "Fridays" in capsys.readouterr().out


def test_test_mode_without_deals_shows_best_seen(cfg, store_pages):
    cfg.min_discount = 99
    cfg.check_stores = False
    code, http, _ = make_run(cfg, store_pages, argv=["--prueba"], browser=FakeBrowser(stores=[]))
    message = http.posts[-1][1]["message"]
    assert "Ahora no hay nada con -99% o más." in message


def test_overflow_summary(cfg, store_pages):
    cfg.max_alerts_per_run = 2
    cfg.store_batch = 10
    code, http, _ = make_run(cfg, store_pages)
    sent = titles(http)
    assert sent[2] == "🔥 2 locales más con descuentos altos"
    assert "-66% Chinawok" in http.posts[2][1]["message"]
    code, http, _ = make_run(cfg, store_pages, now=NOON + 60)
    assert http.posts == []  # el resumen también cuenta como avisado


def test_failure_notice_after_three_rounds_once_a_day(cfg, store_pages, tmp_path):
    cfg.check_stores = False
    broken = FakeBrowser(error=RuntimeError("no apareció el filtro 'Promos'"))
    for i in range(2):
        code, http, _ = make_run(cfg, store_pages, browser=broken, now=NOON + i * 1800)
        assert code == 0
        assert "⚠️ El monitor de Rappi tiene problemas" not in titles(http)
    code, http, _ = make_run(cfg, store_pages, browser=broken, now=NOON + 3 * 1800)
    assert code == 1
    assert "⚠️ El monitor de Rappi tiene problemas" in titles(http)
    code, http, _ = make_run(cfg, store_pages, browser=broken, now=NOON + 4 * 1800)
    assert code == 0 and "⚠️ El monitor de Rappi tiene problemas" not in titles(http)

    # Al recuperarse, el contador vuelve a cero.
    make_run(cfg, store_pages, now=NOON + 5 * 1800)
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["failures"] == {}


def test_chains_are_checked_when_restaurant_list_fails(cfg, store_pages):
    cfg.check_stores = False
    broken = FakeBrowser(error=RuntimeError("falló"))
    code, http, _ = make_run(cfg, store_pages, browser=broken)
    assert "https://www.rappi.com.pe/lima/restaurantes/delivery/6419-fridays" in http.calls


def test_only_new_keeps_unseen_items():
    alert = Alert(kind="restaurante", store_id="1", store_name="X", url="u",
                  offers=[Offer("a", "A", 1, 10, 90), Offer("b", "B", 3, 10, 70)],
                  announced_text="Hasta 90% Off", announced_pct=90)
    state = State()
    keys = item_keys(alert)
    state.mark_seen(keys[0][0], NOON)
    fresh, fresh_keys = only_new(alert, state, NOON + 60, 24)
    assert [offer.product_id for offer in fresh.offers] == ["b"]
    assert fresh.announced_text == "Hasta 90% Off"
    assert len(fresh_keys) == 2
    for key in fresh_keys:
        state.mark_seen(key, NOON + 60)
    assert only_new(alert, state, NOON + 120, 24) == (None, [])


def test_main_requires_topic(monkeypatch, capsys):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert main_module.main([]) == 2
    assert "Falta NTFY_TOPIC" in capsys.readouterr().out


def test_main_reports_config_errors(monkeypatch, capsys):
    monkeypatch.setenv("DESCUENTO_MINIMO", "mucho")
    assert main_module.main(["--sin-enviar"]) == 2
    assert "::error::DESCUENTO_MINIMO" in capsys.readouterr().out


def test_scheduled_run_without_topic_only_warns(monkeypatch, capsys):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    assert main_module.main([]) == 0
    assert "::warning::Falta NTFY_TOPIC" in capsys.readouterr().out


def test_test_mode_fails_when_scan_fails(cfg, store_pages):
    cfg.check_stores = False
    code, http, _ = make_run(cfg, store_pages, argv=["--prueba"],
                             browser=FakeBrowser(error=RuntimeError("falló")))
    assert code == 1
    message = next(payload["message"] for _, payload, _ in http.posts
                   if payload["title"] == "🧪 Prueba del monitor de Rappi")
    assert "El monitor funciona." not in message
    assert "No se puede confirmar" in message


def test_failed_delivery_fails_run_and_is_retried(cfg, store_pages):
    http = FakeHttp(store_pages)
    http.post_status = 503
    code, _, _ = make_run(cfg, store_pages, argv=["--prueba"], http=http)
    assert code == 1
    state = State.load(cfg.state_path)
    assert state.first_run and not state.seen
    code, http, _ = make_run(cfg, store_pages)
    assert code == 0
    assert "✅ Monitor de ofertas activado" in titles(http)


def test_browser_block_stops_all_rappi_sections(cfg, store_pages):
    code, http, _ = make_run(cfg, store_pages, argv=["--prueba"],
                             browser=FakeBrowser(error=Blocked("Rappi respondió 429")))
    assert code == 1
    assert http.calls == []
    assert "🧪 Prueba del monitor de Rappi" in titles(http)

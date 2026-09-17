from datetime import datetime

from conftest import FakeHttp

from monitor.models import Alert, Offer
from monitor.notify import (
    LIMA,
    MAX_MESSAGE_BYTES,
    Notifier,
    alert_message,
    alert_priority,
    alert_title,
    format_price,
    in_quiet_hours,
    truncate_bytes,
)


def lima_ts(hour: int) -> float:
    return datetime(2026, 9, 17, hour, 15, tzinfo=LIMA).timestamp()


def sample_alert(pct=70, kind="restaurante"):
    return Alert(
        kind=kind,
        store_id="23402",
        store_name="Big Cheese Pizza - Miraflores",
        url="https://www.rappi.com.pe/restaurantes/23402-big-cheese-pizza",
        offers=[
            Offer("1", "Cheesyton 3 Pizzas Grandes", 49.9, 149.7, 67),
            Offer("2", "Gran Dúo Cheesy + Cheesy", 29.9, 99.8, pct),
        ],
        distance_km=2.9,
    )


def test_format_price():
    assert format_price(29.9) == "S/ 29.90"
    assert format_price(1234.5) == "S/ 1,234.50"
    assert format_price(None) == "?"


def test_title_and_message():
    alert = sample_alert()
    assert alert_title(alert) == "🔥 -70% en Big Cheese Pizza - Miraflores"
    assert alert_title(sample_alert(pct=85)).startswith("🚨 -85%")
    message = alert_message(alert)
    lines = message.splitlines()
    assert lines[0] == "• -70% Gran Dúo Cheesy + Cheesy: S/ 29.90 (antes S/ 99.80)"
    assert lines[1].startswith("• -67% Cheesyton")
    assert lines[-1] == "Restaurante · a 2.9 km"
    assert "km" not in alert_message(alert, show_distance=False)


def test_message_for_announced_and_store_wide():
    alert = Alert(kind="restaurante", store_id="1792", store_name="Fridays", url="u",
                  announced_text="Hasta 100% Off", announced_pct=100,
                  store_wide_text="60% Off: mín S/40", store_wide_pct=60)
    assert alert.best_pct == 100
    assert alert_title(alert) == "🚨 -100% en Fridays"  # tiene descuento en toda la carta
    alert.store_wide_text = ""
    assert alert_title(alert) == "🚨 hasta -100% en Fridays"
    alert.store_wide_text = "60% Off: mín S/40"
    message = alert_message(alert)
    assert "toda la carta: 60% Off" in message
    assert "Hasta 100% Off" in message and "revisa la app" in message


def test_long_messages_are_truncated():
    offers = [Offer(str(i), "Producto " + "x" * 300, 1.0, 10.0, 90) for i in range(20)]
    alert = Alert(kind="tienda", store_id="1", store_name="Tienda", url="u", offers=offers)
    message = alert_message(alert)
    assert len(message.encode("utf-8")) <= MAX_MESSAGE_BYTES
    assert "…y 14 ofertas más" in message
    assert len(truncate_bytes("ñ" * 5000).encode("utf-8")) <= MAX_MESSAGE_BYTES


def test_priorities_and_quiet_hours(cfg):
    assert alert_priority(sample_alert(pct=70), cfg, lima_ts(12)) == 4
    assert alert_priority(sample_alert(pct=80), cfg, lima_ts(12)) == 5
    cfg.quiet_hours = (23, 7)
    assert in_quiet_hours(cfg.quiet_hours, lima_ts(23))
    assert in_quiet_hours(cfg.quiet_hours, lima_ts(3))
    assert not in_quiet_hours(cfg.quiet_hours, lima_ts(7))
    assert alert_priority(sample_alert(pct=90), cfg, lima_ts(2)) == 2
    assert in_quiet_hours((1, 5), lima_ts(4)) and not in_quiet_hours((1, 5), lima_ts(6))
    assert not in_quiet_hours(None, lima_ts(3))


def test_send_uses_ntfy_json_api(cfg):
    http = FakeHttp()
    cfg.ntfy_token = "tk_secreto"
    notifier = Notifier(cfg, http)
    assert notifier.send_alert(sample_alert(pct=82), now=lima_ts(12))
    url, payload, headers = http.posts[0]
    assert url == "https://ntfy.sh/"
    assert payload["topic"] == "prueba-tema-123"
    assert payload["priority"] == 5
    assert payload["tags"] == ["rotating_light"]
    assert payload["click"].endswith("23402-big-cheese-pizza")
    assert payload["actions"][0]["action"] == "view"
    assert headers == {"Authorization": "Bearer tk_secreto"}
    assert notifier.sent == 1

    http.post_status = 500
    assert not notifier.send("t", "m")
    assert notifier.sent == 1


def test_send_survives_network_errors(cfg):
    class Broken(FakeHttp):
        def post_json(self, *args, **kwargs):
            raise OSError("sin red")

    assert Notifier(cfg, Broken()).send("t", "m") is False


def test_dry_run_prints_instead_of_sending(cfg, capsys):
    http = FakeHttp()
    notifier = Notifier(cfg, http, dry_run=True)
    assert notifier.send_overflow([sample_alert(), sample_alert(pct=61)], now=lima_ts(12))
    assert http.posts == []
    out = capsys.readouterr().out
    assert "2 locales más" in out and "-70% Big Cheese" in out

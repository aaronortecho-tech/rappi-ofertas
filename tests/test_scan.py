import logging

from conftest import BASE, FakeBrowser, FakeHttp, fixture_text

from monitor.http import Blocked
from monitor.scan import Deadline, scan_chains, scan_restaurants, scan_stores, store_batch
from monitor.state import State

LOG = logging.getLogger("test")
NOW = 1_800_000_000


def test_scan_restaurants_uses_live_menu_and_flags_announced_deals(cfg):
    browser = FakeBrowser()
    http = FakeHttp()
    result = scan_restaurants(cfg, lambda: browser, http, LOG)
    assert result.error is None
    assert result.checked == 7
    assert browser.closed
    alerts = {alert.store_id: alert for alert in result.alerts}
    assert set(alerts) == {"1792", "23402", "632"}

    big_cheese = alerts["23402"]
    assert [offer.pct for offer in big_cheese.offers] == [70, 67, 63, 62]
    assert big_cheese.announced_text == ""
    assert big_cheese.url == f"{BASE}/restaurantes/23402-big-cheese-pizza"
    assert big_cheese.distance_km == 2.9

    # Sin menú en vivo se intenta la página pública; si tampoco hay productos,
    # se avisa del descuento anunciado.
    fridays = alerts["1792"]
    assert fridays.offers == [] and fridays.announced_pct == 100
    assert f"{BASE}/restaurantes/1792-tgi-fridays" in http.calls
    assert browser.menu_calls == [1792, 23402, 632]
    assert result.top_offers[0][0] == 70


def test_scan_restaurants_falls_back_to_public_page(cfg):
    browser = FakeBrowser(menus={})
    http = FakeHttp({f"{BASE}/restaurantes/23402-big-cheese-pizza": fixture_text("restaurant_ssg_23402.html")})
    result = scan_restaurants(cfg, lambda: browser, http, LOG)
    big_cheese = next(alert for alert in result.alerts if alert.store_id == "23402")
    # 63% está agotado y 65% es solo para Rappi Pro.
    assert [offer.pct for offer in big_cheese.offers] == [70, 67, 62]


def test_scan_restaurants_limits_candidates(cfg):
    cfg.max_candidates = 1
    browser = FakeBrowser()
    result = scan_restaurants(cfg, lambda: browser, FakeHttp(), LOG)
    assert browser.menu_calls == [1792]
    assert any("se revisan los 1" in note for note in result.notes)


def test_scan_restaurants_reports_browser_errors(cfg):
    result = scan_restaurants(cfg, lambda: FakeBrowser(error=RuntimeError("no apareció el filtro")), FakeHttp(), LOG)
    assert result.error == "no apareció el filtro"
    assert result.alerts == []


def test_store_batch_rotation():
    stores = list(range(10))
    seen = []
    for step in range(3):
        batch, number, total = store_batch(stores, 4, NOW + step * 1800, 30)
        seen.extend(batch)
        assert total == 3
    assert sorted(seen) == stores
    assert store_batch([], 4, NOW, 30) == ([], 0, 0)


def test_scan_stores_finds_offers_and_caches_store_list(cfg, store_pages):
    cfg.store_batch = 10
    state = State()
    http = FakeHttp(store_pages)
    result = scan_stores(cfg, http, state, NOW, LOG)
    assert result.error is None
    assert result.checked == 1  # solo Wong tiene página guardada
    assert [(a.store_id, a.store_name, [o.pct for o in a.offers]) for a in result.alerts] == [("62365", "Wong", [65])]
    assert result.alerts[0].url == f"{BASE}/tiendas/62365-wong"
    assert state.cached_stores(NOW) is not None

    http.calls.clear()
    scan_stores(cfg, http, state, NOW + 60, LOG)
    assert f"{BASE}/tiendas/tipo/market" not in http.calls  # usa la lista guardada


def test_scan_stores_errors(cfg, store_pages):
    empty = scan_stores(cfg, FakeHttp(), State(), NOW, LOG)
    assert "no se encontraron tiendas" in empty.error

    pages = {f"{BASE}/tiendas/tipo/market": store_pages[f"{BASE}/tiendas/tipo/market"]}
    unreadable = scan_stores(cfg, FakeHttp(pages), State(), NOW, LOG)
    assert unreadable.error == "no se pudo leer ninguna tienda del grupo"

    blocked = FakeHttp(store_pages, errors={f"{BASE}/tiendas/62365-wong/ofertas": Blocked("Rappi respondió 403")})
    cfg.store_batch = 10
    assert scan_stores(cfg, blocked, State(), NOW, LOG).error == "Rappi respondió 403"


def test_scan_chains(cfg):
    ssg = fixture_text("restaurant_ssg_23402.html")
    pages = {
        f"{BASE}/lima/restaurantes/delivery/6419-fridays": fixture_text("chain_fridays.html"),
        f"{BASE}/restaurantes/1790-tgi-fridays": ssg,
        f"{BASE}/restaurantes/107225-tgi-fridays": ssg,
    }
    http = FakeHttp(pages)
    result = scan_chains(cfg, http, LOG)
    assert result.error is None
    assert result.checked == 2
    assert f"{BASE}/restaurantes/1791-tgi-fridays" not in http.calls  # solo 2 locales por cadena
    [alert] = result.alerts
    assert alert.kind == "cadena" and alert.store_id == "cadena-6419"
    assert alert.store_name == "Fridays"
    assert [offer.pct for offer in alert.offers] == [70, 67, 62]


class Expired(Deadline):
    def __init__(self, after_checks):
        self.left = after_checks

    def expired(self):
        self.left -= 1
        return self.left < 0


def test_deadline_counts_time():
    ticks = iter([0, 5, 11])
    deadline = Deadline(10, clock=lambda: next(ticks))
    assert not deadline.expired()
    assert deadline.expired()


def test_time_budget_stops_restaurants_and_stores(cfg, store_pages):
    browser = FakeBrowser()
    result = scan_restaurants(cfg, lambda: browser, FakeHttp(), LOG, deadline=Expired(1))
    assert browser.menu_calls == [1792]
    assert any("se acabó el tiempo" in note for note in result.notes)

    cfg.store_batch = 10
    http = FakeHttp(store_pages)
    stores = scan_stores(cfg, http, State(), NOW, LOG, deadline=Expired(0))
    assert stores.checked == 0 and any("se acabó el tiempo" in note for note in stores.notes)
    assert stores.error is None  # sin tiempo no es un error de lectura


def test_one_broken_store_type_does_not_stop_the_rest(cfg, store_pages):
    cfg.store_types = ["farmacia", "market"]
    cfg.store_batch = 10
    http = FakeHttp(store_pages, errors={f"{BASE}/tiendas/tipo/farmacia": TimeoutError("lento")})
    result = scan_stores(cfg, http, State(), NOW, LOG)
    assert result.error is None and result.checked == 1


def test_one_broken_chain_does_not_stop_the_rest(cfg):
    ssg = fixture_text("restaurant_ssg_23402.html")
    cfg.chains = ["4569-chilis", "6419-fridays"]
    pages = {
        f"{BASE}/lima/restaurantes/delivery/6419-fridays": fixture_text("chain_fridays.html"),
        f"{BASE}/restaurantes/1790-tgi-fridays": ssg,
    }
    errors = {f"{BASE}/lima/restaurantes/delivery/4569-chilis": TimeoutError("lento")}
    result = scan_chains(cfg, FakeHttp(pages, errors), LOG)
    assert result.error is None
    assert result.checked == 1  # el segundo local de Fridays no tiene página guardada
    assert [alert.store_id for alert in result.alerts] == ["cadena-6419"]


def test_chains_report_error_when_nothing_could_be_read(cfg):
    errors = {f"{BASE}/lima/restaurantes/delivery/6419-fridays": TimeoutError("lento")}
    assert scan_chains(cfg, FakeHttp(errors=errors), LOG).error == "lento"
    assert "ningún local" in scan_chains(cfg, FakeHttp(), LOG).error


def test_blocked_menu_does_not_try_public_page(cfg):
    class BlockedBrowser(FakeBrowser):
        def restaurant_menu(self, store_id):
            raise Blocked("Rappi respondió 403")

    http = FakeHttp()
    result = scan_restaurants(cfg, BlockedBrowser, http, LOG)
    assert result.blocked and result.error
    assert http.calls == []


def test_store_cursor_continues_where_the_last_round_stopped():
    from monitor.scan import store_window
    stores = [(i, f"t{i}") for i in range(10)]
    assert store_window(stores, 4, 8) == [(8, "t8"), (9, "t9"), (0, "t0"), (1, "t1")]
    assert store_window(stores, 20, 3)[0] == (3, "t3") and len(store_window(stores, 20, 3)) == 10
    assert store_window([], 4, 0) == []


def test_scan_stores_saves_cursor_and_next_round_continues(cfg, store_pages):
    cfg.store_batch = 1
    state = State()
    http = FakeHttp(store_pages)
    scan_stores(cfg, http, state, NOW, LOG)
    first = state.store_list["next_start"]
    stores = state.store_list["stores"]
    read = [c for c in http.calls if c.endswith("/ofertas")]
    http.calls.clear()
    # Aunque la ronda siguiente llegue al mismo «horario», no repite: sigue desde el cursor.
    scan_stores(cfg, http, state, NOW, LOG)
    again = [c for c in http.calls if c.endswith("/ofertas")]
    assert len(stores) > 1 and read != again and state.store_list["next_start"] == (first + 1) % len(stores)

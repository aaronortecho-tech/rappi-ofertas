import json
import logging

import pytest

from conftest import BASE, FakeHttp, fixture_text
from monitor.config import Config
from monitor.http import Blocked
from monitor.parsers import extract_next_data, parse_store_page, store_home_paths
from monitor.scan import load_store_list, scan_stores
from monitor.state import State

LOG = logging.getLogger("test")
NOW = 1_800_000_000
STORE = f"{BASE}/tiendas/66887-turbo-market-nc"
BRAND = f"{BASE}/lima/tiendas/marca-turbo"


def test_market_enabled_by_default_and_can_be_disabled():
    assert Config.from_env({}).check_market
    assert not Config.from_env({"REVISAR_RAPPI_MARKET": "no"}).check_market


def test_turbo_directory_extends_list_and_invalidates_old_cache(cfg, store_pages):
    state = State()
    state.set_stores([(999, "old")], NOW)
    cfg.check_market = True
    http = FakeHttp({**store_pages, BRAND: fixture_text("turbo_lima.html")})
    stores = load_store_list(cfg, http, state, NOW, LOG)
    assert (25321, "turbo") in stores and (27032, "turbo") in stores
    assert (62365, "wong") in stores and (999, "old") not in stores
    http.calls.clear()
    assert load_store_list(cfg, http, state, NOW + 60, LOG) == stores
    assert not http.calls
    cfg.check_market = False
    stores = load_store_list(cfg, http, state, NOW + 120, LOG)
    assert (25321, "turbo") not in stores


def test_empty_turbo_directory_is_not_silent_success(cfg, store_pages):
    cfg.check_market = True
    result = scan_stores(cfg, FakeHttp(store_pages), State(), NOW, LOG)
    assert "directorio" in result.error


def test_home_paths_only_follow_same_store_and_bazar():
    html = '''<a href="/tiendas/66887-turbo-market-nc/hogar-y-vehiculos">Hogar</a>
    <a href="/tiendas/66887-turbo-market-nc/hogar-y-vehiculos">Repetido</a>
    <a href="/tiendas/66887-turbo-market-nc/cuidado-del-hogar">Limpieza</a>
    <a href="/tiendas/123-other/hogar-y-bazar">Otra tienda</a>
    <a href="https://example.org/tiendas/66887-turbo-market-nc/hogar">Externo</a>'''
    assert store_home_paths(html, 66887) == ["/tiendas/66887-turbo-market-nc/hogar-y-vehiculos"]


def market_pages():
    # Estructura real recortada; precios cambiados SOLO para la regresión.
    data = extract_next_data(fixture_text("store_turbo_bazar.html"))
    products = data['props']['pageProps']['fallback']['storefront/25321-turbo/hogar-y-bazar'][
        'sub_aisles_response']['data']['components'][0]['resource']['products']
    products[0].update(product_id="bazar-test", price=20, real_price=100, in_stock=True)
    products[1].update(product_id="sold-out-test", price=5, real_price=100, in_stock=False)
    products.append(dict(products[0]))  # no duplicar un producto entre componentes
    return {BRAND: '<a href="/tiendas/66887-turbo-market-nc">Turbo</a>',
            STORE + "/ofertas": fixture_text("store_turbo_market_offers.html"),
            STORE + "/hogar-y-vehiculos": '<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>'}


def test_market_bazar_offers_are_included_and_deduplicated(cfg):
    cfg.check_market = True
    cfg.store_types = []
    result = scan_stores(cfg, FakeHttp(market_pages()), State(), NOW, LOG)
    assert result.error is None and result.checked == 1
    assert len(result.alerts) == 1
    assert [(o.product_id, o.pct) for o in result.alerts[0].offers] == [("bazar-test", 80)]
    assert any("1 locales y 1 pasillos" in note for note in result.notes)


@pytest.mark.parametrize("error", [Blocked("Rappi respondió 403"), TimeoutError("lento")])
def test_bazar_failure_is_visible(cfg, error):
    cfg.check_market = True
    cfg.store_types = []
    http = FakeHttp(market_pages(), errors={STORE + "/hogar-y-vehiculos": error})
    result = scan_stores(cfg, http, State(), NOW, LOG)
    assert result.error
    assert result.blocked == isinstance(error, Blocked)


def test_real_turbo_fixture_can_be_read():
    name, offers = parse_store_page(extract_next_data(fixture_text("store_turbo_market_offers.html")))
    assert name == "Turbo" and offers

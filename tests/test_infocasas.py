from pathlib import Path

from monitor.catalogs import CatalogState
from monitor.http import Blocked
from monitor.infocasas import listing_data, parse_item, site_rate, scan_listings, evaluate_listing, SEARCHES
import monitor.infocasas as infocasas

FIX = Path(__file__).parent / 'fixtures'
DAY = 20714


def page():
    return (FIX / 'infocasas_venta.html').read_text(encoding='utf-8')


def home(op, usd, area=80.0, lat=-12.1203, mant=0.0, flags=(), prices=None):
    return {'op': op, 'tipo': 'departamentos', 'usd': usd, 'area': area, 'lat': lat, 'lng': -77.0300, 'mon': 'USD',
            'monto': usd, 'mant': mant, 'anio': '', 'dorm': '2', 'zona': 'Miraflores', 'titulo': 'Depa',
            'u': 'https://www.infocasas.com.pe/x/1', 'flags': list(flags), 'p': [[DAY, p] for p in (prices or [usd])],
            'f': DAY, 'r': DAY, 'dist': 'miraflores'}


def zone(**extra):
    # 8 alquileres a US$ 10/m² y 8 ventas a US$ 2.500/m²: rentabilidad de la zona 4,8 %.
    store = {f'a{i}': home('alquiler', 800 + i, lat=-12.12 + i * 0.0005) for i in range(8)}
    store.update({f'v{i}': home('venta', 200000 + i * 100, lat=-12.12 + i * 0.0005) for i in range(8)})
    store['lejos'] = home('alquiler', 3000, lat=-12.20)
    store.update(extra)
    return store


def test_real_listing_page_reads_price_area_location_and_bad_words():
    items, last = listing_data(page())
    assert last == 2 and len(items) == 4
    rate = site_rate(items, 3.5)
    assert 3.3 < rate < 3.45
    first = parse_item(items[0], 'departamentos', rate)
    assert (first['op'], first['usd'], first['area'], first['mon']) == ('venta', 210000.0, 144.0, 'USD')
    assert first['zona'] == 'Miraflores' and first['u'].startswith('https://www.infocasas.com.pe/') and first['mant'] > 0
    soles = parse_item(items[3], 'departamentos', rate)
    assert soles['mon'] == 'PEN' and soles['monto'] == 1699300 and round(soles['usd']) == 503095


def test_wrong_operation_prices_are_dropped():
    items, _ = listing_data(page())
    item = dict(items[0], price_amount_usd=900)
    assert parse_item(item, 'departamentos', 3.4) is None


def test_yield_needs_both_sides_and_flags_cheap_sale():
    store = zone(x=home('venta', 130000))
    score, lines = evaluate_listing(store, 'x', DAY, 3.4)
    assert 'rentabilidad estimada 7.4% (su zona: 4.8%) 🚨' in lines[1] and '8 alquileres parecidos' in lines[2]
    only_sales = {k: v for k, v in store.items() if v['op'] == 'venta'}
    assert evaluate_listing(only_sales, 'x', DAY, 3.4) is None


def test_more_than_twice_the_zone_is_a_warning_not_a_deal_and_bad_words_block():
    assert evaluate_listing(zone(x=home('venta', 90000)), 'x', DAY, 3.4) is None
    assert evaluate_listing(zone(x=home('venta', 130000, flags=['ocupado'])), 'x', DAY, 3.4) is None
    assert evaluate_listing(zone(x=home('venta', 190000)), 'x', DAY, 3.4) is None


def test_maintenance_lowers_the_estimated_rent():
    plain = evaluate_listing(zone(x=home('venta', 140000)), 'x', DAY, 3.4)
    costly = evaluate_listing(zone(x=home('venta', 140000, mant=150)), 'x', DAY, 3.4)
    assert plain and costly is None


def test_price_drop_on_sale_is_reported():
    score, lines = evaluate_listing({'x': home('venta', 180000, prices=[200000, 180000])}, 'x', DAY, 3.4)
    assert 'bajó 10%' in lines[1]


def test_rotation_resumes_unfinished_search_and_stops_on_block(monkeypatch):
    monkeypatch.setattr(infocasas, 'REGIONAL_SEARCHES', {})  # aislar el cursor legado de Lima
    monkeypatch.setenv('PAGINAS_INFOCASAS', '10')
    calls = []

    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url):
            calls.append(url)
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow: /venta/*-y-*'
            return page()

    state = CatalogState()
    fresh, read, error = scan_listings(state, DAY * 86400, 3.5, Client)
    listed = [c for c in calls if 'robots' not in c]
    assert read == 10 and error is None and all('publicado-ultimos-30-dias' in c for c in listed)
    assert listed[1].endswith('/pagina2') and state.datos['infocasas']['turno'] == 5
    assert set(fresh) == {'193465467', '193465492', '193636298', '185573206'}
    assert state.datos['infocasas']['avisos']['193465492']['flags'] == ['derechos y acciones']

    class Blocking(Client):
        def get(self, url):
            if not url.endswith('robots.txt'): raise Blocked('403')
            return super().get(url)

    _, _, error = scan_listings(state, DAY * 86400, 3.5, Blocking)
    assert error == 'acceso bloqueado; no se insiste' and state.datos['infocasas']['turno'] == 5
    assert len(SEARCHES) == 43 * 4


def test_resume_page_when_one_search_exceeds_round_budget(monkeypatch):
    monkeypatch.setattr(infocasas, 'REGIONAL_SEARCHES', {})
    import json
    monkeypatch.setenv('PAGINAS_INFOCASAS', '10')
    calls = []
    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url):
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow:'
            calls.append(url)
            return page()
    import monitor.infocasas as module
    monkeypatch.setattr(module, 'listing_data', lambda html: ([], 25))
    state = CatalogState()
    scan_listings(state, DAY * 86400, 3.5, Client)
    assert state.datos['infocasas'].get('turno', 0) == 0
    assert state.datos['infocasas']['pagina'] == 11
    calls.clear()
    scan_listings(state, DAY * 86400, 3.5, Client)
    assert calls[0].endswith('/pagina11')
    assert state.datos['infocasas']['pagina'] == 21


def test_republished_listing_counts_once():
    from monitor.infocasas import comparables
    store = zone(x=home('venta', 130000))
    # El mismo alquiler publicado otra vez con otro id no suma un comparable.
    store['copia'] = dict(store['a3'])
    assert comparables(store, store['x'], 'alquiler', DAY)[1] == 8
    store['otro'] = home('alquiler', 820, lat=-12.1188)
    assert comparables(store, store['x'], 'alquiler', DAY)[1] == 9

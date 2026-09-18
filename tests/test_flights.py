from dataclasses import replace
from datetime import date
from pathlib import Path
import json
import logging
import pytest

from monitor.catalogs import CatalogState, deal_text, deliver
from monitor.config import Config
from monitor.flights import jetsmart_fares, sky_fares, observe_flight, scan_flights, JET_URL, SKY_URL
from monitor.http import Blocked

FIX = Path(__file__).parent / 'fixtures'
NOW = 1789689600  # 2026-09-18 UTC

def jet():
    return (FIX / 'jetsmart_flights.html').read_text(encoding='utf-8')

def sky():
    return (FIX / 'sky_flights.html').read_text(encoding='utf-8')

def fare():
    return jetsmart_fares(jet(), date(2026, 9, 17))[0]

def history(state, deal, count=3, price=400):
    for offset in range(count, 0, -1):
        assert observe_flight(state, replace(deal, price=price), NOW - offset * 86400) is None

def test_real_jet_uses_taxes_outbound_only_and_future_lima():
    deals = jetsmart_fares(jet(), date(2026, 9, 17))
    assert len(deals) == 2
    cja = next(d for d in deals if 'CJA' in d.name)
    assert cja.price == 133.65 and cja.currency == 'PEN'
    assert 'Tasas incluidas' in cja.condition and '7318' in cja.condition
    assert not jetsmart_fares(jet(), date(2028, 1, 1))

def test_real_sky_excludes_other_origins_and_preserves_usd_and_taxes():
    deals = sky_fares(sky(), date(2026, 9, 17))
    assert deals and all(d.currency == 'USD' for d in deals)
    assert all('Lima (LIM)' in d.name and '+ tasas' in d.condition for d in deals)
    assert len({d.history_key for d in deals}) == len(deals)

@pytest.mark.parametrize('parser', [jetsmart_fares, sky_fares])
def test_changed_html_is_not_success(parser):
    with pytest.raises(ValueError): parser('<html>captcha</html>', date(2026, 9, 17))

def test_no_alert_on_first_read_or_short_history():
    state = CatalogState(); deal = fare()
    history(state, deal, count=2)
    assert observe_flight(state, replace(deal, price=100), NOW) is None

def test_exact_threshold_minimum_not_peak_and_not_rounded_up():
    deal = fare(); state = CatalogState(); history(state, deal)
    assert observe_flight(state, replace(deal, price=200.01), NOW) is None
    alert = observe_flight(state, replace(deal, price=200), NOW)
    assert alert and alert.pct == 50 and alert.regular == 400
    # One historical low prevents a misleading comparison against an earlier high.
    state = CatalogState(); history(state, deal)
    state.observe(replace(deal, price=150), NOW - 86400)
    assert observe_flight(state, replace(deal, price=100), NOW) is None

def test_stale_history_and_different_itinerary_are_not_comparable():
    state = CatalogState(); deal = fare(); history(state, deal)
    assert observe_flight(state, replace(deal, price=100), NOW + 31 * 86400) is None
    assert observe_flight(state, replace(deal, identity='different-date', price=100), NOW) is None
    a = jetsmart_fares(jet(), date(2026,9,17))[0]
    b = jetsmart_fares(jet().replace('2026-10-20 04:50:00', '2026-10-21 04:50:00'), date(2026,9,17))[0]
    assert a.history_key != b.history_key

def test_failed_delivery_can_retry_after_baseline_updated_and_restart(tmp_path):
    state = CatalogState(); deal = fare(); history(state, deal)
    alert = observe_flight(state, replace(deal, price=100), NOW)
    class Notifier:
        cfg = Config()
        ok = False
        def send(self, *args, **kwargs): return self.ok
    notifier = Notifier()
    assert deliver([alert], state, notifier, NOW, 'viajes') == (0, True)
    path = tmp_path / 'state.json'; state.save(path, NOW)
    state = CatalogState.load(path, logging.getLogger())
    retry = observe_flight(state, replace(deal, price=100), NOW + 86400)
    assert retry and retry.regular == 400
    notifier.ok = True
    assert deliver([retry], state, notifier, NOW + 86400, 'viajes') == (1, False)
    assert deliver([retry], state, notifier, NOW + 86401, 'viajes') == (0, False)
    state.prune(NOW + 8 * 86400, 336)
    assert not state.flight_alerts

def test_flight_message_does_not_claim_published_discount_or_soles_for_usd():
    deal = sky_fares(sky(), date(2026,9,17))[0]
    text = deal_text(replace(deal, price=25, regular=50, pct=50))
    assert 'USD 25.00' in text and 'Caída observada' in text and '+ tasas' in text
    assert 'S/' not in text and 'referencia publicada' not in text

@pytest.mark.parametrize('blocked', [True, False])
def test_robots_or_block_stops_source_before_catalog(blocked):
    calls = []
    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url):
            calls.append(url)
            if blocked: raise Blocked('403')
            return 'User-agent: *\nDisallow: /'
    deals, reports = scan_flights(CatalogState(), NOW, Client, [('JetSMART', JET_URL, jetsmart_fares)])
    assert not deals and reports[0][2] and len(calls) == 1

def test_scan_persists_initial_history_without_false_discount():
    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url):
            return 'User-agent: *\nDisallow: /booking' if url.endswith('robots.txt') else jet()
    state = CatalogState()
    deals, reports = scan_flights(state, NOW, Client, [('JetSMART', JET_URL, jetsmart_fares)])
    assert not deals and reports == [('JetSMART/tarifas desde Lima', 2, None)]
    assert len(state.history) == 2

@pytest.mark.parametrize('pages, count, failed', [
    (['<title>JetSMART</title>', jet()], 2, False),
    (['<title>JetSMART</title>', '<title>JetSMART</title>', jet()], 0, False),
])
def test_light_jetsmart_page_is_read_once_more_then_reported(pages, count, failed):
    calls = []
    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url):
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow: /booking'
            calls.append(url)
            return pages[len(calls) - 1]
    _, reports = scan_flights(CatalogState(), NOW, Client, [('JetSMART', JET_URL, jetsmart_fares)])
    assert len(calls) == 2 and reports[0][1] == count and bool(reports[0][2]) == failed

def test_sky_spa_robots_is_absence_of_rules_but_explicit_disallow_wins():
    class Client:
        user_agent = 'Mozilla/5.0'
        rules = '<title>Sky</title><script src="/sky-root-config.js"></script>'
        def __init__(self, **kw): pass
        def get(self, url): return self.rules if url.endswith('robots.txt') else sky()
    sources = [('SKY', SKY_URL, sky_fares)]
    _, reports = scan_flights(CatalogState(), NOW, Client, sources)
    assert reports[0][1] > 0 and not reports[0][2]
    Client.rules += '\nUser-agent: *\nDisallow: /flights/'
    _, reports = scan_flights(CatalogState(), NOW, Client, sources)
    assert reports[0][2]

def test_currency_class_and_date_change_comparison_identity():
    original = sky_fares(sky(), date(2026,9,17))[0]
    for changed in [sky().replace('"USD"', '"PEN"'),
                    sky().replace('"economy"', '"business"'),
                    sky().replace('2026-12-07', '2026-12-08')]:
        assert sky_fares(changed, date(2026,9,17))[0].history_key != original.history_key

def test_existing_state_saves_history_even_without_notifications(tmp_path):
    path = tmp_path / 'viajes.json'
    state = CatalogState(); state.save(path, NOW - 86400)
    loaded = CatalogState.load(path)
    assert not loaded.changed()
    assert observe_flight(loaded, fare(), NOW) is None
    loaded.prune(NOW, 336)
    assert loaded.changed() and loaded.save(path, NOW)
    assert len(CatalogState.load(path).history) == 1
    assert not loaded.changed()
    loaded.cursors['test'] = 3
    assert loaded.changed()


from monitor.flights import observe_distance, distance_km, travelpayouts_directions, scan_travelpayouts, BAND_MIN


def test_distance_band_needs_its_own_history_then_flags_half_price_per_km():
    state = CatalogState()
    km = distance_km('LIM', 'CUZ')
    for i in range(BAND_MIN):
        other = replace(fare(), identity=f'ruta-{i}', price=200 + i)
        assert observe_distance(state, other, NOW, 'JetSMART|PEN', km) is None
    cheap = observe_distance(state, replace(fare(), price=95), NOW, 'JetSMART|PEN', km)
    assert cheap and cheap.reference_kind == 'flight_distance' and cheap.pct >= 50
    assert 'centavos/km' in cheap.condition and 'tramo nacional' in cheap.condition
    text = deal_text(cheap)
    assert 'bajo lo normal para esa distancia' in text and 'no descuento anunciado' in text
    # Una quinta parte de lo normal no es ganga: es un error de datos.
    assert observe_distance(state, replace(fare(), identity='raro', price=20), NOW, 'JetSMART|PEN', km) is None


def test_distance_alert_key_ignores_moving_median():
    state = CatalogState()
    km = distance_km('LIM', 'CUZ')
    for i in range(BAND_MIN):
        observe_distance(state, replace(fare(), identity=f'r{i}', price=200 + i), NOW, 'b', km)
    first = observe_distance(state, replace(fare(), price=95), NOW, 'b', km)
    for i in range(15): observe_distance(state, replace(fare(), identity=f'extra{i}', price=400), NOW, 'b', km)
    second = observe_distance(state, replace(fare(), price=95), NOW, 'b', km)
    assert first.pct != second.pct and first.key == second.key


TP = {'success': True, 'currency': 'usd', 'error': None, 'data': {
    'MAD': {'origin': 'LIM', 'destination': 'MAD', 'price': 690, 'transfers': 1, 'airline': 'IB', 'flight_number': 6650,
            'departure_at': '2026-11-10T20:00:00Z', 'return_at': '2026-11-24T10:00:00Z', 'expires_at': '2026-09-20T00:00:00Z'},
    'OLD': {'origin': 'LIM', 'destination': 'BOG', 'price': 150, 'transfers': 0, 'airline': 'AV', 'flight_number': 1,
            'departure_at': '2026-09-01T10:00:00Z', 'return_at': '', 'expires_at': '2026-09-20T00:00:00Z'}}}


def test_travelpayouts_reads_round_trips_and_skips_past_or_expired():
    fares = travelpayouts_directions(TP, date(2026, 9, 17), NOW)
    assert len(fares) == 1 and fares[0].currency == 'USD' and 'Ida y vuelta' in fares[0].condition
    assert 'Madrid (MAD)' in fares[0].name and fares[0].url.endswith('LIM1011MAD24111')
    assert 'no tarifa en vivo' in fares[0].condition
    with pytest.raises(ValueError): travelpayouts_directions(dict(TP, currency='rub'), date(2026, 9, 17), NOW)


def test_travelpayouts_needs_token_and_runs_every_six_hours():
    calls = []
    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url, headers=None):
            calls.append((url, headers))
            return json.dumps(TP)
    state = CatalogState()
    assert scan_travelpayouts(state, NOW, token='', http_factory=Client) == ([], [])
    _, reports = scan_travelpayouts(state, NOW, token='secreto', http_factory=Client)
    assert reports == [('Travelpayouts/destinos desde Lima', 1, None)]
    assert all('secreto' not in url and headers == {'X-Access-Token': 'secreto'} for url, headers in calls)
    assert scan_travelpayouts(state, NOW + 3600, token='secreto', http_factory=Client) == ([], [])


def test_light_page_three_rounds_in_a_row_becomes_an_error_and_success_resets():
    class Client:
        user_agent = 'Mozilla/5.0'
        pages = []
        def __init__(self, **kw): pass
        def get(self, url):
            return 'User-agent: *\nDisallow: /booking' if url.endswith('robots.txt') else Client.pages.pop(0)
    state = CatalogState()
    sources = [('JetSMART', JET_URL, jetsmart_fares)]
    for expected in (False, False, True):
        Client.pages = ['<title>JetSMART</title>'] * 2
        _, reports = scan_flights(state, NOW, Client, sources)
        assert bool(reports[0][2]) == expected
    Client.pages = [jet()]
    _, reports = scan_flights(state, NOW, Client, sources)
    assert reports[0][1] == 2 and not reports[0][2] and 'JetSMART/portada-sin-tarifas' not in state.cursors
    Client.pages = ['<html>otra cosa</html>'] * 2   # si no es la portada de JetSMART, falla de inmediato
    _, reports = scan_flights(state, NOW, Client, sources)
    assert reports[0][2]

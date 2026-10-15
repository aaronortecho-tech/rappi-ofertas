import json
from copy import deepcopy
from datetime import date
from urllib.parse import parse_qs, urlsplit

from monitor.catalogs import CatalogState, run_group
from monitor.config import Config
from monitor.flights import dated_fares, scan_flight_dates
from monitor.http import Blocked

NOW = 1789689600
ROW = dict(origin='LIM', destination='MAD', origin_airport='LIM', destination_airport='MAD',
           airline='IB', flight_number='6650', departure_at='2026-11-10T20:00:00Z',
           return_at='2026-11-24T10:00:00Z', transfers=0, return_transfers=1, price=700)


def payload(row=None):
    return dict(success=True, currency='usd', data=[deepcopy(row or ROW)])


def test_dates_do_not_mix_return_stops_airports_or_trip_types():
    today = date(2026, 9, 18)
    original = dated_fares(payload(), today, False)[0]
    for change in (dict(return_transfers=0), dict(destination_airport='BCN')):
        other = dated_fares(payload(dict(ROW, **change)), today, False)[0]
        assert other.history_key != original.history_key
        assert other.flight_context['service'] != original.flight_context['service']
    assert dated_fares(payload(), today, True) == []
    assert dated_fares(payload(dict(ROW, return_transfers=None)), today, False) == []
    assert dated_fares(payload(dict(ROW, departure_at='invalid')), today, False) == []
    assert dated_fares(payload(dict(ROW, price=-1)), today, False) == []


def test_expansion_queries_months_without_route_combinatorics_and_throttles():
    calls = []
    class Client:
        def __init__(self, **kw): pass
        def get(self, url, headers):
            assert 'secret' not in url and headers == {'X-Access-Token': 'secret'}
            query = parse_qs(urlsplit(url).query)
            calls.append(query)
            row = dict(ROW, return_at='', return_transfers=None) if query['one_way'] == ['true'] else ROW
            return json.dumps(payload(row))
    state = CatalogState()
    deals, reports = scan_flight_dates(state, NOW, token='secret', http_factory=Client)
    assert not deals and reports[0][1] == 3 and not reports[0][2]
    assert [c['departure_at'][0] for c in calls] == ['2026-09', '2026-10', '2026-11']
    assert all('destination' not in c and c['unique'] == ['false'] for c in calls)
    assert scan_flight_dates(state, NOW+1800, token='secret', http_factory=Client) == ([], [])
    scan_flight_dates(state, NOW+21600, token='secret', http_factory=Client)
    assert len(calls) == 6 and calls[-1]['one_way'] == ['false']


def test_blocked_expansion_stops_and_does_not_retry_every_half_hour():
    calls = []
    class Client:
        def __init__(self, **kw): pass
        def get(self, url, headers): calls.append(url); raise Blocked('no')
    state = CatalogState()
    _, reports = scan_flight_dates(state, NOW, token='secret', http_factory=Client)
    assert reports[0][2] and len(calls) == 1
    assert scan_flight_dates(state, NOW+1800, token='secret', http_factory=Client) == ([], [])


def test_persistent_incident_only_notifies_once_until_sustained_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv('NTFY_TOPIC_VIAJES', 'test')
    messages = []
    class Sink:
        cfg = Config()
        def send(self, title, message, **kw): messages.append(title); return True
    path = str(tmp_path/'viajes.json')
    def round_at(i, ok=False):
        report = [('JetSMART/tarifas desde Lima', 12 if ok else 0, None if ok else 'revisión incompleta')]
        run_group('viajes', now=NOW+i*86400, scanner=lambda s,n: ([], report), notifier=Sink(), state_path=path)
    for i in range(5): round_at(i)
    round_at(5, True)
    for i in range(6, 11): round_at(i)
    assert len(messages) == 1
    for i in range(11, 17): round_at(i, True)
    for i in range(17, 20): round_at(i)
    assert len(messages) == 2

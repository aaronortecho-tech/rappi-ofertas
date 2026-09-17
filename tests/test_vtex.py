import copy
import json
from pathlib import Path
import pytest
from monitor.catalogs import CatalogState
from monitor.http import Blocked
from monitor.vtex import SOURCES, parse_products, scan_vtex

FIXTURES = Path(__file__).parent / 'fixtures'

@pytest.mark.parametrize('source,domain', SOURCES)
def test_real_catalogs(source, domain):
    raw = (FIXTURES / ('vtex_' + source.lower() + '.json')).read_text(encoding='utf-8')
    deals, count = parse_products(raw, source, domain)
    assert count == 8
    assert deals
    assert all(60 <= d.pct < 95 and d.price >= 10 and d.seller for d in deals)

def product():
    rows = json.loads((FIXTURES / 'vtex_estilos.json').read_text(encoding='utf-8'))
    row = copy.deepcopy(rows[0])
    row['items'] = row['items'][:1]
    row['items'][0]['sellers'] = row['items'][0]['sellers'][:1]
    row['items'][0]['sellers'][0]['commertialOffer'] = {
        'Price': 40, 'ListPrice': 100, 'AvailableQuantity': 2, 'IsAvailable': True}
    return row

@pytest.mark.parametrize('changes', [ {'Price': 40.01}, {'Price': 9.99},
    {'ListPrice': None}, {'Price': 10, 'ListPrice': 200}, {'AvailableQuantity': 0},
    {'IsAvailable': False}, {'Price': 'NaN'}, {'ListPrice': 'Infinity'}])
def test_invalid_or_below_threshold_prices(changes):
    row = product()
    row['items'][0]['sellers'][0]['commertialOffer'].update(changes)
    assert not parse_products(json.dumps([row]), 'Estilos', 'www.estilos.com.pe')[0]

def test_exact_threshold_and_category_url_filters():
    row = product()
    assert parse_products(json.dumps([row]), 'Estilos', 'www.estilos.com.pe')[0][0].pct == 60
    for field, value in [('categories', ['/Belleza/']), ('link', 'https://example.com/p')]:
        changed = copy.deepcopy(row); changed[field] = value
        assert not parse_products(json.dumps([changed]), 'Estilos', 'www.estilos.com.pe')[0]

def test_dedup_shared_marketplace():
    row = product()
    first = parse_products(json.dumps([row]), 'Estilos', 'www.estilos.com.pe')[0][0]
    row['link'] = row['link'].replace('www.estilos.com.pe', 'www.promart.pe')
    second = parse_products(json.dumps([row]), 'Promart', 'www.promart.pe')[0][0]
    assert first.key == second.key
    second.price += 1
    assert first.key != second.key

@pytest.mark.parametrize('robots', ['User-agent: *\nDisallow: /api/', None, 'blocked'])
def test_no_catalog_request_without_robots_permission(robots):
    calls = []
    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url): calls.append(url); return robots
    deals, reports = scan_vtex(CatalogState(), 1, Client, [('Estilos', 'www.estilos.com.pe')])
    assert not deals and reports[0][2]
    assert len(calls) == 1

def test_block_is_reported_and_next_site_is_independent():
    calls = []
    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url):
            calls.append(url)
            if 'promart' in url: raise Blocked('403')
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow: /checkout'
            return json.dumps([product()])
    deals, reports = scan_vtex(CatalogState(), 1, Client, SOURCES[:1] + SOURCES[2:3])
    assert reports[0][2] and not reports[1][2] and len(deals) == 1
    assert len(calls) == 3

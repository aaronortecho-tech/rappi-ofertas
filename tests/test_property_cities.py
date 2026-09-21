import json
from pathlib import Path

import pytest

from monitor.catalogs import CatalogState
from monitor import infocasas, inmuebles
from monitor.property_cities import CITIES, city_at, bank_city
from monitor.http import Blocked

FIX = Path(__file__).parent/'fixtures'
NOW = 1790000000
CENTERS = {'lima': (-12.12, -77.03), 'arequipa': (-16.4, -71.54),
           'cusco': (-13.53, -71.97), 'cajamarca': (-7.16, -78.51),
           'trujillo': (-8.11, -79.03), 'huaraz': (-9.53, -77.53)}


@pytest.mark.parametrize('city', CITIES)
def test_accepts_city_coordinates_and_rejects_wrong_search(city):
    rows, _ = infocasas.listing_data((FIX/'infocasas_venta.html').read_text(encoding='utf-8'))
    row = dict(rows[0], latitude=CENTERS[city][0], longitude=CENTERS[city][1])
    assert city_at(*CENTERS[city]) == city
    assert infocasas.parse_item(row, 'departamentos', 3.5, city)['ciudad'] == city
    other = 'lima' if city != 'lima' else 'cusco'
    assert infocasas.parse_item(row, 'departamentos', 3.5, other) is None
    assert city_at(float('nan'), -77) is None
    assert city_at(0, 0) is None


@pytest.mark.parametrize('city,filename', [('arequipa','arequipa'), ('cusco','cusco')])
def test_real_nexo_regional_fixtures(city, filename):
    url = ('https://nexoinmobiliario.pe/departamentos/arequipa/luzzo-cerro-colorado-3197'
           if city == 'arequipa' else 'https://nexoinmobiliario.pe/departamentos/cusco/lumine-3513')
    _, project = inmuebles.parse_project((FIX/f'nexo_{filename}.html').read_text(encoding='utf-8'), url)
    assert project['ciudad'] == city and project['modelos']


def test_real_infocasas_fixtures_exclude_misclassified_lima():
    data = json.loads((FIX/'infocasas_ciudad_arequipa_departamentos_venta.json').read_text(encoding='utf-8'))
    parsed = [infocasas.parse_item(row, 'departamentos', 3.5, 'arequipa') for row in data['data']]
    assert parsed[0] is None and any(p and p['ciudad'] == 'arequipa' for p in parsed[1:])
    cusco = json.loads((FIX/'infocasas_ciudad_cusco_departamentos_venta.json').read_text(encoding='utf-8'))
    assert infocasas.parse_item(cusco['data'][0], 'departamentos', 3.5, 'cusco')['ciudad'] == 'cusco'


def test_city_cursors_share_budget_and_preserve_lima_progress(monkeypatch):
    monkeypatch.setenv('PAGINAS_INFOCASAS', '60')
    state = CatalogState(); state.datos['infocasas'] = {'turno': 7, 'pagina': 2}
    calls = []
    class Client:
        user_agent = 'test'
        def __init__(self, **kwargs): pass
        def get(self, url):
            calls.append(url)
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow:'
            # Lima tiene muchas páginas; las ciudades, una por búsqueda.
            last = 100 if '/lima/' in url else 1
            return '<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':{'fetchResult':{
                'searchFast':{'data':[], 'paginatorInfo':{'lastPage':last}}}}}})+'</script>'
    _, read, error = infocasas.scan_listings(state, NOW, 3.5, Client)
    assert read == 60 and error is None and len(calls) == 61
    assert calls[1].endswith('/pagina2')
    data = state.datos['infocasas']
    assert data['turno'] == 7 and data['pagina'] == 42
    assert data['ultima_cobertura']['lima']['paginas'] == 40
    for city in infocasas.REGIONAL_SEARCHES:
        assert data['ultima_cobertura'][city]['paginas'] == 4
        assert data['rotacion_ciudades'][city] == {'turno':0, 'pagina':1}


def test_block_stops_all_city_requests():
    calls = []
    class Client:
        user_agent = 'test'
        def __init__(self, **kwargs): pass
        def get(self, url):
            calls.append(url)
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow:'
            raise Blocked('403')
    _, read, error = infocasas.scan_listings(CatalogState(), NOW, 3.5, Client)
    assert error and read == 0 and len(calls) == 2


def test_real_bank_provinces_and_non_target_exclusion():
    data = json.loads((FIX/'scotia_ciudades.json').read_text(encoding='utf-8'))
    assert {v['ciudad'] for v in data.values()} == set(CITIES)-{'lima'}
    assert all(bank_city(v['texto']) == v['ciudad'] for v in data.values())
    assert bank_city('AV AREQUIPA 123 LIMA LIMA LINCE') == 'lima'
    assert bank_city('AV CUSCO LORETO MAYNAS IQUITOS') is None
    assert bank_city('CALLE 1 CUZCO CUZCO WANCHAQ') == 'cusco'


def test_comparables_remain_local_and_old_lima_memory_works():
    row = {'op':'venta','tipo':'departamentos','usd':100000.,'area':80.,'lat':-16.4,'lng':-71.54,'r':NOW//86400}
    store = {'target':row}
    for i in range(8):
        store[f'a{i}'] = dict(row, op='alquiler', usd=500., lat=-16.4005-i*.0002)
        store[f'l{i}'] = dict(row, op='alquiler', usd=1500., lat=-12.12-i*.0002,lng=-77.03)
    median, count = infocasas.comparables(store,row,'alquiler',NOW//86400)
    assert count == 8 and median == 6.25
    lima = dict(row,lat=-12.119,lng=-77.03)
    assert infocasas.comparables(store,lima,'alquiler',NOW//86400) == (18.75,8)


def test_bank_scan_alerts_regional_drop_but_excludes_outside_and_unregistered(monkeypatch):
    rows = {'a': {'texto':'CALLE 1 ANCASH HUARAZ HUARAZ', 'ciudad':'huaraz', 'inscrito':True,
                  'valor':90000., 'area':'80 m2', 'clase':'VIVIENDA'},
            'b': {'texto':'CALLE 2 LORETO MAYNAS IQUITOS', 'ciudad':None, 'inscrito':True,
                  'valor':90000., 'area':'80 m2', 'clase':'VIVIENDA'},
            'c': {'texto':'CALLE 3 AREQUIPA AREQUIPA CAYMA', 'ciudad':'arequipa', 'inscrito':False,
                  'valor':90000., 'area':'80 m2', 'clase':'VIVIENDA'}}
    monkeypatch.setattr(inmuebles, 'scotia_rows', lambda raw: rows)
    class Client:
        def __init__(self, **kwargs): pass
        def get_bytes(self, url): return b'PDF'
    state = CatalogState(); state.datos['scotiabank'] = {'filas':{key:{'valor':100000.} for key in rows}}
    found, reports = inmuebles.scan_scotia(state,NOW,Client)
    assert [r[0] for r in found] == ['a']
    assert 'Huaraz' in found[0][-1][0] and 'bajó 10%' in found[0][-1][1]


def test_regional_pagination_resumes_without_starving_other_cities(monkeypatch):
    monkeypatch.setenv('PAGINAS_INFOCASAS','60')
    monkeypatch.setattr(infocasas,'listing_data',lambda html: ([],20 if html=='arequipa' else 1))
    class Client:
        user_agent='test'
        def __init__(self,**kwargs): pass
        def get(self,url):
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow:'
            return 'arequipa' if '/arequipa/' in url else 'other'
    state=CatalogState()
    infocasas.scan_listings(state,NOW,3.5,Client)
    rotation=state.datos['infocasas']['rotacion_ciudades']
    assert rotation['arequipa']=={'turno':0,'pagina':5}
    assert rotation['huaraz']=={'turno':0,'pagina':1}
    infocasas.scan_listings(state,NOW+21600,3.5,Client)
    assert rotation['arequipa']=={'turno':0,'pagina':9}

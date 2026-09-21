from pathlib import Path

from monitor.catalogs import CatalogState
from monitor.inmuebles import parse_project, evaluate_project, update_project, scotia_text_rows, scan_inmuebles
import monitor.inmuebles as inmuebles

FIX = Path(__file__).parent / 'fixtures'
URL = 'https://nexoinmobiliario.pe/departamentos/miraflores/lima-15-3978'
DAY = 20700
RATE = 3.5


def project(m2_price, lat=-12.1175, lng=-77.0333, models=None):
    models = models or {'A': [80.0, 2, 'PEN', 80.0 * m2_price]}
    return {'u': URL, 'tipo': 'departamentos', 'dist': 'Miraflores', 'nombre': 'Proyecto', 'marca': '',
            'lat': lat, 'lng': lng, 'etapa': 'en planos', 'modelos': models,
            'primero': {k: [v[2], v[3], DAY] for k, v in models.items()}, 'r': DAY, 'x': DAY}


def zone(**extra):
    store = {f'n{i}': project(10000 + i * 10, lat=-12.1175 + i * 0.001) for i in range(8)}
    store['far'] = project(3000, lat=-12.20)  # a más de 1,5 km: no cuenta
    store.update(extra)
    return store


def test_real_project_page_reads_models_location_and_stage():
    pid, data = parse_project((FIX / 'nexo_proyecto.html').read_text(encoding='utf-8'), URL)
    assert pid == '3978' and data['dist'] == 'Miraflores' and data['etapa'] == 'en planos'
    assert data['modelos']['Modelo 1A'] == [85.25, 1, 'PEN', 714000.0]
    assert (data['lat'], data['lng']) == (-12.11752, -77.0333)


def test_micro_zone_needs_eight_nearby_projects():
    store = {f'n{i}': project(10000) for i in range(7)}
    store['x'] = project(7000)
    assert evaluate_project(store, 'x', RATE, DAY) is None
    score, lines = evaluate_project(zone(x=project(7000)), 'x', RATE, DAY)
    assert '30% bajo la zona' in lines[1] and 'Mediana de 8 proyectos' in lines[2]


def test_absurd_gap_is_treated_as_data_error_and_small_gap_ignored():
    assert evaluate_project(zone(x=project(4000)), 'x', RATE, DAY) is None
    assert evaluate_project(zone(x=project(9000)), 'x', RATE, DAY) is None


def test_model_price_drop_is_reported_against_first_seen():
    store = {}
    update_project(store, 'x', project(10000), DAY - 20)
    update_project(store, 'x', project(8900), DAY)
    score, lines = evaluate_project(store, 'x', RATE, DAY)
    assert 'bajó 11%' in lines[1]


SCOTIA = '''VENTA DE INMUEBLES LIMA Y PROVINCIAS
No. # Exp Dirección Bien Departamento Provincia Distrito Valor Referencial
1 427 (50% ACC)PARCELA 2 IMPERIAL LIMA CAÑETE IMPERIAL 268,040.50 41237 m2 NO REALENGO P03081110 0 X COMERCIAL TERRENO AGRARIO NO INSCRITO
2 5679 LT 21 MZ M1 URB.CASUARINAS SUR LIMA LIMA SANTIAGO DE SURCO 438,300.00 1280 m2 NO REALENGO 1 X VIVIENDA TERRENO URBANO INSCRITO
3 5556 CALLE 7 IQUITOS LORETO MAYNAS IQUITOS 4,961.25 132.3 m2 NO REALENGO 18202 S/N X VIVIENDA CASA HABITACION INSCRITO
4 5683 - C CALLE B PARCELA 19 URB. SANTA GENOVEVA LIMA LIMA LURIN 1,218,200.00 1.74 Ha REALENGO X VIVIENDA TERRENO URBANO INSCRITO
'''


def test_scotia_rows_parse_value_area_region_and_registry():
    rows = scotia_text_rows(SCOTIA, minimum=1)
    assert set(rows) == {'427', '5679', '5556', '5683-C'}
    assert rows['5679'] == {'valor': 438300.0, 'area': '1280 m2', 'lima': True, 'ciudad': 'lima', 'inscrito': True,
                            'texto': 'LT 21 MZ M1 URB.CASUARINAS SUR LIMA LIMA SANTIAGO DE SURCO', 'clase': 'VIVIENDA TERRENO URBANO'}
    assert rows['427']['inscrito'] is False and rows['5556']['lima'] is False


def test_scotia_first_read_only_stores_then_reports_new_and_drops(monkeypatch):
    lists = [scotia_text_rows(SCOTIA, minimum=1)]
    monkeypatch.setattr(inmuebles, 'scotia_rows', lambda raw: lists[-1])
    monkeypatch.setattr(inmuebles, 'scan_nexo', lambda *a, **k: ([], []))
    monkeypatch.setattr(inmuebles.infocasas, 'scan_listings', lambda *a, **k: ([], 0, None))

    class Client:
        def __init__(self, **kw): pass
        def get_bytes(self, url): return b'%PDF'

    state = CatalogState()
    deals, reports = scan_inmuebles(state, DAY * 86400, Client)
    assert not deals and reports == [('Infocasas/avisos recientes', 0, None), ('Scotiabank/adjudicados', 4, None)]
    later = scotia_text_rows(SCOTIA.replace('438,300.00', '380,000.00'), minimum=1)
    later['9999'] = dict(later['5679'], valor=90000.0)
    lists.append(later)
    deals, _ = scan_inmuebles(state, (DAY + 1) * 86400, Client)
    assert not deals  # todavía no pasa una semana
    deals, _ = scan_inmuebles(state, (DAY + 8) * 86400, Client)
    texts = sorted(d.condition for d in deals)
    assert len(deals) == 2 and any('bajó 13%' in t for t in texts) and any('nuevo en la lista' in t for t in texts)
    assert all('referencial' in t for t in texts)


def test_district_filter_accepts_short_names_and_accents(monkeypatch):
    from monitor.inmuebles import wanted_districts, in_districts
    monkeypatch.setenv('INMUEBLES_DISTRITOS', 'Surco, Jesús María')
    wanted = wanted_districts()
    assert in_districts('Santiago De Surco', wanted) and in_districts('JESUS MARIA', wanted)
    assert not in_districts('Miraflores', wanted)
    monkeypatch.setenv('INMUEBLES_DISTRITOS', '')
    assert in_districts('Miraflores', wanted_districts())


def test_bad_text_uses_whole_words():
    from monitor.inmuebles import bad_text
    assert bad_text('venta de aires en Lince') and bad_text('inmueble OCUPADO por terceros')
    assert not bad_text('Urb. Buenos Aires, San Martín de Porres') and not bad_text('Av. Los Desocupados 123')

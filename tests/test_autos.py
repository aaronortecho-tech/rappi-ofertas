from pathlib import Path

from monitor.autos import parse_ad, sitemap_ads, evaluate, market, new_car_market, update_record, scan_autos
from monitor.catalogs import CatalogState
from monitor.http import Blocked

FIX = Path(__file__).parent / 'fixtures'
URL = 'https://neoauto.com/auto/usado/kia-sorento-2022-1885383'
DAY = 20700
RATE = 3.5


def page():
    return (FIX / 'neoauto_aviso.html').read_text(encoding='utf-8')


def car(price, year=2022, km=None, kind='usado', version='', seller='particular', shop='', flags=(), pub='', prices=None, first=DAY):
    km = (2026 - year) * 15000 if km is None else km
    return {'u': URL, 't': kind, 'm': 'kia', 'mo': 'sorento', 'v': version, 'a': year, 'km': km, 'mon': 'USD',
            'vend': seller, 'tienda': shop, 'dist': 'Surco', 'pub': pub, 'flags': list(flags),
            'nombre': f'Kia Sorento {year}', 'p': [[DAY, p] for p in (prices or [price])], 'f': first, 'r': DAY, 'x': DAY}


def fleet(**extra):
    """Ocho comparables por año: 2022 a US$ 20.000, 2021 a 17.000, 2020 a 15.000, 2019 a 13.000."""
    ads = {}
    for year, price in ((2022, 20000), (2021, 17000), (2020, 15000), (2019, 13000)):
        for n in range(8):
            ads[f'{year}{n}'] = car(price + n * 10 - 35, year)
    ads.update(extra)
    return ads


def judge(ads, ad_id):
    return evaluate(ads, ad_id, market(ads, RATE, DAY), new_car_market(ads, RATE, DAY), RATE, DAY, 2026)


def test_real_ad_page_reads_structured_data_without_personal_names():
    ad_id, record = parse_ad(page(), URL)
    assert ad_id == '1885383' and record['precio'] == 29000 and record['mon'] == 'USD'
    assert (record['m'], record['mo'], record['a'], record['km']) == ('kia', 'sorento', 2022, 64000)
    assert record['vend'] == 'particular' and record['tienda'] == '' and 'prueba' not in str(record).lower()
    assert record['pub'].startswith('Publicado')


def test_sitemap_skips_non_ad_urls_and_has_no_query_strings():
    ads = sitemap_ads((FIX / 'neoauto_sitemap.xml').read_text(encoding='utf-8'))
    assert len(ads) == 3 and all('?' not in u for u in ads.values())


def test_no_opinion_without_comparables():
    assert judge({'x': car(15000)}, 'x') is None


def test_free_year_needs_score_and_two_years_is_exceptional():
    ads = fleet(one=car(16900, pub='Publicado hace más de un mes'), two=car(14800, pub='Publicado hace más de un mes'))
    assert judge(ads, 'one') is None            # un año gratis de un particular no llega a 70 puntos
    score, lines = judge(ads, 'two')
    assert score >= 70 and 'cuesta como uno 2020 🚨' in lines[1]


def test_cheaper_than_three_years_back_or_under_55_percent_is_suspicious():
    assert judge(fleet(x=car(12000)), 'x') is None
    assert judge(fleet(x=car(10500)), 'x') is None


def test_red_flags_and_odd_mileage_block_the_alert():
    assert judge(fleet(x=car(14800, flags=['chocado'])), 'x') is None
    assert judge(fleet(x=car(14800, km=2000)), 'x') is None
    assert judge(fleet(x=car(14800, km=None) | {'km': None}), 'x') is None


def test_price_drop_on_old_listing_alerts_without_comparables():
    ads = {'x': car(18000, prices=[20000, 18000], pub='Publicado hace más de un mes')}
    score, lines = judge(ads, 'x')
    assert 'bajó 10%' in lines[1] and 'antes US$ 20,000' in lines[1]
    assert judge({'x': car(18000, prices=[20000, 18000], pub='Publicado hace 2 días')}, 'x') is None


def test_dealer_selling_everything_cheap_is_not_a_discount():
    shop = {f's{n}': car(15500, seller='empresa', shop='Autos X') for n in range(3)}
    ads = fleet(x=car(14800, seller='empresa', shop='Autos X', pub='Publicado hace más de un mes'), **shop)
    assert judge(ads, 'x') is None


def test_update_keeps_price_history_and_first_seen():
    ads = {}
    _, parsed = parse_ad(page(), URL)
    update_record(ads, '1', dict(parsed), DAY - 10)
    update_record(ads, '1', dict(parsed, precio=26000.0), DAY)
    assert ads['1']['p'] == [[DAY - 10, 29000.0], [DAY, 26000.0]] and ads['1']['f'] == DAY - 10


def test_scan_reads_new_ads_first_and_stops_on_block():
    sitemap = (FIX / 'neoauto_sitemap.xml').read_text(encoding='utf-8')
    big = sitemap.replace('</urlset>', ''.join(f'<url><loc>https://neoauto.com/auto/usado/kia-rio-2020-{i}</loc></url>'
                                                 for i in range(100000, 100600)) + '</urlset>')
    calls = []

    class Client:
        user_agent = 'Mozilla/5.0'
        def __init__(self, **kw): pass
        def get(self, url):
            calls.append(url)
            if url.endswith('robots.txt'): return 'User-agent: *\nDisallow: /*?'
            if url.endswith('.xml'): return big
            if len([c for c in calls if '/auto/' in c]) > 2: raise Blocked('403')
            return page()

    state = CatalogState()
    deals, reports = scan_autos(state, DAY * 86400, Client)
    reads = [c for c in calls if '/auto/' in c]
    assert reads[0].endswith('1886234') and reports[0][2] == 'acceso bloqueado; no se insiste'
    assert len(reads) == 3 and not deals and all('?' not in c for c in calls)


def test_without_topic_the_slow_groups_only_collect(tmp_path, monkeypatch):
    from monitor.catalogs import run_group
    monkeypatch.delenv('NTFY_TOPIC_AUTOS', raising=False)
    path = tmp_path / 'autos.json'

    def scanner(state, now):
        state.datos['neoauto'] = {'avisos': {'1': car(15000)}}
        return [], [('Neoauto/avisos', 1, None)]

    assert run_group('autos', now=DAY * 86400, scanner=scanner, state_path=str(path)) == 0
    assert '"neoauto"' in path.read_text(encoding='utf-8')
    with __import__('pytest').raises(ValueError):
        run_group('hogar', now=DAY * 86400, scanner=scanner, state_path=str(tmp_path / 'h.json'))


def test_price_range_only_filters_alerts(monkeypatch):
    from monitor.autos import price_range
    monkeypatch.setenv('AUTOS_PRECIO_MIN', '10,000')
    monkeypatch.setenv('AUTOS_PRECIO_MAX', 'mucho')
    assert price_range() == (10000.0, float('inf'))


def test_scan_keeps_all_candidates_and_reserves_known_price_reads(monkeypatch):
    import monitor.autos as module
    from monitor.catalogs import deliver, Deal
    from monitor.config import Config
    monkeypatch.setenv('LECTURAS_AUTOS', '12')
    listed = {str(i): f'https://neoauto.com/auto/usado/kia-rio-2020-{i}' for i in range(100000, 100600)}
    monkeypatch.setattr(module, 'sitemap_ads', lambda html: listed)
    monkeypatch.setattr(module, 'parse_ad', lambda html, url: ('ignored', car(15000) | {'precio': 15000}))
    monkeypatch.setattr(module, 'evaluate', lambda *args: (80, ['Candidato']))
    calls = []
    class Client:
        user_agent = 'test'
        def __init__(self, **kw): pass
        def get(self, url):
            if '/auto/' in url: calls.append(url.rsplit('-', 1)[-1])
            return 'User-agent: *\nDisallow:'
    state = CatalogState()
    state.datos['neoauto'] = {'avisos': {str(i): car(15000) for i in range(100000, 100004)}}
    deals, reports = scan_autos(state, DAY * 86400, Client)
    assert len(calls) == 12 and set(str(i) for i in range(100000, 100004)) <= set(calls)
    assert len(deals) == 12
    for deal in deals[:3]: state.mark_seen(deal.key, DAY * 86400)
    class Sink:
        cfg = Config()
        def send(self, *args, **kwargs): return True
    sent, failed = deliver(deals, state, Sink(), DAY * 86400, 'autos')
    assert sent == 3 and not failed and len(state.seen) == 6


def test_medians_skip_damaged_cars_and_never_mix_version_with_model():
    # Ocho chocados baratos no deben bajar la mediana del modelo.
    ads = fleet(**{f'ch{i}': car(9000, flags=['chocado']) for i in range(8)})
    assert market(ads, RATE, DAY, 2026)[('kia', 'sorento', 2022)][1] == 8
    # Versión con medianas propias en 2022 y 2021: se compara todo por versión.
    top = {f'gt{y}{i}': car(p + i, year=y, version='gt') for y, p in ((2022, 30000), (2021, 26000)) for i in range(8)}
    ads = fleet(x=car(16900, version='gt', pub='Publicado hace más de un mes'), **top)
    # A US$ 16.900 un GT 2022 está muy por debajo del GT 2021 (26.000): más barato que tres años atrás
    # por versión no existe, pero bajo el 55 % de su propia mediana sí: sospechoso, no ganga.
    assert judge(ads, 'x') is None
    # Sin medianas de la versión el aviso usa el modelo completo (como antes).
    assert judge(fleet(x=car(14800, version='raro', pub='Publicado hace más de un mes')), 'x')

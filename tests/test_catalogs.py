import json
from datetime import date
from dataclasses import replace

import pytest

from conftest import FakeHttp, fixture_text
from monitor.catalogs import (CatalogState, Deal, DinersCards, DINERS_URL, deal_text,
                              deliver, diners_deal, exact_discount, retail_products,
                              run_group, scan_retail, scan_travel, validity)
from monitor.config import Config
from monitor.http import Blocked
from monitor.notify import Notifier

NOW = 1_789_689_600  # septiembre 2026


def html_products(products, count=None):
    data = {'props': {'pageProps': {'results': products, 'pagination': {
        'count': len(products) if count is None else count, 'perPage': 48}}}}
    return '<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>'


def product(regular='100', web='40', card=None):
    prices = [{'type': 'normalPrice', 'symbol': 'S/ ', 'price': [regular]},
              {'type': 'internetPrice', 'symbol': 'S/ ', 'price': [web]}]
    if card: prices.append({'type': 'cmrPrice', 'symbol': 'S/ ', 'price': [card]})
    return {'productId': '123', 'skuId': '124', 'displayName': 'Escritorio',
            'url': 'https://www.falabella.com.pe/falabella-pe/product/123/escritorio',
            'sellerName': 'Tercero', 'prices': prices, 'discountBadge': {'label': '-99%'}}


def test_real_retail_fixtures_parse():
    for source, filename in [('Falabella', 'retail_falabella.html'), ('Sodimac', 'retail_sodimac.html')]:
        deals, checked, _ = retail_products(fixture_text(filename), source, 'Muebles')
        assert checked == 3 and deals
        assert all(d.seller and d.regular > d.price > 0 for d in deals)


def test_retail_uses_prices_not_advertised_percentage_and_does_not_round_up():
    deals, _, _ = retail_products(html_products([product(web='40.01', card='35')]), 'Falabella', 'Hogar')
    assert [(d.pct, d.condition.startswith('Requiere')) for d in deals] == [(59, False), (65, True)]
    assert deals[0].seller == 'Tercero'


def test_retail_rejects_price_ranges_wrong_currency_and_external_links():
    p = product(); p['prices'][1]['price'] = ['20', '40']
    assert not retail_products(html_products([p]), 'Falabella', 'Hogar')[0]
    p = product(); p['prices'][1]['symbol'] = '$'
    assert not retail_products(html_products([p]), 'Falabella', 'Hogar')[0]
    p = product(); p['url'] = 'https://evil.example/product'
    assert not retail_products(html_products([p]), 'Falabella', 'Hogar')[0]


def test_broken_catalog_is_failure_but_confirmed_empty_is_ok():
    with pytest.raises(ValueError): retail_products('<html>Error 500</html>', 'Falabella', 'Hogar')
    assert retail_products(html_products([]), 'Falabella', 'Hogar')[1] == 0


class RetailHttp(FakeHttp):
    def __init__(self, *args, **kwargs):
        super().__init__(); self.blocked = None
    def get(self, url):
        self.calls.append(url)
        if 'page=2' in url: return html_products([product(web='30')], count=100)
        return html_products([product(web='40', card='25')], count=100)


def test_retail_rotates_pages_and_prefers_unconditional_deal():
    http = RetailHttp(); state = CatalogState()
    sources = [('Falabella', 'Muebles', 'https://www.falabella.com.pe/muebles')]
    deals, reports = scan_retail(state, NOW, http_factory=lambda **kw: http, sources=sources)
    assert not reports[0][2] and reports[0][1] == 2
    assert len(deals) == 1 and not deals[0].condition.startswith('Requiere')
    assert list(state.cursors.values()) == [3]
    assert len(http.calls) == 2 and 'page=2' in http.calls[1]


def test_blocked_shop_is_not_retried_for_other_categories():
    class Denied(RetailHttp):
        def get(self, url):
            self.calls.append(url); self.blocked = '403'; raise Blocked('403')
    http = Denied()
    _, reports = scan_retail(CatalogState(), NOW, http_factory=lambda **kw: http,
                            sources=[('Falabella', c, 'https://www.falabella.com.pe/' + c) for c in ['a', 'b']])
    assert len(http.calls) == 1 and all(r[2] for r in reports)


def test_price_history_is_observed_not_claimed_original_price(tmp_path):
    state = CatalogState()
    deal = Deal('Falabella', '1', 'Mesa', 'https://example.org', 60, 40, 100, 'Tercero', 'web')
    state.observe(deal, NOW)
    assert deal.previous_min is None
    path = tmp_path / 'memory.json'; state.save(path, NOW)
    state = CatalogState.load(path)
    cheap = replace(deal, price=30)
    state.observe(cheap, NOW + 86400)
    assert cheap.previous_min == 40
    assert 'referencia publicada' in deal_text(cheap)
    assert 'Mesa' not in path.read_text()


@pytest.mark.parametrize('text, expected', [('Hasta 55% de descuento', 0),
    ('Hasta un 70% de descuento y 12 cuotas', 0), ('50% de descuento con DINERS50', 50),
    ('Hasta 24 cuotas sin intereses', 0), ('Regalo de S/ 50 por compra', 0),
    ('49,9% de descuento', 49)])
def test_discount_does_not_confuse_maximum_or_financing(text, expected):
    assert exact_discount(text) == expected


def test_spanish_validity_ranges():
    assert validity('Válido del 01 al 12 de julio de 2026.') == (date(2026, 7, 1), date(2026, 7, 12))
    assert validity('Vigencia del 01 de setiembre al 31 de diciembre de 2026') == (date(2026, 9, 1), date(2026, 12, 31))
    assert validity('Válido del 31 al 32 de febrero de 2026') is None
    assert validity('Sujeto a disponibilidad') is None


def test_travel_excludes_expired_unknown_dates_and_other_origins():
    card = {'name': 'Hotel', 'url': DINERS_URL + '/test', 'text': '50% de descuento con DINERS50'}
    assert diners_deal(card, '<p>Condiciones Válido del 01 al 12 de julio de 2026.</p>', date(2026,9,17)) is None
    assert diners_deal(card, 'Sin fechas', date(2026,9,17)) is None
    detail = 'Condiciones Válido del 01 de septiembre al 31 de diciembre de 2026. Tarjetas Diners Club.'
    assert diners_deal(card, detail + ' Salidas desde Arequipa.', date(2026,9,17)) is None
    deal = diners_deal(card, detail + ' Salidas desde Lima.', date(2026,9,17))
    assert deal.pct == 50 and '2026-12-31' in deal.condition


def test_real_diners_cards_have_no_guaranteed_fifty_percent():
    html = fixture_text('diners_cards.html')
    parser = DinersCards(); parser.feed(html)
    assert len(parser.cards) == 12
    http = FakeHttp({DINERS_URL: html})
    deals, reports = scan_travel(CatalogState(), NOW, http_factory=lambda **kw: http)
    assert not deals and reports == [('Diners/viajes', 12, None)]
    assert http.calls == [DINERS_URL]


def test_topics_stay_separate_and_failed_delivery_is_not_marked(monkeypatch, tmp_path):
    monkeypatch.setenv('NTFY_TOPIC_HOGAR', 'test-hogar')
    monkeypatch.setenv('NTFY_TOPIC_VIAJES', 'test-viajes')
    deal = Deal('Falabella', '1', 'Mesa', 'https://example.org', 60, 40, 100, 'Tercero', 'web')
    for group in ['hogar', 'viajes']:
        cfg = Config(ntfy_topic='test-' + group)
        http = FakeHttp(); notifier = Notifier(cfg, http)
        path = tmp_path / (group + '.json')
        scanner = lambda state, now: ([deal], [('Prueba', 1, None)])
        assert run_group(group, now=NOW, scanner=scanner, notifier=notifier, state_path=path, test=True) == 0
        assert all(p['topic'] == 'test-' + group for _, p, _ in http.posts)
        assert len(http.posts) == 2
        http.posts.clear()
        run_group(group, now=NOW + 1800, scanner=scanner, notifier=notifier, state_path=path)
        assert not http.posts
    state = CatalogState(); http.post_status = 503
    sent, failed = deliver([deal], state, notifier, NOW, 'hogar')
    assert sent == 0 and failed and not state.seen


def test_notification_limit_does_not_mark_undelivered_items():
    cfg = Config(ntfy_topic='test-hogar'); http = FakeHttp(); notifier = Notifier(cfg,http)
    deals = [Deal('Falabella', str(i), f'Mesa {i}', 'https://example.org', 60, 40, 100, 'Tercero', 'web') for i in range(30)]
    state = CatalogState()
    sent, failed = deliver(deals, state, notifier, NOW, 'hogar')
    assert sent == 24 and len(state.seen) == 24 and len(http.posts) == 8 and not failed


def test_same_seller_sku_is_not_repeated_across_platforms():
    a = Deal('Falabella', '124', 'Mesa', 'https://example.org/a', 60, 40, 100, 'Sodimac', 'web')
    b = replace(a, source='Sodimac', url='https://example.org/b')
    assert a.key == b.key and a.history_key == b.history_key
    assert replace(b, seller='Otro').key != a.key


def test_categories_get_space_even_if_decor_has_higher_discounts():
    deals = [Deal('Falabella', str(i), 'Decoración', 'https://example.org', 90, 10, 100,
                  'Vendedor', 'web', 'Hogar') for i in range(30)]
    deals.append(Deal('Falabella','tech','Laptop','https://example.org',60,40,100,'Vendedor','web','Tecnología'))
    cfg=Config(ntfy_topic='test-hogar'); http=FakeHttp()
    deliver(deals,CatalogState(),Notifier(cfg,http),NOW,'hogar')
    assert 'Laptop' in http.posts[0][1]['message']


def test_dry_run_does_not_write_memory(tmp_path):
    path = tmp_path / 'memory.json'
    assert run_group('hogar', dry_run=True, state_path=path,
                     scanner=lambda s,n: ([], [('Prueba', 0, None)])) == 0
    assert not path.exists()

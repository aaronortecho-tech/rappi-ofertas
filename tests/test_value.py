from dataclasses import replace
import logging
import math

import pytest

from conftest import FakeHttp, seed_value
from monitor.catalogs import CatalogState, Deal, run_group
from monitor.config import Config
from monitor.main import run, parse_args
from monitor.models import Alert, Offer, ScanResult
from monitor.notify import Notifier, offer_line
from monitor.parsers import parse_restaurant_page, parse_restaurant_live
from monitor.state import State
from monitor.value import (evidence, remember, day_at, filter_rappi, rappi_identity,
                           catalog_value, mark_value, set_market)

NOW = 1791167000
DAY = day_at(NOW)


def rows(price, day=DAY):
    return [[day-i, price] for i in range(1,8)]


def item(**changes):
    return replace(Deal('Falabella', 'sku1', 'Freidora Marca ABC123', 'https://example.org/item',
                        80, 249., 1245., 'Tienda A', 'Precio web', 'Electrodomésticos'), **changes)


def alert(**changes):
    return Alert('tienda', 'store1', 'Tienda', 'https://example.org/store',
                 offers=[replace(Offer('p1', 'Producto 1 kg', 30., 150., 80), **changes)])


def test_inflated_list_price_does_not_create_savings():
    state = CatalogState(); deal = item(price=299.)
    state.history[deal.history_key] = rows(309., NOW//86400)
    assert catalog_value(deal, state, NOW)[0] is None
    state.history[deal.history_key] = rows(299., NOW//86400)
    assert catalog_value(deal, state, NOW)[0] is None


def test_historical_offer_passes_even_with_small_advertised_discount():
    state = CatalogState(); deal = item(pct=5, regular=260.)
    state.history[deal.history_key] = rows(329., NOW//86400)
    good, reason = catalog_value(deal, state, NOW)
    assert not reason and good.value_savings == 80 and good.value_pct == 24


def test_single_spike_and_current_day_do_not_inflate_reference():
    history = rows(299.) + [[DAY-1, 9999.], [DAY, 99999.]]
    assert evidence(history, 299., DAY, 15, 50)[0] is None


@pytest.mark.parametrize('price', [None, 0, -1, math.nan, math.inf, True])
def test_invalid_prices_never_pass(price):
    assert evidence(rows(100.), price, DAY, 20, 10)[0] is None


def test_thresholds_do_not_round_up_and_require_both():
    assert evidence(rows(100.), 80.01, DAY, 20, 10)[0] is None
    assert evidence(rows(20.), 10.01, DAY, 20, 10)[0] is None
    assert evidence(rows(100.), 80., DAY, 20, 10)[0][1:3] == (20., 20)


def test_seven_distinct_recent_days_required():
    assert evidence([[DAY-1,100.]]*20, 50., DAY, 20, 10)[0] is None
    assert evidence([[DAY-i,100.] for i in range(15,22)], 50., DAY, 20, 10)[0] is None


def test_history_persists_and_keeps_daily_minimum(tmp_path):
    state = State(); remember(state.price_history, 'k', 100., DAY)
    remember(state.price_history, 'k', 999., DAY)
    path = tmp_path/'state.json'; state.save(path, NOW)
    loaded = State.load(path)
    assert loaded.price_history['k'] == [[DAY,100.]]
    remember(loaded.price_history, 'k', 50., DAY)
    assert loaded.changed()


def test_announcements_and_inferred_prices_are_never_proof():
    a = alert(price_verified=False); a.announced_text='Hasta 80%'
    state=State(); state.price_history[rappi_identity(a,a.offers[0])] = rows(100.)
    assert filter_rappi([a],state,NOW)[0] == []
    assert not filter_rappi([Alert('tienda','x','X','u',store_wide_text='80%')],state,NOW)[0]


def test_rappi_savings_and_conditions_are_explicit():
    a=alert(pro_only=True); state=State()
    state.price_history[rappi_identity(a,a.offers[0])]=rows(50.)
    good,_=filter_rappi([a],state,NOW)
    offer=good[0].offers[0]
    assert offer.pct==40 and offer.savings==20.
    text=offer_line(offer)
    assert 'antes de cargos' in text and 'Envío/cargos por confirmar' in text and 'Rappi Pro' in text
    assert '150' not in text


def test_variant_store_and_membership_histories_do_not_mix():
    a=alert(); state=State()
    state.price_history[rappi_identity(a,a.offers[0])]=rows(100.)
    for other in [replace(a,store_id='other'),alert(name='Producto 500 g'),alert(pro_only=True)]:
        assert filter_rappi([other],state,NOW)[0] == []


def test_market_comparison_requires_exact_model_and_independent_sellers():
    a=item(); b=item(source='Promart',identity='b',seller='B',price=329.)
    c=item(source='Oechsle',identity='c',seller='C',price=349.)
    state=CatalogState(); set_market(state,[a,b,c])
    good,_=catalog_value(a,state,NOW)
    assert good.value_basis=='mercado' and good.value_reference==329.
    set_market(state,[a,b,replace(c,seller='B')])
    assert catalog_value(a,state,NOW)[0] is None
    set_market(state,[a,b,replace(c,name='Freidora Marca ABC124')])
    assert catalog_value(a,state,NOW)[0] is None


def test_cheaper_competitor_vetoes_historical_bargain():
    a=item(); state=CatalogState(); seed_value(state,[a],NOW)
    set_market(state,[a,item(seller='B',identity='b',price=229.)])
    assert catalog_value(a,state,NOW)[0] is None


def test_card_price_is_withheld_until_eligibility_known():
    a=item(condition='Requiere tarjeta CMR'); state=CatalogState(); seed_value(state,[a],NOW)
    assert catalog_value(a,state,NOW)[1]=='condición de acceso sin confirmar'


def test_same_price_does_not_realert_after_badge_change_or_seller_change():
    a=item(); state=CatalogState(); seed_value(state,[a],NOW)
    good,_=catalog_value(a,state,NOW); mark_value(state,good.value_id,good.price,NOW)
    b=replace(a,pct=90,regular=9999.,seller='B');seed_value(state,[b],NOW)
    assert catalog_value(b,state,NOW+8*86400)[0] is None
    seed_value(state,[b],NOW+8*86400)
    assert catalog_value(b,state,NOW+8*86400)[1]=='ya avisada sin mejora'
    assert catalog_value(replace(b,price=230.),state,NOW+8*86400)[0]


def test_rappi_run_limits_five_and_does_not_mark_failed_delivery(cfg, tmp_path, monkeypatch):
    import monitor.main as module
    offers=[Offer(str(i),f'Producto {i} 1kg',30.,150.,80) for i in range(8)]
    a=replace(alert(),offers=offers)
    state=State(); state.mark_started(NOW-1)
    for o in offers: state.price_history[rappi_identity(a,o)] = rows(100.)
    state.save(cfg.state_path,NOW-1)
    cfg.check_restaurants=False; cfg.check_stores=True
    monkeypatch.setattr(module,'scan_stores',lambda *args: ScanResult('tiendas',alerts=[a],checked=1))
    http=FakeHttp(); notifier=Notifier(cfg,http)
    assert run(cfg,parse_args([]),logging.getLogger('test'),now=NOW,http=http,notifier=notifier)==0
    saved=State.load(cfg.state_path)
    assert len(saved.value_notices)==5 and sum(p['message'].count('🛒') for _,p,_ in http.posts)==5
    http.posts.clear(); http.post_status=503
    assert run(cfg,parse_args([]),logging.getLogger('test'),now=NOW+1800,http=http,notifier=notifier)==1
    assert len(State.load(cfg.state_path).value_notices)==5


def test_old_queue_cannot_bypass_gate(tmp_path):
    from dataclasses import asdict
    state=CatalogState(); a=item()
    state.datos['cola_hogar']={a.history_key:{'oferta':asdict(a),'visto':NOW-10}}
    path=tmp_path/'home.json';state.save(path,NOW-1)
    class Phone:
        cfg=Config()
        def send(self,*args,**kwargs): raise AssertionError('Unverified offer sent')
    assert run_group('hogar',now=NOW,scanner=lambda s,n:([],[]),notifier=Phone(),state_path=path)==0
    assert not CatalogState.load(path).datos['cola_hogar']

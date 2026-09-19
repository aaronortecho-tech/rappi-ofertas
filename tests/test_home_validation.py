from dataclasses import asdict, replace
from urllib.parse import urlencode
import json
import pytest
from conftest import fixture_text
from monitor.catalogs import CatalogState, Deal, RETAIL_SOURCES, hold_home, quality, home_urgent, retail_products, run_group
from monitor.home_validation import validate, record_metrics, allowed_url
from monitor.http import Blocked
from monitor.config import Config

NOW = 1789689600
BASE = next(url for source,category,url in RETAIL_SOURCES if source == 'Falabella' and category == 'Muebles')
URL = BASE + '?' + urlencode({'f.range.derived.variant.discount': '60% dcto y más'})
RAW = fixture_text('retail_falabella.html')


def sample():
    deal = next(d for d in retail_products(RAW, 'Falabella', 'Muebles')[0] if d.pct >= 60)
    return replace(deal, check_url=URL)


def memory(deals):
    state = CatalogState()
    state.datos['cola_hogar'] = {d.history_key: {'oferta': asdict(d), 'visto': NOW-3600} for d in deals}
    return state


class Client:
    user_agent = 'test'
    calls = []
    raw = RAW
    robots = 'User-agent: *\nDisallow:'
    block = False
    def __init__(self, **kw): self.requests_made = 0
    def get(self, url):
        self.requests_made += 1
        type(self).calls.append(url)
        if url.endswith('robots.txt'): return type(self).robots
        if type(self).block: raise Blocked('403')
        return type(self).raw


@pytest.fixture(autouse=True)
def reset_client():
    Client.calls=[]; Client.raw=RAW; Client.robots='User-agent: *\nDisallow:'; Client.block=False


def test_current_observation_needs_no_extra_request():
    deal=sample(); state=memory([deal])
    good, stats=validate([deal],state,NOW,[deal],[],Client)
    assert len(good)==1 and stats['confirmadas_ronda']==1 and not Client.calls
    assert 'Precio observado en esta ronda' in good[0].note


def test_stale_listing_is_rechecked_once_per_page():
    deal=sample(); other=replace(deal,identity='absent')
    state=memory([deal,other])
    good, stats=validate([deal,other],state,NOW,[],[],Client)
    assert len(good)==1 and stats['revalidadas']==1 and stats['no_confirmadas']==1
    assert len(Client.calls)==2 and state.datos['cola_hogar'][deal.history_key]['visto']==NOW


def test_changed_price_replaces_queue_but_never_sends_stale_price():
    actual=sample(); old=replace(actual,price=actual.price+1)
    state=memory([old])
    good, stats=validate([old],state,NOW,[],[],Client)
    assert not good and stats['cambiadas']==1
    assert state.datos['cola_hogar'][old.history_key]['oferta']['price']==actual.price


def test_missing_or_unavailable_is_not_notified_or_marked_seen():
    deal=sample(); state=memory([deal]); Client.raw='<script id="__NEXT_DATA__">'+json.dumps({'props':{'pageProps':{'results':[], 'pagination':{'count':0}}}})+'</script>'
    good,stats=validate([deal],state,NOW,[],[],Client)
    assert not good and stats['no_confirmadas']==1 and not state.seen
    assert state.datos['cola_hogar'][deal.history_key]['visto']==NOW-3600


@pytest.mark.parametrize('blocked_before', [False,True])
def test_no_retry_after_block_in_scan_or_revalidation(blocked_before):
    deal=sample(); other=replace(deal,identity='absent',check_url=URL+'&page=2')
    Client.block=True
    reports=[('Falabella/Muebles',0,'acceso bloqueado')] if blocked_before else []
    good,stats=validate([deal,other],memory([deal,other]),NOW,[],reports,Client)
    assert not good and len(Client.calls)==(0 if blocked_before else 2)


def test_robots_denial_and_unknown_urls_never_fetch_catalog():
    deal=sample();Client.robots='User-agent: *\nDisallow: /'
    good,stats=validate([deal],memory([deal]),NOW,[],[],Client)
    assert not good and len(Client.calls)==1
    assert not allowed_url(replace(deal,check_url='https://example.org/private'))
    assert not allowed_url(replace(deal,check_url=URL+'&token=secret'))


def test_unknown_legacy_offer_waits_without_advancing_digest(tmp_path):
    deal=replace(sample(),check_url=''); state=memory([deal]); path=tmp_path/'state.json';state.save(path,NOW-10)
    class Phone:
        cfg=Config()
        def send(self,*a,**k): raise AssertionError('No debe enviar una oferta sin confirmar')
    assert run_group('hogar',now=NOW,scanner=lambda s,n:([],[]),notifier=Phone(),state_path=path)==0
    saved=CatalogState.load(path)
    assert not saved.datos.get('ultimo_resumen_hogar')
    assert saved.datos['ultima_ronda_hogar']['no_confirmadas']==1


def test_historial_beats_inflated_reference_and_cold_80_is_not_urgent():
    cold=replace(sample(),pct=90,regular=999999)
    backed=replace(sample(),identity='backed',pct=80)
    state=CatalogState();day=NOW//86400
    state.history[backed.history_key]=[[day-n,backed.price*2] for n in (3,2,1)]
    cold.rank,_,_=quality(state,cold,NOW);backed.rank,_,_=quality(state,backed,NOW)
    assert backed.rank>cold.rank and home_urgent(backed) and not home_urgent(cold)
    state.datos['ultimo_resumen_hogar']=NOW
    due,_,_=hold_home(state,[cold,backed],NOW)
    assert [d.identity for d in due]==['backed']


def test_category_survives_global_queue_limit(monkeypatch):
    import monitor.catalogs as mod
    monkeypatch.setattr(mod,'QUEUE_MAX',4)
    deals=[replace(sample(),identity=str(i),pct=90,category='Hogar') for i in range(20)]
    deals.append(replace(sample(),identity='tech',pct=60,category='Tecnología'))
    state=CatalogState(); hold_home(state,deals,NOW)
    queue=state.datos['cola_hogar']
    assert len(queue)==4 and any(v['oferta']['identity']=='tech' for v in queue.values())


def test_metrics_retention_and_counters():
    state=CatalogState();state.datos['metricas_hogar']={str(NOW//86400-40):{'rondas':1}}
    record_metrics(state,NOW,{'no_confirmadas':2,'revalidadas':3},2,False)
    record_metrics(state,NOW+1,{'no_confirmadas':1},0,True)
    daily=state.datos['metricas_hogar'];assert len(daily)==1
    row=next(iter(daily.values()))
    assert row['rondas']==2 and row['no_confirmadas']==3 and row['enviadas']==2 and row['rondas_con_fallo_envio']==1


def test_page_budget_is_bounded():
    base=sample(); deals=[replace(base,identity=str(i),check_url=URL+f'&page={i+1}') for i in range(24)]
    good,stats=validate(deals,memory(deals),NOW,[],[],Client)
    assert stats['paginas_releidas']==8 and len(Client.calls)==9 and not good

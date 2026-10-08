from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import pytest

from monitor.config import Config
from monitor.factoring import (public_announcements, collect_public, evaluate, returns,
                               deliver, run, alert_text)
from monitor.http import Blocked
from monitor.state import State

NOW=int(datetime(2026,10,8,12,tzinfo=timezone.utc).timestamp())
ISO=datetime.fromtimestamp(NOW,timezone.utc).isoformat()
PROFILE={'capital_pen':10000,'currency':'PEN','max_days':90}


def complete():
    review={'reviewed':True,'observed_at':ISO,'available':True,'currency':'PEN',
        'url':'https://www.prestamype.com/app/inversionista/oportunidades',
        'opportunity_id':'synthetic-op-1','invoice_id':'synthetic-invoice-1',
        'payer_id':'synthetic-payer-1','payer':'EMPRESA FICTICIA PARA PRUEBAS',
        'group_id':'synthetic-group-1','sector':'test-sector','evidence_ref':'synthetic-evidence',
        'rate_type':'effective_annual','day_basis':360,'annual_pct':15,'grade':'A',
        'protected':False,'checks':{'checked_at':ISO,**{k:True for k in
          ('invoice_accepted','cavali_registered','no_dispute','no_related_parties',
           'credit_current','financials_reviewed','no_legal_red_flags','costs_confirmed')}},
        'history':{'complete_matured_cohort':True,'as_of':ISO,'window_days':365,'matured':100,
            'paid_on_time':98,'paid_late':2,'unpaid':0,'written_off':0,'currently_overdue':0,'p95_delay_days':2},
        'available_pen':5000,'minimum_pen':100,'funding_date':'2026-10-08','due_date':'2026-12-07',
        'fee_pct':10,'fee_vat_pct':18,'withholding_pct':5,'withholding_base':'gross_interest',
        'fixed_cost_pen':0}
    portfolio={'complete':True,'observed_at':ISO,'cash_pen':10000,'positions':[]}
    benchmark={'currency':'PEN','net_effective_annual':True,'checked_at':ISO,
               'source_ref':'synthetic-bank-reference','max_lock_days':90,'annual_pct':5}
    return review,portfolio,benchmark


def judge(review=None,portfolio=None,benchmark=None,now=NOW):
    r,p,b=complete()
    return evaluate(r if review is None else review,PROFILE,p if portfolio is None else portfolio,
                    b if benchmark is None else benchmark,now)


def public_html(body,stamp=ISO,post=1):
    return (f'<div class="tgme_widget_message" data-post="oportunidadesfactoringprestamype/{post}">'
            f'<div class="tgme_widget_message_text js-message_text">{body}</div>'
            f'<time datetime="{stamp}">12:00</time></div>')


def announcement(**changes):
    fields=dict(payer='FICTICIA',currency='S/',rate='12.5',grade='A+',paid=100,overdue=0)
    fields.update(changes)
    return public_html('💰 {payer}<br>Monto: {currency}1,000.00<br>Tasa de retorno anual: {rate}%<br>'
                       'Riesgo: {grade}<br>Operaciones pagadas: {paid}<br>'
                       'Operaciones por pagar (vencidas): {overdue}'.format(**fields))


def test_public_data_not_promoted_to_verified_evidence():
    posts=public_announcements(announcement(),NOW)
    assert len(posts)==1 and posts[0]['grade']=='A+' and posts[0]['currency']=='PEN'
    assert posts[0]['paid_count']==100 and 'paid_on_time' not in posts[0]
    assert judge(posts[0])[0] is None


def test_public_expired_future_impossible_and_image_only_are_not_candidates():
    assert not public_announcements(announcement(),NOW+86401)
    assert not public_announcements(announcement(),NOW-1)
    assert not public_announcements(announcement(rate='3651934.74'),NOW)
    assert not public_announcements(public_html('<img src="card.png">'),NOW)
    with pytest.raises(ValueError): public_announcements('<html>login</html>',NOW)


def test_batch_announcements_count_activity_without_inventing_invoices():
    posts=public_announcements(public_html('📌 NUEVAS SUBASTAS POR ACTIVAR<br>'
        '✨ FICTICIA<br>Monto: 1000 PEN<br>Tasa Anualizada: 12%<br>'
        '✨ OTRA FICTICIA<br>Monto: 5000 USD<br>Tasa Anualizada: 10%'),NOW)
    assert len(posts)==1 and posts[0]['kind']=='batch_announcement'
    assert 'invoice_id' not in posts[0] and judge(posts[0])[0] is None


@pytest.mark.parametrize('robots', ['User-agent: *\nDisallow: /s/', 'not robots'])
def test_robot_denial_stops_before_channel(robots):
    calls=[]
    class Client:
        user_agent='test'
        def __init__(self,**kw): pass
        def get(self,url): calls.append(url); return robots
    with pytest.raises(ValueError): collect_public(NOW,Client)
    assert len(calls)==1


def test_missing_robots_file_is_not_block_and_no_login_is_used():
    calls=[]
    class Client:
        user_agent='test'
        def __init__(self,**kw): pass
        def get(self,url):
            calls.append(url)
            return None if url.endswith('/robots.txt') else announcement()
    assert len(collect_public(NOW,Client))==1 and len(calls)==2


def test_complete_review_net_and_delay_math():
    result,reason=judge()
    assert reason is None and result['ticket']==500
    expected=500*((1.15)**(60/360)-1)*.832
    assert result['net']==pytest.approx(expected)
    assert result['net_annual_pct']>result['stress_annual_pct']>5
    assert 'no es probabilidad futura' in alert_text(result)
    assert 'no garantizados' in alert_text(result)


@pytest.mark.parametrize('path,value', [
    ('grade','D'),('grade',None),('available',False),('currency','USD'),('reviewed',False),
    ('fee_pct',None),('fee_pct',float('nan')),('annual_pct',float('inf')),('annual_pct',True),
    ('annual_pct',3651934.74),('day_basis',None),('rate_type','monthly'),
    ('minimum_pen',1000),('due_date','2026-12-08'),('funding_date','2026-10-07'),
    ('observed_at','2026-10-08T11:29:59+00:00'),('observed_at','2026-10-08T12:00:01+00:00'),
    ('url','https://www.prestamype.com.evil.test/app/inversionista/'),('evidence_ref',''),
    ('withholding_base','unknown'),('protected',True),
    ('checks.invoice_accepted',False),('checks.financials_reviewed',False),
    ('checks.costs_confirmed',False),('checks.no_dispute',False),
    ('history.complete_matured_cohort',False),('history.currently_overdue',1),
    ('history.paid_on_time',90),('history.matured',99),('history.p95_delay_days',8),
    ('history.window_days',179),('history.written_off',1),('history.unpaid',1),
])
def test_missing_or_adverse_evidence_never_generates_alert(path,value):
    r,_,_=complete()
    keys=path.split('.')
    target=r if len(keys)==1 else r[keys[0]]
    target[keys[-1]]=value
    assert judge(r)[0] is None


def test_public_paid_count_cannot_fill_missing_cohort_and_small_sample_is_blocked():
    r,_,_=complete()
    r['history']={'paid_count':10000,'overdue_count':0}
    assert judge(r)[0] is None
    r,_,_=complete(); r['history'].update(matured=29,paid_on_time=29,paid_late=0)
    assert judge(r)[1]=='muestra insuficiente'


def position(**changes):
    p={'invoice_id':'other','payer_id':'other','group_id':'other','sector':'other','principal_pen':1000}
    p.update(changes); return p


def test_concentration_across_same_economic_group_and_existing_invoice():
    r,p,b=complete()
    p['positions']=[position(group_id=r['group_id'],principal_pen=950)]
    assert judge(portfolio=p)[0] is None
    p['positions']=[position(invoice_id=r['invoice_id'],principal_pen=100)]
    assert judge(portfolio=p)[1]=='factura ya en cartera'
    p['positions']=[position(sector=r['sector'],principal_pen=2200)]
    assert judge(portfolio=p)[0]['ticket']==300
    p['cash_pen']=90
    assert judge(portfolio=p)[0] is None


def test_reference_and_portfolio_need_current_evidence_and_meaningful_net_premium():
    r,p,b=complete()
    p['complete']=False
    assert judge(portfolio=p)[0] is None
    b['annual_pct']=15
    assert judge(benchmark=b)[1]=='rentabilidad neta insuficiente frente a referencia'
    del b['annual_pct']
    assert judge(benchmark=b)[0] is None


class Sink:
    cfg=Config()
    def __init__(self,ok=True): self.ok=ok; self.messages=[]
    def send(self,*args,**kwargs): self.messages.append((args,kwargs)); return self.ok


def test_delivery_failure_retry_daily_limit_and_stable_invoice_identity():
    result,_=judge(); state=State(); sink=Sink(False)
    assert deliver([result],state,sink,NOW)==(0,True) and not state.seen
    sink.ok=True
    assert deliver([result],state,sink,NOW)==(1,False)
    changed=dict(result,opportunity_id='new-auction',net_annual_pct=99)
    assert deliver([changed],state,sink,NOW+1)==(0,False)
    others=[dict(result,invoice_id=f'i-{i}',group_id=f'g-{i}') for i in range(4)]
    assert deliver(others,state,sink,NOW+2)==(1,False)
    assert len(state.seen)==2


def test_batch_alerts_do_not_jointly_exceed_sector_or_cash_room():
    first,_=judge()
    first.update(room_sector=750)
    second=dict(first,invoice_id='second',group_id='second')
    assert deliver([first,second],State(),Sink(),NOW)==(1,False)


def test_default_run_only_collects_public_data_and_never_sends(tmp_path):
    path=tmp_path/'state.json'; sink=Sink()
    assert run(now=NOW,state_path=path,profile=PROFILE,bundle={},notifier=sink,
               source=lambda now:public_announcements(announcement(),now))==0
    assert not sink.messages
    data=json.loads(path.read_text(encoding='utf-8'))
    assert data['store_list']['metrics']['status']=='sin fichas completas: alertas bloqueadas'
    assert 'FICTICIA' not in path.read_text() and 'capital_pen' not in path.read_text()


def test_private_review_not_persisted_and_dry_run_does_not_modify_state(tmp_path):
    r,p,b=complete(); path=tmp_path/'state.json'; sink=Sink()
    bundle={'reviews':[r],'portfolio':p,'benchmark':b}
    assert run(now=NOW,state_path=path,profile=PROFILE,bundle=bundle,notifier=sink,source=lambda n:[])==0
    text=path.read_text(encoding='utf-8')
    for secret in (r['payer'],r['payer_id'],r['evidence_ref'],'cash_pen','capital_pen'):
        assert secret not in text
    before=path.read_bytes()
    assert run(now=NOW+60,state_path=path,dry_run=True,profile=PROFILE,bundle={},source=lambda n:[])==0
    assert path.read_bytes()==before


def test_source_failure_is_visible_and_not_recorded_as_healthy(tmp_path):
    def blocked(now): raise Blocked('403')
    path=tmp_path/'state.json'
    assert run(now=NOW,state_path=path,profile=PROFILE,bundle={},source=blocked)==1
    state=json.loads(path.read_text())
    assert state['failures']['public_source']==1


@pytest.mark.parametrize('part', ['review','checks','history','portfolio','benchmark','position'])
@pytest.mark.parametrize('bad', [None, [], 'invalid'])
def test_malformed_private_records_fail_closed(part,bad):
    r,p,b=complete()
    if part=='review': r=bad
    elif part=='portfolio': p=bad
    elif part=='benchmark': b=bad
    elif part=='position': p['positions']=[bad]
    else: r[part]=bad
    assert evaluate(r,PROFILE,p,b,NOW)[0] is None

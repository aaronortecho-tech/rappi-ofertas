"""Read-only factoring watch. Public announcements NEVER qualify as investments.

Complete, explicitly reviewed records are supplied privately. No login, orders,
deposits, or assumed default probabilities. See FACTORING.md for the data contract.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, ROUND_DOWN
from html.parser import HTMLParser
import json
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .config import Config
from .http import HttpClient
from .notify import Notifier, LIMA, in_quiet_hours
from .state import State, offer_key

CHANNEL = 'oportunidadesfactoringprestamype'
PUBLIC_URL = f'https://t.me/s/{CHANNEL}'
PORTAL = 'https://www.prestamype.com/app/inversionista/oportunidades'
GRADES = {'A+': 0, 'A': 1, 'B': 2}


class PublicPosts(HTMLParser):
    """Read only message bodies and timestamps, excluding previews and scripts."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts = []
        self.current = None
        self.depth = 0
        self.text_depth = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            self.depth += 1
            post = attrs.get('data-post', '')
            if re.fullmatch(CHANNEL+r'/\d+', post):
                self.current = {'id': post.split('/')[-1], 'text': '', 'published_at': None}
                self.posts.append(self.current)
            if 'tgme_widget_message_text' in attrs.get('class', '').split() and self.current is not None:
                self.text_depth = self.depth
        if self.current is not None:
            if tag == 'time': self.current['published_at'] = attrs.get('datetime')
            if tag == 'br' and self.text_depth is not None: self.current['text'] += '\n'

    def handle_endtag(self, tag):
        if tag == 'div':
            if self.text_depth == self.depth: self.text_depth = None
            self.depth -= 1

    def handle_data(self, data):
        if self.current is not None and self.text_depth is not None:
            self.current['text'] += data


def stamp(raw):
    parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    if parsed.tzinfo is None: raise ValueError('timestamp without timezone')
    return parsed.timestamp()


def fresh(raw, now, hours):
    try: return 0 <= now - stamp(raw) <= hours*3600
    except (AttributeError, ValueError, TypeError): return False


def public_announcements(html, now):
    parser = PublicPosts(); parser.feed(html or '')
    if not parser.posts: raise ValueError('public channel format changed')
    result = []
    for post in parser.posts:
        body = post['text']
        if not fresh(post['published_at'], now, 24): continue
        # Current channel also groups many auctions in one promotional message.
        # Count the message as activity, never invent individual invoice IDs.
        if ('NUEVAS SUBASTAS POR ACTIVAR' in body or 'SUBASTAS DISPONIBLES EN PLATAFORMA' in body):
            result.append({'post_id':post['id'], 'kind':'batch_announcement',
                           'published_at':post['published_at'],
                           'url':f"https://t.me/{CHANNEL}/{post['id']}",
                           'status':'incomplete_public_information'})
            continue
        # Multi-auction announcements and images alone have no reliable identity.
        payer = re.search(r'💰\s*([^\n]+)', body)
        rate = re.search(r'Tasa de retorno anual:\s*([\d.,]+)\s*%', body, re.I)
        if not payer or not rate: continue
        try: annual = float(rate[1].replace(',', '.'))
        except ValueError: continue
        if not math.isfinite(annual) or not 0 < annual <= 40: continue
        grade = re.search(r'Riesgo:\s*([A-E]\+?)(?![\w+])', body)
        paid = re.search(r'Operaciones pagadas:\s*(\d+)', body)
        overdue = re.search(r'Operaciones por pagar\s*\(vencidas\):\s*(\d+)', body)
        currency = 'PEN' if re.search(r'Monto:\s*S/', body) else 'USD' if re.search(r'Monto:\s*\$', body) else None
        result.append({'post_id': post['id'], 'payer': payer[1].strip()[:160],
                       'annual_pct': annual, 'grade': grade[1] if grade else None,
                       'currency': currency, 'paid_count': int(paid[1]) if paid else None,
                       'overdue_count': int(overdue[1]) if overdue else None,
                       'published_at': post['published_at'],
                       'url': f"https://t.me/{CHANNEL}/{post['id']}",
                       'status': 'incomplete_public_information'})
    return result


def collect_public(now, http_factory=HttpClient):
    http = http_factory(delay=1.5, timeout=25, max_requests=3)
    robots = http.get('https://t.me/robots.txt')
    if robots is not None:  # HTTP 404 means no robots file, not a bypass of a denial.
        if 'user-agent:' not in robots.lower(): raise ValueError('unrecognized robots response')
        rules = RobotFileParser(); rules.parse(robots.splitlines())
        if not rules.can_fetch(http.user_agent, PUBLIC_URL): raise ValueError('robots disallows source')
    return public_announcements(http.get(PUBLIC_URL), now)


def number(obj, key, minimum=0, maximum=1e12):
    v = obj[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not minimum <= v <= maximum:
        raise ValueError(key)
    return float(v)


def count(obj, key):
    n = number(obj, key, 0, 10000000)
    if n != int(n): raise ValueError(key)
    return int(n)


def text_field(obj, key):
    v = obj[key]
    if not isinstance(v, str) or not v.strip() or len(v) > 240 or any(ord(c)<32 for c in v):
        raise ValueError(key)
    return v.strip()


def platform_url(raw):
    try:
        u = urlsplit(raw)
        return (u.scheme == 'https' and u.hostname == 'www.prestamype.com' and not u.username
                and not u.password and u.port in (None,443) and u.path.startswith('/app/inversionista/'))
    except (ValueError, TypeError): return False


def returns(principal, annual_pct, interest_days, locked_days, basis, fee_pct, vat_pct,
            withholding_pct, fixed_cost, delay_days):
    """Annual effective gross input; withholding is explicitly on gross interest.

    Reporting annualization always uses 365 days. No reinvestment or late interest
    is promised. Delay is a scenario, not a probability or a maximum legal delay.
    """
    gross = principal * math.expm1(math.log1p(annual_pct/100)*interest_days/basis)
    costs = gross*(fee_pct/100)*(1+vat_pct/100) + gross*withholding_pct/100 + fixed_cost
    net = gross-costs
    holding_return = net/principal
    annual = math.expm1(math.log1p(holding_return)*365/locked_days)*100
    stressed = math.expm1(math.log1p(holding_return)*365/(locked_days+delay_days))*100
    # Zero recovery and no delay: loss probability that erases all net profit.
    # A sensitivity threshold, NEVER an estimate of default probability.
    break_even = max(0, holding_return/(1+holding_return))*100
    return {'gross':gross, 'costs':costs, 'net':net, 'net_annual_pct':annual,
            'stress_annual_pct':stressed, 'zero_recovery_break_even_pct':break_even}


def evaluate(review, profile, portfolio, benchmark, now):
    """Fail closed. Input assertions come from a human review of original evidence."""
    reject = lambda reason: (None, reason)
    try:
        budget = number(profile, 'capital_pen', 100, 1e8)
        horizon = count(profile, 'max_days')
        if profile.get('currency') != 'PEN' or not 1 <= horizon <= 90: return reject('perfil no compatible')
        if review.get('reviewed') is not True or not fresh(review.get('observed_at'), now, .5):
            return reject('ficha no revisada o vencida')
        if review.get('available') is not True or review.get('currency') != 'PEN':
            return reject('disponibilidad o moneda no compatible')
        if not platform_url(review.get('url')): return reject('fuente de ficha no válida')
        for k in ('opportunity_id','invoice_id','payer_id','payer','group_id','sector','evidence_ref'):
            text_field(review,k)
        if review.get('rate_type') != 'effective_annual' or review.get('day_basis') not in (360,365):
            return reject('base de tasa sin confirmar')
        grade = review['grade']
        if grade not in GRADES: return reject('riesgo fuera del filtro')
        checks = review['checks']
        required = ('invoice_accepted','cavali_registered','no_dispute','no_related_parties',
                    'credit_current','financials_reviewed','no_legal_red_flags','costs_confirmed')
        if any(checks.get(k) is not True for k in required): return reject('verificación documental incompleta')
        if not fresh(checks.get('checked_at'),now,7*24): return reject('verificación documental vencida')
        # Promotional protection is never a substitute for debtor and invoice checks.
        if review.get('protected') is not False:
            if review.get('protected') is not True: return reject('protección no aclarada')
            protection = review['protection']
            for k in ('guarantor','conditions_ref'): text_field(protection,k)
            if (protection.get('solvency_reviewed') is not True or
                    not fresh(protection.get('reviewed_at'),now,7*24)):
                return reject('garantía sin verificar')
            number(protection,'coverage_pct',1,100)
            count(protection,'payout_delay_days')
        history = review['history']
        if history.get('complete_matured_cohort') is not True or not fresh(history.get('as_of'),now,24):
            return reject('historial incompleto o vencido')
        if count(history,'window_days') < 180: return reject('historial demasiado corto')
        matured, ontime, late, unpaid, lost = [count(history,k) for k in
            ('matured','paid_on_time','paid_late','unpaid','written_off')]
        if matured != ontime+late+unpaid+lost: return reject('historial inconsistente')
        if matured < 30: return reject('muestra insuficiente')
        if unpaid or lost or count(history,'currently_overdue'): return reject('mora o pérdidas observadas')
        punctuality = ontime/matured
        if punctuality < .95 or number(history,'p95_delay_days',0,3650)>7:
            return reject('puntualidad insuficiente')
        if portfolio.get('complete') is not True or not fresh(portfolio.get('observed_at'),now,24):
            return reject('cartera sin actualizar')
        positions = portfolio['positions']
        if not isinstance(positions,list): return reject('cartera inválida')
        payer_exposure = sector_exposure = invested = 0
        for p in positions:
            for k in ('invoice_id','payer_id','group_id','sector'): text_field(p,k)
            value = number(p,'principal_pen')
            invested += value
            if p['invoice_id']==review['invoice_id'] and value>0: return reject('factura ya en cartera')
            if p['payer_id']==review['payer_id'] or p['group_id']==review['group_id']: payer_exposure += value
            if p['sector']==review['sector']: sector_exposure += value
        available = number(review,'available_pen',.01)
        cash = number(portfolio,'cash_pen')
        ticket = min(budget*.05, budget*.10-payer_exposure, budget*.25-sector_exposure,
                     budget-invested,cash,available)
        ticket = float(Decimal(str(max(0,ticket))).quantize(Decimal('.01'),rounding=ROUND_DOWN))
        if ticket < number(review,'minimum_pen',.01): return reject('concentración o saldo insuficiente')
        today = datetime.fromtimestamp(now,LIMA).date()
        funding, due = date.fromisoformat(review['funding_date']), date.fromisoformat(review['due_date'])
        interest_days, locked_days = (due-funding).days, (due-today).days
        if funding < today or interest_days<=0 or locked_days<=0: return reject('fechas no válidas')
        delay = 30  # Conservative policy buffer; not an empirical loss model.
        if review['protected']: delay=max(delay,review['protection']['payout_delay_days'])
        if locked_days+delay>horizon: return reject('plazo más margen de atraso supera horizonte')
        if (benchmark.get('currency')!='PEN' or benchmark.get('net_effective_annual') is not True
                or not fresh(benchmark.get('checked_at'),now,7*24)):
            return reject('referencia neta sin verificar')
        text_field(benchmark,'source_ref')
        if count(benchmark,'max_lock_days')>horizon: return reject('referencia no comparable por plazo')
        base = number(benchmark,'annual_pct',0,30)
        fee, vat, tax = [number(review,k,0,100) for k in ('fee_pct','fee_vat_pct','withholding_pct')]
        if review.get('withholding_base')!='gross_interest': return reject('base tributaria sin confirmar')
        rate = number(review,'annual_pct',.01,40)
        fixed = number(review,'fixed_cost_pen',0,ticket*.5)
        result = returns(ticket,rate,interest_days,locked_days,review['day_basis'],fee,vat,tax,fixed,delay)
        if result['net_annual_pct']<base+3 or result['stress_annual_pct']<base:
            return reject('rentabilidad neta insuficiente frente a referencia')
        result.update(ticket=ticket,locked_days=locked_days,delay_days=delay,benchmark=base,
                      room_sector=budget*.25-sector_exposure,room_total=min(budget-invested,cash),
                      punctuality=punctuality,matured=matured,grade=grade,
                      opportunity_id=review['opportunity_id'],invoice_id=review['invoice_id'],
                      payer_id=review['payer_id'],payer=review['payer'],group_id=review['group_id'],
                      sector=review['sector'],url=review['url'],due_date=review['due_date'])
        return result, None
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return reject('datos faltantes o inválidos')


def alert_text(result):
    r=result
    return (f"Factoring · candidata con ficha revisada\n{r['payer']} · riesgo publicado {r['grade']}\n"
            f"Tope orientativo: S/ {r['ticket']:.2f} · vencimiento {r['due_date']}\n"
            f"Ganancia neta estimada: S/ {r['net']:.2f} · anualizada {r['net_annual_pct']:.2f}%\n"
            f"Con {r['delay_days']} días de atraso, sin interés adicional: {r['stress_annual_pct']:.2f}% anualizada\n"
            f"Pagos puntuales observados: {r['punctuality']:.1%} de {r['matured']} vencidos; no es probabilidad futura.\n"
            "Confirmar ficha antes de decidir. Capital y fecha de cobro no garantizados.\n"+r['url'])


def deliver(results, state, notifier, now):
    # Same invoice is suppressed even if the auction ID, rate or source post changes.
    day=datetime.fromtimestamp(now,LIMA).date()
    today_sent=sum(datetime.fromtimestamp(t,LIMA).date()==day for t in state.seen.values())
    remaining=max(0,2-today_sent)
    sent=0; failed=False; payers=set(); reserved=0; sectors=Counter()
    for result in sorted(results,key=lambda r:(GRADES[r['grade']],-r['stress_annual_pct'],
                                               -r['punctuality'],r['locked_days'])):
        key=offer_key('factoring-invoice-v1',result['invoice_id'])
        if key in state.seen or result['group_id'] in payers: continue
        if sent>=remaining: break
        if (reserved+result['ticket']>result['room_total'] or
                sectors[result['sector']]+result['ticket']>result['room_sector']): continue
        payers.add(result['group_id'])
        ok=notifier.send('📄 Factoring: candidata para revisar',alert_text(result),
                         priority=2 if in_quiet_hours(notifier.cfg.quiet_hours,now) else 3,
                         click=result['url'])
        if ok:
            state.mark_seen(key,now); sent+=1
            reserved+=result['ticket']; sectors[result['sector']]+=result['ticket']
        else: failed=True
    return sent,failed


def run(*,now=None,state_path='state/factoring.json',dry_run=False,source=collect_public,
        profile=None,bundle=None,notifier=None):
    now=time.time() if now is None else now
    state=State.load(state_path)
    metrics={'public_announcements':0,'reviewed_candidates':0,'eligible':0,'sent':0,'rejections':{}}
    errors=[]
    try:
        public=source(now)
        metrics['public_announcements']=len(public)
        metrics['public_incomplete']=len(public)
        state.record_result('public_source',True)
    except Exception as exc:
        errors.append('lectura pública incompleta: '+type(exc).__name__)
        state.record_result('public_source',False)
    profile=profile if profile is not None else json.loads(os.environ.get('FACTORING_PROFILE_JSON') or '{}')
    bundle=bundle if bundle is not None else json.loads(os.environ.get('FACTORING_REVIEWS_JSON') or '{}')
    if not isinstance(profile,dict) or not isinstance(bundle,dict): raise ValueError('invalid configuration')
    reviews=bundle.get('reviews',[])
    if not isinstance(reviews,list) or len(reviews)>100: raise ValueError('invalid review batch')
    eligible=[]; rejected=Counter()
    for review in reviews:
        result,reason=evaluate(review,profile,bundle.get('portfolio',{}),bundle.get('benchmark',{}),now)
        if result: eligible.append(result)
        else: rejected[reason]+=1
    metrics.update(reviewed_candidates=len(reviews),eligible=len(eligible),rejections=dict(rejected))
    metrics['status']='sin fichas completas: alertas bloqueadas' if not reviews else 'evaluación completada'
    if eligible:
        if notifier is None:
            cfg=Config.from_env(); cfg.ntfy_topic=os.environ.get('NTFY_TOPIC_FACTORING') or None
            if not cfg.ntfy_topic and not dry_run:
                errors.append('falta el canal de factoring')
            elif cfg.ntfy_topic and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',cfg.ntfy_topic):
                errors.append('canal de factoring inválido')
            else: notifier=Notifier(cfg,HttpClient(delay=1.5,max_requests=6),dry_run=dry_run)
        if notifier:
            sent,failed=deliver(eligible,state,notifier,now)
            metrics['sent']=sent
            if failed: errors.append('entrega fallida; no marcada como enviada')
    # Public state contains ONLY aggregates and hashed notification IDs, no profiles,
    # balances, portfolio positions, source documents, reviewed names or contract data.
    state.store_list={'last_scan':int(now),'metrics':metrics,'errors':errors}
    state.mark_started(now)
    state.seen={k:t for k,t in state.seen.items() if now-180*86400<=t<=now}
    if not dry_run: state.save(state_path,now)
    line=json.dumps(dict(metrics,errors=errors),ensure_ascii=False)
    print(line)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as f:
            f.write('### Factoring — modo estricto\n\n```json\n'+line+'\n```\n')
    return 1 if errors else 0


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sin-enviar',action='store_true')
    parser.add_argument('--fichas',type=Path,help='Paquete privado revisado; nunca subirlo al repositorio')
    args=parser.parse_args()
    try:
        bundle=json.loads(args.fichas.read_text(encoding='utf-8-sig')) if args.fichas else None
        return run(dry_run=args.sin_enviar,bundle=bundle)
    except (OSError,ValueError,TypeError):
        print('Configuración de factoring inválida; no se enviaron alertas.')
        return 1


if __name__=='__main__': raise SystemExit(main())

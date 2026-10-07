"""Comparable route observations; no cross-route price-per-kilometre alerts."""
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, ROUND_FLOOR
from statistics import median

from .notify import LIMA
from .state import offer_key
from .value import clean_rows, positive

PCT_MIN = 25
MIN_SAVING = {'PEN': 80, 'USD': 25}


def savings(price, reference, currency):
    if not positive(price) or not positive(reference) or currency not in MIN_SAVING:
        return None
    p, r = Decimal(str(price)), Decimal(str(reference))
    pct = (1-p/r)*100
    # Extremely low prices still require manual verification, not an automatic alert.
    if p < r*Decimal('0.2') or pct < PCT_MIN or r-p < MIN_SAVING[currency]: return None
    return int(pct.to_integral_value(rounding=ROUND_FLOOR))


def route_key(deal, now):
    c = deal.flight_context
    try:
        departure = date.fromisoformat(c['depart'][:10])
        lead = (departure-datetime.fromtimestamp(now,LIMA).date()).days
        if lead <= 0: return None
        back = date.fromisoformat(c['back'][:10]) if c.get('back') else None
        duration = (back-departure).days if back else 0
        if back and duration <= 0: return None
        if not all(c.get(k) for k in ('destination','airline','service','taxes')): return None
        if type(c.get('stops')) is not int or c['stops'] < 0: return None
    except (ValueError, KeyError, TypeError): return None
    lead_band = next(limit for limit in (14,45,90,3650) if lead <= limit) if lead<=3650 else 3650
    duration_band = next(limit for limit in (0,7,14,30,3650) if duration<=limit) if duration<=3650 else 3650
    return offer_key('route-v2', deal.source, 'LIM', c['destination'], deal.currency,
                     c['airline'], c['service'], c['taxes'], c['stops'],
                     c['depart'][:7], departure.weekday()>=5, lead_band, bool(back), duration_band)


def observe_route(state, deal, now):
    key = route_key(deal, now)
    if not key or not positive(deal.price): return None
    day = int(now//86400)
    groups = state.datos.setdefault('rutas_vuelos_v2', {})
    rows = groups.setdefault(key, {})
    prior, observed_days = {}, set()
    for identity, entry in rows.items():
        if identity == deal.history_key: continue
        history = {d:p for d,p in clean_rows(entry.get('prices',[]),day).items() if d<day}
        if not history or max(history)<day-7: continue
        # One value per departure date avoids treating repeated polls or multiple
        # flights on the same date as independent date alternatives.
        departure=entry['depart']
        prior.setdefault(departure,[]).append(median(history.values()))
        observed_days.update(history)
    previous=rows.get(deal.history_key, {})
    values=clean_rows(previous.get('prices',[]),day)
    values[day]=min(values.get(day,deal.price),deal.price)
    rows[deal.history_key]={'depart':deal.flight_context['depart'][:10], 'prices':sorted(values.items())}
    if len(prior)<5 or len(observed_days)<3: return None
    reference=median(min(values) for values in prior.values())
    pct=savings(deal.price,reference,deal.currency)
    if pct is None: return None
    return replace(deal,pct=pct,regular=reference,reference_kind='flight_route',
                   note=f'{len(prior)} fechas comparables · {len(observed_days)} días observados. '
                        'Misma ruta, aerolínea, moneda, tipo de viaje y condiciones publicadas; '
                        'mismo mes, grupo de anticipación y duración. Precio final por confirmar.')


def prune_routes(state, now, limit=10000):
    day=int(now//86400)
    groups=state.datos.get('rutas_vuelos_v2',{})
    flat=[]
    for group, entries in groups.items():
        for identity, entry in entries.items():
            values=clean_rows(entry.get('prices',[]),day)
            if values:
                flat.append((max(values),len(values),group,identity,
                             {'depart':entry['depart'],'prices':sorted(values.items())}))
    result={}
    for _,_,group,identity,entry in sorted(flat,key=lambda x:x[:4])[-limit:]:
        result.setdefault(group,{})[identity]=entry
    if groups: state.datos['rutas_vuelos_v2']=result

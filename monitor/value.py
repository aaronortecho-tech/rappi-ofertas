"""Evidence gate: posted discounts never count as proof of savings.

Only comparable observed prices enter the reference. One minimum per Lima day
prevents repeated polls or a short price spike from inflating the baseline.
"""
from dataclasses import replace
from decimal import Decimal, ROUND_FLOOR
import math
import re
from statistics import median

from .state import offer_key

WINDOW = 30
MIN_DAYS = 7
MAX_RESULTS = 5
HISTORY_LIMIT = 50000


def day_at(now):
    return int((now - 5 * 3600) // 86400)


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def clean_rows(rows, day):
    values = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        d, p = row
        if isinstance(d, int) and day - WINDOW <= d <= day and positive(p):
            values[d] = min(values.get(d, p), p)
    return values


def evidence(rows, price, day, pct_min, soles_min):
    if not positive(price):
        return None, 'precio no verificable'
    before = {d: p for d, p in clean_rows(rows, day).items() if d < day}
    if len(before) < MIN_DAYS or max(before) < day - 7:
        return None, 'historial insuficiente'
    reference = Decimal(str(median(before.values())))
    current = Decimal(str(price))
    savings = reference - current
    pct = savings * 100 / reference
    if pct < pct_min or savings < soles_min:
        return None, 'ahorro real insuficiente'
    return (float(reference), float(savings), int(pct.to_integral_value(rounding=ROUND_FLOOR)), len(before)), None


def remember(history, key, price, day):
    if not positive(price):
        return
    values = clean_rows(history.get(key, []), day)
    values[day] = min(values.get(day, price), price)
    history[key] = sorted(values.items())


def prune_history(history, day, limit=HISTORY_LIMIT):
    cleaned = {k: sorted(clean_rows(v, day).items()) for k, v in history.items()}
    cleaned = {k: v for k, v in cleaned.items() if v}
    # Keep repeat observations long enough to mature. A deterministic key tie-break
    # selects a stable discovery sample instead of evicting today's known products
    # whenever a new page is appended. Inactive rows lose priority after a week.
    def priority(item):
        key, rows = item
        return (rows[-1][0] >= day - 7, min(len(rows), MIN_DAYS), rows[-1][0], key)
    return dict(sorted(cleaned.items(), key=priority)[-limit:])


def rappi_identity(alert, offer):
    return offer_key('rappi-value-v1', alert.kind, alert.store_id, offer.product_id,
                     ' '.join(offer.name.casefold().split()), offer.pro_only)


def improved(state, identity, price, now):
    last = state.value_notices.get(identity)
    if not isinstance(last, dict) or not positive(last.get('price')):
        return True
    # Within 30 days, require a meaningful additional price drop, not a new badge.
    if now - last.get('time', 0) >= WINDOW * 86400:
        return True
    return price <= last['price'] * 0.97 and last['price'] - price >= 1


def mark_value(state, identity, price, now):
    state.value_notices[identity] = {'price': price, 'time': int(now)}


def filter_rappi(alerts, state, now):
    stats, accepted = {}, []
    day = day_at(now)
    for alert in alerts:
        offers = []
        for offer in alert.offers:
            key = rappi_identity(alert, offer)
            if (not offer.price_verified or not offer.available or alert.kind == 'cadena'
                    or not offer.product_id or offer.product_id == 'None' or not offer.name):
                reason, result = 'precio o local no verificable', None
            else:
                result, reason = evidence(state.price_history.get(key, []), offer.price, day, 20, 10)
                remember(state.price_history, key, offer.price, day)
            if result and not improved(state, key, offer.price, now):
                result, reason = None, 'ya avisada sin mejora'
            if result:
                reference, saving, pct, days = result
                offers.append(replace(offer, pct=pct, regular_price=reference,
                                      verified_days=days, savings=saving, value_id=key))
            else:
                stats[reason] = stats.get(reason, 0) + 1
        if alert.announced_text or alert.store_wide_text:
            stats['anuncio sin producto verificable'] = stats.get('anuncio sin producto verificable', 0) + 1
        if offers:
            accepted.append(replace(alert, offers=offers, announced_text='', announced_pct=0,
                                    store_wide_text='', store_wide_pct=0))
    return accepted, stats


def catalog_value(deal, state, now):
    # Legacy home history contains actual PEN SKU/seller/condition observations.
    # It uses UTC dates; preserve its day convention when reading that history.
    if deal.currency != 'PEN' or not deal.identity or deal.identity == 'None':
        return None, 'identidad no verificable'
    if deal.condition.startswith('Requiere'):
        return None, 'condición de acceso sin confirmar'
    food = deal.source in ('Tambo', 'Makro')
    pct_min, cash_min = (20, 10) if food else (15, 50)
    result, reason = evidence(state.history.get(deal.history_key, []), deal.price,
                              int(now // 86400), pct_min, cash_min)
    basis = 'historial'
    peers = [] if food else getattr(state, 'value_market', {}).get(market_key(deal), [])
    peers = [p for p in peers if p.seller.casefold() != deal.seller.casefold()
             and p.history_key != deal.history_key]
    sellers = {p.seller.casefold() for p in peers if p.seller not in ('', 'No informado')}
    # A cheaper observed equivalent vetoes the historical "bargain". To replace
    # history entirely, require two other independent sellers with the exact title/model.
    market = min((p.price for p in peers if positive(p.price)), default=None)
    if market is not None and (result or len(sellers) >= 2):
        if not result or market < result[0]: basis = 'mercado'
        reference = min(result[0], market) if result else market
        days = result[3] if result else 0
        checked, reason = evidence([[int(now // 86400)-d, reference] for d in range(1, 8)],
                                   deal.price, int(now // 86400), pct_min, cash_min)
        result = (*checked[:3], days) if checked else None
    if not result:
        return None, reason
    from .catalogs import home_notice_key
    identity = offer_key('home-value-v1', home_notice_key(replace(deal, price=0)))
    if not improved(state, identity, deal.price, now):
        return None, 'ya avisada sin mejora'
    reference, savings, pct, days = result
    return replace(deal, value_reference=reference, value_savings=savings, value_pct=pct,
                   value_days=days, value_id=identity, confidence='historical',
                   value_basis=basis,
                   rank=pct + math.log1p(savings)), None


def filter_catalog(deals, state, now):
    accepted, stats = [], {}
    for deal in deals:
        verified, reason = catalog_value(deal, state, now)
        if verified:
            accepted.append(verified)
        else:
            stats[reason] = stats.get(reason, 0) + 1
    return accepted, stats


def market_key(deal):
    name = ' '.join(deal.name.casefold().split())
    # Never infer equivalence from a generic name or a price alone.
    if len(name.split()) < 3 or not re.search(r'\b[a-z][a-z0-9-]{3,}\d[a-z0-9-]*\b', name):
        return None
    return (name, deal.currency, deal.category, deal.condition)


def set_market(state, deals):
    state.value_market = {}
    for deal in deals:
        key = market_key(deal)
        if key and positive(deal.price):
            state.value_market.setdefault(key, []).append(deal)

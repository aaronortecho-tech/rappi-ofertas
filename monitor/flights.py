"""Tarifas publicadas desde Lima; nunca consulta ni automatiza reservas."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
import json
import re
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .http import HttpClient, Blocked
from .parsers import extract_next_data
from .state import offer_key
from .notify import LIMA

JET_URL = 'https://www.jetsmart.com/pe/es/'
SKY_URL = 'https://www.skyairline.com/flights/es-pe/ofertas-descuentos'


def amount(value):
    if isinstance(value, bool): return None
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0: return None
        return float(number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError): return None


def future_day(value, today):
    try: return date.fromisoformat(str(value)[:10]) > today
    except ValueError: return False


def snapshot(source, identity, name, price, currency, condition, url):
    from .catalogs import Deal
    return Deal(source, offer_key('flight-v1', *identity), name, url, 0,
                price=price, condition=condition, category='Vuelos', currency=currency,
                reference_kind='flight_history')


def jetsmart_fares(html, today):
    # El JSON es contenido de la página pública; no ejecutar JavaScript ni usar eval.
    match = re.search(r"\blet\s+list\s*=\s*JSON\.parse\('([^']*)'\)\s*;", html or '')
    if not match: raise ValueError('No se encontró el catálogo público JetSMART')
    data = json.loads(match.group(1))
    if not isinstance(data, dict) or not data: raise ValueError('Catálogo JetSMART inválido')
    found = {}
    for row in data.values():
        if not isinstance(row, dict): raise ValueError('Ficha JetSMART inválida')
        if row.get('dep') != 'LIM' or not future_day(row.get('date'), today): continue
        destination = str(row.get('arr') or '')
        if not re.fullmatch('[A-Z]{3}', destination): continue
        price = amount(row.get('pi', {}).get('pen'))
        base = amount(row.get('p', {}).get('pen'))
        tax = amount(row.get('i', {}).get('pen'))
        if not price or not base or tax is None or abs(price - base - tax) > .03: continue
        if not row.get('fn') or not row.get('c') or not row.get('cc'): continue
        if not isinstance(row.get('s'), (int, float)) or row['s'] <= 0: continue
        # Clase, vuelo y hora impiden comparar itinerarios distintos. Ignorar la vuelta sugerida:
        # pi corresponde solo al tramo saliente, como indica la tarjeta de la portada.
        identity = ['JetSMART', 'LIM', destination, row['date'], row['fn'], row['cc'],
                    row['c'], 'PEN', 'ONE_WAY', 'taxes-included']
        condition = (f"Salida publicada: {row['date']} · vuelo {row['cc']}{row['fn']} · clase {row['c']}. "
                     'Solo ida, por persona. Tasas incluidas según la portada; equipaje y extras no confirmados. '
                     'Tarifa publicada desde, sujeta a disponibilidad; confirmar precio final y condiciones en la aerolínea.')
        deal = snapshot('JetSMART', identity, f'Lima (LIM) → {destination}', price, 'PEN', condition, JET_URL)
        old = found.get(deal.identity)
        if old is None or price < old.price: found[deal.identity] = deal
    return list(found.values())


def sky_fares(html, today):
    data = extract_next_data(html)
    try: cache = data['props']['pageProps']['apolloState']['data']
    except (KeyError, TypeError): raise ValueError('No se encontró el catálogo público SKY')
    modules = [v for v in cache.values() if isinstance(v, dict) and v.get('__typename') == 'StandardFareModule']
    if not modules or not any(isinstance(m.get('fares'), list) for m in modules):
        raise ValueError('No se reconocen las tarifas SKY')
    found = {}
    for module in modules:
        for row in module.get('fares', []):
            if row.get('originAirportCode') != 'LIM' or not future_day(row.get('departureDate'), today): continue
            destination = str(row.get('destinationAirportCode') or '')
            currency = row.get('currencyCode')
            price = amount(row.get('totalPrice'))
            if not price or currency not in ('PEN', 'USD') or not re.fullmatch('[A-Z]{3}', destination): continue
            if row.get('flightType') != 'ONE_WAY' or row.get('returnDate') or row.get('redemption'): continue
            # La página muestra explícitamente '+ tasas'. No convertir totalPrice en precio final.
            if '+ tasas' not in html: raise ValueError('Cambió la indicación de tasas SKY; revisar lector')
            seen = row.get('priceLastSeen') or {}
            try: age = float(seen.get('value'))
            except (TypeError, ValueError): continue
            if seen.get('unit') not in ('minutes', 'hours'): continue
            if not 0 <= age <= (1440 if seen['unit'] == 'minutes' else 24): continue
            if not row.get('travelClass'): continue
            fields = ('departureDate', 'returnDate', 'travelClass', 'brandedFareClass', 'flightType',
                      'promoCode', 'departureTime', 'returnTime', 'stops', 'layovers', 'flightDuration', 'nightStay')
            identity = ['SKY', 'LIM', destination, currency, 'taxes-extra'] + [json.dumps(row.get(k), sort_keys=True) for k in fields]
            condition = (f"Salida: {row['departureDate']} · {row['travelClass']} · solo ida, por persona. "
                         'Precio base publicado desde + tasas; equipaje, horario y extras no confirmados. '
                         'Compara la tarifa anunciada para esa fecha, no un mismo vuelo confirmado. '
                         'Confirmar precio final y disponibilidad en SKY.')
            if row.get('promoCode'): condition += ' Código: ' + str(row['promoCode'])
            deal = snapshot('SKY', identity, f"Lima (LIM) → {row.get('destinationCity') or destination} ({destination})",
                            price, currency, condition, SKY_URL)
            old = found.get(deal.identity)
            if old is None or price < old.price: found[deal.identity] = deal
    return list(found.values())


def observe_flight(state, deal, now):
    day = int(now // 86400)
    rows = state.history.get(deal.history_key, [])
    previous = {r[0]: r[1] for r in rows if isinstance(r, (list, tuple)) and len(r) == 2
                and isinstance(r[0], int) and day - 30 <= r[0] < day
                and isinstance(r[1], (int, float)) and amount(r[1]) is not None}
    # Tres días distintos como mínimo: una sola observación alta no define una buena oferta.
    baseline = min(previous.values()) if len(previous) >= 3 else None
    pending_key = offer_key('flight-drop', deal.history_key, deal.price)
    saved = state.flight_alerts.get(pending_key, {})
    if saved.get('created', 0) >= now - 7 * 86400 and amount(saved.get('reference')):
        baseline = saved['reference']
    state.observe(deal, now)
    if baseline is None: return None
    pct = int(((1 - Decimal(str(deal.price)) / Decimal(str(baseline))) * 100).to_integral_value(rounding=ROUND_FLOOR))
    if not 50 <= pct < 100: return None
    deal.pct, deal.regular, deal.previous_min = pct, baseline, baseline
    if not saved or saved.get('created', 0) < now - 7 * 86400:
        state.flight_alerts[pending_key] = {'reference': baseline, 'created': now}
    return deal


def scan_flights(state, now, http_factory=HttpClient, sources=None):
    sources = sources if sources is not None else [('JetSMART', JET_URL, jetsmart_fares), ('SKY', SKY_URL, sky_fares)]
    deals, reports = [], []
    today = datetime.fromtimestamp(now, LIMA).date()
    for name, url, parser in sources:
        client = http_factory(delay=1.5, timeout=25, max_requests=5)
        count, error = 0, None
        try:
            parts = urlsplit(url)
            robots = client.get(f'{parts.scheme}://{parts.netloc}/robots.txt')
            # SKY responde con la portada de su SPA incluso en /robots.txt: no publica
            # directivas allí. No confundir ese HTML con permiso explícito ni con bloqueo.
            sky_shell = (name == 'SKY' and robots and '<title>Sky</title>' in robots
                         and 'sky-root-config.js' in robots and 'user-agent:' not in robots.lower())
            if robots and 'user-agent:' in robots.lower():
                rules = RobotFileParser(); rules.parse(robots.splitlines())
                if not rules.can_fetch(client.user_agent, url): raise ValueError('robots.txt no permite leer esta página')
            elif not sky_shell:
                raise ValueError('No se pudo verificar robots.txt')
            try: observations = parser(client.get(url), today)
            except ValueError:
                # JetSMART alterna al azar entre su portada completa y otra ligera sin el carrusel
                # de tarifas (misma página, sin bloqueo). Una sola relectura, con la pausa normal,
                # separa eso de un cambio real de formato, que sigue marcándose como error.
                observations = parser(client.get(url), today)
            count = len(observations)
            for deal in observations:
                alert = observe_flight(state, deal, now)
                if alert: deals.append(alert)
        except Exception as exc:
            error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:140]
        reports.append((name + '/tarifas desde Lima', count, error))
    return deals, reports


def scan_trips(state, now):
    from .catalogs import scan_travel
    benefits, reports = scan_travel(state, now)
    flights, extra = scan_flights(state, now)
    return benefits + flights, reports + extra

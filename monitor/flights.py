"""Tarifas publicadas desde Lima; nunca consulta ni automatiza reservas."""
import csv
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, ROUND_HALF_UP
import json
import math
import os
from pathlib import Path
import re
import statistics
from urllib.parse import urlsplit, urlencode
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


_COORDS = None
_NAMES = {}


def place(code):
    coords(code)
    return _NAMES.get(code) or code


def coords(code):
    """Coordenadas públicas (OurAirports y ciudades de Travelpayouts) incluidas en el repositorio."""
    global _COORDS
    if _COORDS is None:
        path = Path(__file__).parent / 'datos' / 'aeropuertos.csv'
        with open(path, encoding='utf-8', newline='') as f:
            rows = list(csv.DictReader(f))
        _COORDS = {r['codigo']: (float(r['lat']), float(r['lon'])) for r in rows}
        _NAMES.update((r['codigo'], r['ciudad']) for r in rows)
    return _COORDS.get(code)


def distance_km(origin, destination):
    a, b = coords(origin), coords(destination)
    if not a or not b or origin == destination: return None
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return round(2 * 6371 * math.asin(math.sqrt(h)))


# Tramos de distancia por trayecto. Cada uno tiene su propia banda: un vuelo corto
# siempre cuesta más por kilómetro que uno largo, así que no se mezclan.
TRAMOS = [(1200, 'nacional'), (4000, 'regional'), (8000, 'medio'), (float('inf'), 'largo')]
BAND_MIN = 20          # tarifas distintas necesarias antes de opinar
BAND_DAYS = 30


def tramo(km):
    return next(name for limit, name in TRAMOS if km < limit)


def destination_code(deal):
    match = re.search(r'([A-Z]{3})\)?$', deal.name)
    return match.group(1) if match else None


def observe_distance(state, deal, now, band, km, trips=1):
    """Centavos por kilómetro frente a la mediana de su tramo, con historia propia del monitor.

    La banda la calcula el monitor con lo que junta; no se inventan referencias.
    Devuelve la oferta si queda al menos 50 % bajo la mediana y no parece un error de datos."""
    day = int(now // 86400)
    cents = deal.price * 100 / (km * trips)
    key = f'{band}|{tramo(km)}'
    bands = state.datos.setdefault('bandas_vuelos', {})
    rows = {k: v for k, v in bands.get(key, {}).items()
            if isinstance(v, list) and len(v) == 2 and day - BAND_DAYS <= v[0] <= day}
    # Mediana antes de registrar la tarifa actual: no se compara consigo misma.
    others = sorted(v[1] for k, v in rows.items() if k != deal.history_key)
    rows[deal.history_key] = [day, round(cents, 3)]
    bands[key] = rows
    if len(others) < BAND_MIN: return None
    median = statistics.median(others)
    ratio = cents / median
    # Por debajo de una quinta parte de la mediana casi siempre es un error de datos
    # (moneda equivocada, ida contada como ida y vuelta, tarifa fantasma): no se avisa.
    if ratio < 0.2 or ratio > 0.5: return None
    deal.pct = int(((1 - Decimal(str(ratio))) * 100).to_integral_value(rounding=ROUND_FLOOR))
    deal.reference_kind = 'flight_distance'
    deal.regular = round(median * km * trips / 100, 2)
    deal.previous_min = None
    deal.condition = (f'{km:,} km por trayecto · tramo {tramo(km)} · {cents:.1f} centavos/km '
                      f'contra una mediana de {median:.1f} en {len(others)} tarifas observadas del mismo tramo '
                      f'(últimos {BAND_DAYS} días). ' + deal.condition)
    return deal


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
        deal = snapshot('JetSMART', identity, f'Lima (LIM) → {place(destination)} ({destination})', price, 'PEN', condition, JET_URL)
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
            misses_key = name + '/portada-sin-tarifas'
            try: observations = parser(client.get(url), today)
            except ValueError:
                # JetSMART alterna al azar entre su portada completa y otra ligera sin el carrusel
                # de tarifas (misma página, sin bloqueo). Se relee una vez; si vuelve la ligera, esa
                # ronda queda sin tarifas pero no en rojo. Tres rondas seguidas así sí es un error:
                # probablemente cambió el formato.
                html = client.get(url)
                try: observations = parser(html, today)
                except ValueError:
                    misses = state.cursors.get(misses_key, 0) + 1
                    state.cursors[misses_key] = misses
                    if name != 'JetSMART' or 'JetSMART' not in (html or '') or misses >= 3: raise
                    observations = None
            if observations is None:
                observations = []
            else:
                state.cursors.pop(misses_key, None)
            count = len(observations)
            for deal in observations:
                plain = replace(deal)
                alert = observe_flight(state, deal, now)
                # La banda por distancia se alimenta siempre; si ya hubo caída histórica
                # no se manda un segundo aviso del mismo vuelo.
                km = distance_km('LIM', destination_code(plain) or '')
                cheap = observe_distance(state, plain, now, f'{name}|{plain.currency}', km) if km else None
                if alert or cheap: deals.append(alert or cheap)
        except Exception as exc:
            error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:140]
        reports.append((name + '/tarifas desde Lima', count, error))
    return deals, reports


# ---- Travelpayouts: descubrir destinos baratos desde Lima ---------------------------

TP_API = 'https://api.travelpayouts.com'
TP_EVERY = 6 * 3600     # cuidar la cuota: una lectura cada 6 horas aunque la ronda sea cada 30 min
TP_CONFIRM = 3          # consultas de calendario como máximo por ronda


def aviasales_link(origin, destination, depart, back=None):
    stamp = lambda d: d[8:10] + d[5:7]
    return f'https://www.aviasales.com/search/{origin}{stamp(depart)}{destination}{stamp(back) if back else ""}1'


def travelpayouts_directions(payload, today, now):
    """Lee v1/city-directions: un precio por destino. Los precios de ida y vuelta traen return_at."""
    from .catalogs import Deal
    if not isinstance(payload, dict) or payload.get('success') is not True or not isinstance(payload.get('data'), dict):
        raise ValueError('Respuesta de Travelpayouts no reconocida')
    if str(payload.get('currency', '')).lower() != 'usd':
        raise ValueError('Travelpayouts no respondió en dólares')
    fares = []
    for code, row in payload['data'].items():
        if not isinstance(row, dict) or row.get('origin') != 'LIM': continue
        destination = str(row.get('destination') or code)
        price = amount(row.get('price'))
        depart = str(row.get('departure_at') or '')[:10]
        back = str(row.get('return_at') or '')[:10] or None
        if not price or not re.fullmatch('[A-Z]{3}', destination) or not future_day(depart, today): continue
        if back and back < depart: continue
        try:
            if datetime.fromisoformat(str(row.get('expires_at')).replace('Z', '+00:00')).timestamp() < now: continue
        except (TypeError, ValueError): continue
        stops = row.get('transfers')
        identity = ['Travelpayouts', 'LIM', destination, depart, back or '', str(row.get('airline') or ''),
                    str(stops), 'USD']
        condition = (f"{'Ida y vuelta' if back else 'Solo ida'}: salida {depart}" + (f', regreso {back}' if back else '')
                     + f" · aerolínea {row.get('airline') or 'no informada'} · "
                     + ('directo' if stops == 0 else f'{stops} escala(s)' if isinstance(stops, int) else 'escalas no informadas')
                     + '. Precio encontrado en búsquedas de otros usuarios (caché de hasta 7 días), no tarifa en vivo: '
                       'abrir la búsqueda para ver el precio actual, tasas y equipaje.')
        fares.append(Deal('Travelpayouts', offer_key('flight-tp', *identity), f'Lima (LIM) → {place(destination)} ({destination})',
                          aviasales_link('LIM', destination, depart, back), 0, price=price, condition=condition,
                          category='Vuelos', currency='USD', reference_kind='flight_history'))
    return fares


def travelpayouts_month(payload, deal):
    """v2/prices/month-matrix: otras fechas del mismo mes con precio parecido (flexibilidad)."""
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise ValueError('Calendario de Travelpayouts no reconocido')
    days = sorted({str(r.get('depart_date'))[:10] for r in payload['data']
                   if isinstance(r, dict) and r.get('actual') is not False
                   and (amount(r.get('value')) or 1e12) <= deal.price * 1.1})
    return days


def scan_travelpayouts(state, now, token=None, http_factory=HttpClient):
    token = (token if token is not None else os.environ.get('TRAVELPAYOUTS_TOKEN', '')).strip()
    last = state.cursors.get('travelpayouts', 0)
    if not token or (isinstance(last, (int, float)) and now - last < TP_EVERY): return [], []
    client = http_factory(delay=1.5, timeout=25, max_requests=2 + TP_CONFIRM)
    headers = {'X-Access-Token': token}
    today = datetime.fromtimestamp(now, LIMA).date()
    deals, count, error = [], 0, None
    try:
        query = urlencode({'origin': 'LIM', 'currency': 'usd'})
        fares = travelpayouts_directions(json.loads(client.get(f'{TP_API}/v1/city-directions?{query}', headers=headers) or 'null'), today, now)
        count = len(fares)
        for deal in fares:
            km = distance_km('LIM', destination_code(deal) or '')
            round_trip = 'Ida y vuelta' in deal.condition
            cheap = observe_distance(state, deal, now, 'Travelpayouts|USD|' + ('ida-vuelta' if round_trip else 'ida'),
                                     km, 2 if round_trip else 1) if km else None
            if cheap: deals.append(cheap)
        deals.sort(key=lambda d: -d.pct)
        for deal in deals[:TP_CONFIRM]:
            match = re.search(r'salida (\d{4}-\d{2})-\d{2}', deal.condition)
            query = urlencode({'origin': 'LIM', 'destination': destination_code(deal), 'currency': 'usd',
                               'month': match.group(1) + '-01', 'show_to_affiliates': 'true'})
            days = travelpayouts_month(json.loads(client.get(f'{TP_API}/v2/prices/month-matrix?{query}', headers=headers) or 'null'), deal)
            if len(days) > 1: deal.condition += (' Otras salidas del mes con precio parecido: ' + ', '.join(d[8:] for d in days[:12]) + ' (la duración del viaje y las condiciones pueden ser otras).')
        state.cursors['travelpayouts'] = int(now)
    except Exception as exc:
        # El token no aparece en los mensajes: HttpClient solo incluye tipo y texto del error.
        error = 'acceso bloqueado o token rechazado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:140]
    return deals, [('Travelpayouts/destinos desde Lima', count, error)]


def scan_trips(state, now):
    from .catalogs import scan_travel
    benefits, reports = scan_travel(state, now)
    flights, extra = scan_flights(state, now)
    discovered, more = scan_travelpayouts(state, now)
    return benefits + flights + discovered, reports + extra + more

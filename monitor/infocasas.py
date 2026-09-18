"""Infocasas: ventas y alquileres publicados en los últimos 30 días en Lima Metropolitana.

Es la fuente de alquileres que Urbania y Adondevivir no permiten leer (bloqueo de Cloudflare).
Sus reglas de robots.txt permiten estos listados; solo se prohíben combinaciones «-y-» y rutas
internas. Se lee el JSON que la propia página trae (`__NEXT_DATA__`), sin APIs internas.
"""
from __future__ import annotations

import json
import os
import re
import statistics
from urllib.robotparser import RobotFileParser

from .http import HttpClient, Blocked

BASE = 'https://www.infocasas.com.pe'
# Los 43 distritos de Lima Metropolitana (sin el Callao), con la forma de dirección de Infocasas.
DISTRICTS = ['ancon', 'ate', 'barranco', 'brena', 'carabayllo', 'cercado-de-lima', 'chaclacayo', 'chorrillos',
             'cieneguilla', 'comas', 'el-agustino', 'independencia', 'jesus-maria', 'la-molina', 'la-victoria',
             'lince', 'los-olivos', 'lurigancho-chosica', 'lurin', 'magdalena-del-mar', 'miraflores', 'pachacamac',
             'pucusana', 'pueblo-libre', 'puente-piedra', 'punta-hermosa', 'punta-negra', 'rimac', 'san-bartolo',
             'san-borja', 'san-isidro', 'san-juan-de-lurigancho', 'san-juan-de-miraflores', 'san-luis',
             'san-martin-de-porres', 'san-miguel', 'santa-anita', 'santa-maria-del-mar', 'santa-rosa',
             'santiago-de-surco', 'surquillo', 'villa-el-salvador', 'villa-maria-del-triunfo']
SEARCHES = [(op, kind, d) for d in DISTRICTS for kind in ('departamentos', 'casas') for op in ('venta', 'alquiler')]
FRESH = 'publicado-ultimos-30-dias'

MIN_COMPARABLES = 8
RADIUS_KM = 1.5
KEEP_DAYS = 120         # los alquileres cambian lento: cuatro meses de avisos sirven de comparables
AREA_BAND = (0.7, 1.4)  # comparables de tamaño parecido, nunca m² de terreno con construidos


def pages_budget():
    try: return max(10, min(150, int(os.environ.get('PAGINAS_INFOCASAS', '') or 60)))
    except ValueError: return 60


def listing_data(html):
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html or '', re.S)
    try: fast = json.loads(match.group(1))['props']['pageProps']['fetchResult']['searchFast']
    except (AttributeError, KeyError, TypeError, ValueError): raise ValueError('El listado de Infocasas cambió de formato')
    if not isinstance(fast.get('data'), list): raise ValueError('El listado de Infocasas no trae avisos')
    return fast['data'], int((fast.get('paginatorInfo') or {}).get('lastPage') or 1)


def _sheet(item, field):
    for row in item.get('technicalSheet') or []:
        if isinstance(row, dict) and row.get('field') == field: return str(row.get('value') or '').strip()
    return ''


def _money(text, rate):
    """«S/ 300» o «U$S 120» a dólares."""
    match = re.search(r'(S/|U\$S|US\$)\s*([\d.,]+)', text or '')
    if not match: return 0.0
    value = float(re.sub(r'[.,](?=\d{3}\b)', '', match.group(2)).replace(',', '.'))
    return value / rate if match.group(1) == 'S/' else value


def parse_item(item, kind, rate):
    """Aviso normalizado en dólares. Devuelve None si le falta lo indispensable para compararlo."""
    price = item.get('price') or {}
    usd = item.get('price_amount_usd')
    op = ((item.get('operation_type') or {}).get('name') or '').lower()
    if price.get('hidePrice') or not isinstance(usd, (int, float)) or usd <= 0 or op not in ('venta', 'alquiler'): return None
    area = item.get('m2Built') or (item.get('m2') if kind == 'departamentos' else 0)
    try: lat, lng = float(item.get('latitude')), float(item.get('longitude'))
    except (TypeError, ValueError): return None
    if not area or not 15 <= float(area) <= 1000 or not (-12.6 < lat < -11.6 and -77.3 < lng < -76.6): return None
    # Avisos publicados en la operación equivocada (una «venta» de US$ 900 es un alquiler) ensucian las medianas.
    per_m2 = usd / float(area)
    if (op == 'venta' and per_m2 < 200) or (op == 'alquiler' and not 1 <= per_m2 <= 60): return None
    currency = (price.get('currency') or {}).get('name')
    year = _sheet(item, 'constructionYear')
    neighbourhood = ((item.get('locations') or {}).get('neighbourhood') or [{}])[0].get('name', '')
    text = (str(item.get('title') or '') + ' ' + re.sub(r'<[^>]+>', ' ', str(item.get('description') or ''))).lower()
    link = str(item.get('link') or '')
    return {
        'op': op, 'tipo': kind, 'usd': float(usd), 'area': float(area), 'lat': round(lat, 5), 'lng': round(lng, 5),
        'mon': 'PEN' if currency == 'S/' else 'USD', 'monto': float(price.get('amount') or usd),
        'mant': round(_money(_sheet(item, 'commonExpenses'), rate), 2), 'anio': year if re.fullmatch(r'(19|20)\d\d', year) else '',
        'dorm': _sheet(item, 'bedrooms'), 'zona': neighbourhood[:40], 'titulo': str(item.get('title') or '').strip()[:80],
        'texto': text[:4000], 'u': BASE + link if link.startswith('/') else link,
    }


def site_rate(items, fallback):
    """Tipo de cambio que usa la propia página para convertir los avisos en soles."""
    for item in items:
        price = item.get('price') or {}
        if (price.get('currency') or {}).get('name') == 'S/' and item.get('price_amount_usd'):
            rate = float(price['amount']) / float(item['price_amount_usd'])
            if 2.5 < rate < 5: return rate
    return fallback


def scan_listings(state, now, rate, http_factory=HttpClient):
    """Lee por turnos las búsquedas (operación, tipo, distrito) de avisos recientes."""
    data = state.datos.setdefault('infocasas', {})
    store = data.setdefault('avisos', {})
    day = int(now // 86400)
    budget = pages_budget()
    client = http_factory(delay=2, timeout=40, max_requests=budget + 2)
    read, error, fresh = 0, None, []
    cursor = data.get('turno', 0) if isinstance(data.get('turno'), int) else 0
    try:
        rules = RobotFileParser(); rules.parse((client.get(BASE + '/robots.txt') or '').splitlines())
        for step in range(len(SEARCHES)):
            if read >= budget: break
            op, kind, district = SEARCHES[(cursor + step) % len(SEARCHES)]
            page = max(1, int(data.get('pagina', 1))) if step == 0 else 1
            last = page
            while page <= last and read < budget:
                url = f'{BASE}/{op}/{kind}/lima/{district}/{FRESH}' + (f'/pagina{page}' if page > 1 else '')
                if not rules.can_fetch(client.user_agent, url): raise ValueError('robots.txt ya no permite ' + url)
                html = client.get(url); read += 1
                if html is None: last = 0; break
                items, last = listing_data(html)
                rate = data['tc'] = site_rate(items, data.get('tc') or rate)
                for item in items:
                    parsed = parse_item(item, kind, rate)
                    if not parsed or parsed['op'] != op: continue
                    key = str(item.get('id'))
                    old = store.get(key) or {}
                    prices = old.get('p', [])
                    if not prices or prices[-1][1] != parsed['usd']: prices.append([day, parsed['usd']])
                    text = parsed.pop('texto')  # solo se guardan las alertas, no la descripción
                    flags = sorted(w for w in BAD_WORDS if re.search(r'(?<!\w)' + re.escape(w) + r'(?!\w)', text))
                    store[key] = dict(parsed, flags=flags, p=prices[-8:], f=old.get('f', day), r=day, dist=district)
                    fresh.append(key)
                page += 1
                data['pagina'] = page
            if page <= last: break  # se acabó el presupuesto a mitad de la búsqueda: se retoma la próxima vez
            data['turno'] = (cursor + step + 1) % len(SEARCHES)
            data['pagina'] = 1
    except Exception as exc:
        error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:140]
    for key in [k for k, v in store.items() if v.get('r', 0) < day - KEEP_DAYS]: store.pop(key)
    return sorted(set(fresh)), read, error


# Frases completas: «aires» a secas marcaría «aires acondicionados» y «posesión» marcaría «entrega de posesión inmediata».
BAD_WORDS = ['derechos y acciones', 'acciones y derechos', 'venta de aires', 'derecho de aires', 'derechos de aires',
             'certificado de posesion', 'certificado de posesión', 'constancia de posesion', 'constancia de posesión',
             'sin titulo', 'sin título', 'sin saneamiento', 'independizacion', 'independización', 'sucesion intestada',
             'sucesión intestada', 'anticresis', 'usufructo', 'bien futuro', 'ocupado', 'posesionarios',
             'desocupacion', 'desocupación', 'embargo', 'medida cautelar', 'hipoteca vigente', 'remate', 'demo',
             'traspaso', 'solo terreno']


def comparables(store, listing, op, day):
    from .inmuebles import distance_km
    low, high = AREA_BAND
    here = (listing['lat'], listing['lng'])
    values = [v['usd'] / v['area'] for v in store.values()
              if v is not listing and v['op'] == op and v['tipo'] == listing['tipo'] and not v.get('flags')
              and v.get('r', 0) >= day - KEEP_DAYS and low * listing['area'] <= v['area'] <= high * listing['area']
              and distance_km(here, (v['lat'], v['lng'])) <= RADIUS_KM]
    return statistics.median(values) if len(values) >= MIN_COMPARABLES else None, len(values)


def evaluate_listing(store, key, day, rate):
    """Rentabilidad implícita frente a la de su micro-zona (FUENTES.md, grupo 5)."""
    listing = store[key]
    if listing['op'] != 'venta' or listing.get('flags'): return None
    money = (lambda v: f"S/ {v * rate:,.0f}") if listing['mon'] == 'PEN' else (lambda v: f"US$ {v:,.0f}")
    title = (f"🏠 {listing['tipo'][:-1].capitalize()} en venta · {listing['zona'] or listing['dist'].replace('-', ' ').title()}"
             f" · {listing['area']:g} m²" + (f" · {listing['dorm']} dorm." if listing.get('dorm') else ''))
    age = (f"Construido en {listing['anio']}" + (' (antes de la norma sísmica de 1997)' if listing['anio'] < '1997' else '')
           if listing.get('anio') else 'Antigüedad no informada')
    prices = [p for _, p in listing['p']]
    if len(prices) > 1 and prices[-1] <= max(prices[:-1]) * 0.9 + 1e-6:
        drop = round(1 - prices[-1] / max(prices[:-1]), 4)
        return 40 + drop * 100, [title, f"💰 {money(prices[-1])}  |  📉 bajó {drop:.0%} (antes {money(max(prices[:-1]))})", age]
    rent_m2, rents = comparables(store, listing, 'alquiler', day)
    sale_m2, sales = comparables(store, listing, 'venta', day)
    if not rent_m2 or not sale_m2: return None
    own_m2 = listing['usd'] / listing['area']
    if own_m2 < 0.3 * sale_m2: return None  # precio o área mal escritos
    rent = rent_m2 * listing['area'] - listing.get('mant', 0)
    implied, zone = rent * 12 / listing['usd'], rent_m2 * 12 / sale_m2
    ratio = implied / zone
    # Más de dos veces la rentabilidad de su zona no es ganga: es una advertencia.
    if not 1.3 <= ratio <= 2: return None
    return 30 + ratio * 20, [
        title,
        f"💰 {money(listing['usd'])}  |  rentabilidad estimada {implied:.1%} (su zona: {zone:.1%})" + (' 🚨' if ratio >= 1.5 else ''),
        f"Alquiler estimado S/ {rent * rate:,.0f} al mes: mediana de {rents} alquileres parecidos a menos de {RADIUS_KM:g} km"
        + (f", menos mantenimiento S/ {listing['mant'] * rate:,.0f}" if listing.get('mant') else ''),
        f"Venta: US$ {own_m2:,.0f}/m² contra US$ {sale_m2:,.0f}/m² de {sales} ventas cercanas",
        age,
    ]

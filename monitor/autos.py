"""Grupo autos: avisos públicos de Neoauto. El descuento se calcula contra los propios avisos.

Solo mapas del sitio y páginas de aviso (sin `?`, que su robots.txt prohíbe). No consulta
SUNARP ni papeletas: el aviso deja el enlace para revisarlo a mano.
"""
from __future__ import annotations

from datetime import datetime
import json
import logging
import os
import re
import statistics
from urllib.robotparser import RobotFileParser

from .http import HttpClient, Blocked
from .notify import LIMA

BASE = 'https://neoauto.com'
SITEMAPS = {kind: f'{BASE}/sitemap-avisos-autos-{kind}s.xml' for kind in ('nuevo', 'seminuevo', 'usado')}
AD_URL = re.compile(r'^https://neoauto\.com/auto/(nuevo|seminuevo|usado)/([a-z0-9-]+)-(\d{4})-(\d{4,9})$')
SUNARP = 'https://consultavehicular.sunarp.gob.pe/consulta-vehicular'

MIN_COMPARABLES = 8
KEEP_DAYS = 60          # un aviso retirado se conserva un tiempo: su historia es la que da valor
FRESH_DAYS = 21         # precios más viejos no entran en las medianas
MAX_ALERTS = 3

# Palabras que descartan el aviso como oferta (FUENTES.md, "Los filtros que separan una ganga de una trampa").
RED_FLAGS = ['choque', 'chocado', 'siniestrado', 'siniestro', 'para reparar', 'con detalle', 'no camina',
             'motor malogrado', 'papeles en tramite', 'papeles en trámite', 'sin soat', 'deuda', 'prenda',
             'gravamen', 'glp', 'gnv', 'importado usado', 'a nombre de tercero', 'permuta', 'remate']


def settings():
    try: rate = float(os.environ.get('TIPO_CAMBIO', '') or 3.5)
    except ValueError: rate = 3.5
    try: reads = max(10, min(250, int(os.environ.get('LECTURAS_AUTOS', '') or 150)))
    except ValueError: reads = 150
    return rate, reads


def price_range():
    """Rango de interés en dólares (AUTOS_PRECIO_MIN/MAX). Solo filtra avisos, no comparables."""
    bounds = []
    for name, default in (('AUTOS_PRECIO_MIN', 0.0), ('AUTOS_PRECIO_MAX', float('inf'))):
        try: bounds.append(float(os.environ.get(name, '').replace(',', '') or default))
        except ValueError: bounds.append(default)
    return bounds[0], bounds[1]


def sitemap_ads(xml):
    """{id: url} de un mapa del sitio. Neoauto pone la misma fecha en todas las entradas
    (la hora en que generó el archivo), así que <lastmod> no sirve para saber qué cambió."""
    ads = {}
    for url in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', xml or ''):
        match = AD_URL.match(url)
        if match: ads[match.group(4)] = url
    return ads


def _product(html):
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html or '', re.S):
        try: data = json.loads(block)
        except ValueError: continue
        for item in (data.get('@graph') or [data]) if isinstance(data, dict) else []:
            if isinstance(item, dict) and item.get('@type') == 'Product' and isinstance(item.get('offers'), dict):
                return item
    return None


def _number(text):
    digits = re.sub(r'[^\d]', '', str(text or ''))
    return int(digits) if digits else None


def parse_ad(html, url):
    """Ficha de un aviso a partir de sus datos estructurados (schema.org) y del bloque del anuncio."""
    match = AD_URL.match(url)
    product = _product(html)
    if not match or not product: raise ValueError('La página del aviso no trae la ficha del producto')
    ad_id = match.group(4)
    offer = product['offers']
    price = offer.get('price')
    currency = offer.get('priceCurrency')
    if not isinstance(price, (int, float)) or price <= 0 or currency not in ('USD', 'PEN'):
        raise ValueError('Precio del aviso no reconocido')
    props = {p.get('name'): p.get('value') for p in product.get('additionalProperty') or [] if isinstance(p, dict)}
    seller = offer.get('seller') if isinstance(offer.get('seller'), dict) else {}
    address = seller.get('address') if isinstance(seller.get('address'), dict) else {}
    # Bloque del anuncio embebido en la página (texto JSON escapado). Se ancla en el id del aviso
    # para no leer por error los autos sugeridos que la misma página también trae.
    block = re.search(r'\\"publicationDate\\":\\"([^"\\]*)\\",\\"id\\":' + ad_id + r'\b(.{0,1500}?)\\"versionName\\":\\"([^"\\]*)\\"', html, re.S)
    brand = product.get('brand') if isinstance(product.get('brand'), dict) else {}
    description = str(product.get('description') or '')
    record = {
        'u': url, 't': match.group(1), 'm': str(brand.get('name') or '').strip().lower(),
        'mo': str(product.get('model') or '').strip().lower(), 'v': (block.group(3).strip().lower() if block else ''),
        'a': int(match.group(3)), 'km': _number(props.get('Kilometraje')), 'mon': currency, 'precio': float(price),
        # Solo el tipo de vendedor y, si es empresa, su nombre comercial. No se guardan nombres de personas.
        'vend': 'empresa' if seller.get('@type') == 'Organization' else 'particular',
        'tienda': str(seller.get('name') or '')[:60] if seller.get('@type') == 'Organization' else '',
        'dist': str(address.get('addressLocality') or '')[:40], 'pub': (block.group(1) if block else '')[:40],
        'flags': sorted({w for w in RED_FLAGS if re.search(r'\b' + re.escape(w) + r'\b', description.lower())}),
        'nombre': str(product.get('name') or '').title()[:70],
    }
    if not record['m'] or not record['mo']: raise ValueError('El aviso no trae marca o modelo')
    return ad_id, record


def usd(record, rate, price=None):
    price = record['p'][-1][1] if price is None else price
    return price if record['mon'] == 'USD' else price / rate


def _store(state):
    data = state.datos.setdefault('neoauto', {})
    return data.setdefault('avisos', {})


def update_record(ads, ad_id, parsed, day):
    old = ads.get(ad_id)
    price = parsed.pop('precio')
    if old and old.get('mon') == parsed['mon']:
        prices = old.get('p', [])
        if not prices or prices[-1][1] != price: prices.append([day, price])
        parsed.update(p=prices[-12:], f=old.get('f', day))
    else:
        parsed.update(p=[[day, price]], f=day)
    parsed.update(r=day, x=day)
    ads[ad_id] = parsed
    return parsed


def anomalies(record, today_year):
    """Todo lo que no sea el precio. Una ganga real es normal en todo lo demás."""
    found = list(record.get('flags') or [])
    if record['t'] != 'nuevo':
        age = max(1, today_year - record['a'])
        km = record.get('km')
        if km is None: found.append('kilometraje no informado')
        elif not 5000 <= km / age <= 25000: found.append(f'kilometraje raro para el año ({km:,} km)')
    return found


def market(ads, rate, day, today_year=None):
    """Medianas en dólares por (marca, modelo, año) y por versión, solo con precios recientes.

    Los avisos con palabras de alerta o kilometraje raro no entran: un chocado barato bajaría
    la mediana y haría parecer caro a un auto normal."""
    today_year = today_year or datetime.fromtimestamp(day * 86400, LIMA).year
    groups = {}
    for record in ads.values():
        if record.get('x', 0) < day - 2 or record.get('r', 0) < day - FRESH_DAYS or record['t'] == 'nuevo': continue
        if anomalies(record, today_year): continue
        value = usd(record, rate)
        groups.setdefault((record['m'], record['mo'], record['a']), []).append(value)
        if record.get('v'): groups.setdefault((record['m'], record['mo'], record['a'], record['v']), []).append(value)
    return {k: (statistics.median(v), len(v)) for k, v in groups.items() if len(v) >= MIN_COMPARABLES}


def new_car_market(ads, rate, day):
    groups = {}
    for record in ads.values():
        if record['t'] != 'nuevo' or record.get('x', 0) < day - 2: continue
        groups.setdefault((record['m'], record['mo'], record['a'], record.get('v', '')), []).append(usd(record, rate))
    return {k: (statistics.median(v), len(v)) for k, v in groups.items() if len(v) >= MIN_COMPARABLES}


def dealer_points(ads, record, medians, rate, day):
    """¿El resto del inventario de este vendedor está a precio de mercado?"""
    if record['vend'] != 'empresa' or not record.get('tienda'): return 0, ''
    ratios = []
    for other in ads.values():
        if other is record or other.get('tienda') != record['tienda'] or other.get('x', 0) < day - 2: continue
        reference = medians.get((other['m'], other['mo'], other['a']))
        if reference: ratios.append(usd(other, rate) / reference[0])
    if len(ratios) < 3: return 0, ''
    typical = statistics.median(ratios)
    if typical < 0.85: return 0, 'todo el inventario de este vendedor está bajo el mercado: no es un descuento'
    return (15, 'el resto de su inventario está a precio de mercado') if typical <= 1.15 else (0, '')


def evaluate(ads, ad_id, medians, new_medians, rate, day, today_year):
    """Devuelve (puntos, líneas del aviso) o None. Primero lo eliminatorio, después el puntaje."""
    record = ads[ad_id]
    price = usd(record, rate)
    money = lambda v: f'US$ {v:,.0f}'
    title = f"🚗 {record['nombre']}" + (f" · {record['v'].upper()}" if record.get('v') else '')
    facts = ' · '.join(x for x in [record['t'], f"{record['km']:,} km" if record.get('km') is not None else '',
                                   record.get('dist', ''), record['vend']] if x)
    price_line = f"💰 {money(price)}" + (f" (publicado en S/ {record['p'][-1][1]:,.0f})" if record['mon'] == 'PEN' else '')
    problems = anomalies(record, today_year)
    prices = [usd(record, rate, p) for _, p in record['p']]
    # Redondeo a 4 decimales: 20.000 → 18.000 es exactamente 10 %, no 9,999…
    drop = round(1 - price / max(prices[:-1]), 4) if len(prices) > 1 else 0
    old_listing = 'mes' in record.get('pub', '') or day - record.get('f', day) >= 28

    if record['t'] == 'nuevo':
        reference = new_medians.get((record['m'], record['mo'], record['a'], record.get('v', '')))
        if not reference or problems: return None
        below = 1 - price / reference[0]
        if below < 0.08: return None
        return 50 + below * 100, [title, f"{price_line}  |  {below:.0%} bajo otros nuevos iguales" + (' 🚨' if below >= 0.12 else ''),
                                  f"Mediana de {reference[1]} avisos del mismo modelo, versión y año: {money(reference[0])}", facts,
                                  'Confirmar si el precio exige financiar con un banco.']
    if problems: return None
    # Un aviso con versión declarada solo se compara con esa versión (en su año y en los anteriores).
    # Sin versión declarada se usa el modelo completo, y el aviso lo dice. Nunca versión contra modelo.
    version = (record['v'],) if record.get('v') else ()
    same = medians.get((record['m'], record['mo'], record['a'], *version))
    if same and price < 0.55 * same[0]: return None  # sospechoso: estafa, siniestro o precio gancho

    # 1) Bajada de precio: no necesita comparables y es la señal más útil para quien no tiene apuro.
    if drop >= 0.10 and old_listing:
        lines = [title, f"{price_line}  |  📉 bajó {drop:.0%} (antes {money(max(prices[:-1]))})",
                 f"{len(prices) - 1} bajada(s) de precio · {record.get('pub') or 'publicado hace semanas'}", facts]
        if same: lines.append(f"Mercado: mediana de {same[1]} avisos iguales {money(same[0])}")
        return 40 + drop * 100, lines

    # 2) Año gratis + puntaje. Sin comparables suficientes no se opina.
    if not same: return None
    ladder = [medians.get((record['m'], record['mo'], record['a'] - n, *version)) for n in (1, 2, 3)]
    if ladder[0] is None: return None
    if ladder[2] and price < ladder[2][0]: return None  # más barato que tres años antes: hay una razón oculta
    free_years = 2 if ladder[1] and price <= ladder[1][0] else (1 if price <= ladder[0][0] else 0)
    if not free_years: return None
    below = 1 - price / same[0]
    rebate = 20 * min(below, 0.30) / 0.30 if below <= 0.35 else 20 - (below - 0.35) * 100
    dealer, dealer_note = dealer_points(ads, record, medians, rate, day)
    if dealer_note.startswith('todo'): return None
    patience = (5 if old_listing else 0) + (5 if len(prices) > 1 and drop > 0 else 0)
    # Retención relativa aún no se calcula: el puntaje se escala sobre las señales disponibles (80).
    score = round(((35 if free_years == 2 else 20) + max(rebate, -20) + dealer + patience) * 100 / 80)
    if score < 70: return None
    return score, [title,
                   f"{price_line}  |  año gratis: cuesta como uno {record['a'] - free_years}" + (' 🚨' if free_years == 2 else ''),
                   f"Mediana {record['a']}: {money(same[0])} ({same[1]} avisos) · {record['a'] - 1}: {money(ladder[0][0])}"
                   + (f" · {record['a'] - 2}: {money(ladder[1][0])}" if ladder[1] else ''),
                   f"Puntaje {score}/100 · {below:.0%} bajo sus comparables" + (f" · {dealer_note}" if dealer_note else ''),
                   f"Comparado con la versión {record['v'].upper()}" if version else
                   'El aviso no dice su versión: comparado con todas las versiones del modelo', facts]


def scan_autos(state, now, http_factory=HttpClient):
    from .catalogs import Deal
    rate, budget = settings()
    day = int(now // 86400)
    today_year = datetime.fromtimestamp(now, LIMA).year
    client = http_factory(delay=1.5, timeout=40, max_requests=budget + 6)
    ads = _store(state)
    read, failed, error, deals = 0, 0, None, []
    fresh = set()
    try:
        robots = client.get(BASE + '/robots.txt') or ''
        rules = RobotFileParser(); rules.parse(robots.splitlines())
        if 'user-agent' not in robots.lower(): raise ValueError('No se pudo verificar robots.txt')
        listed = {}
        for kind, url in SITEMAPS.items():
            listed.update(sitemap_ads(client.get(url)))
        if len(listed) < 500: raise ValueError(f'Mapas del sitio con muy pocos avisos ({len(listed)}); ¿cambió el formato?')
        for ad_id in listed:
            if ad_id in ads: ads[ad_id]['x'] = day
        # Primero los avisos nuevos (los más recientes antes), después los leídos hace más tiempo.
        queue = sorted((i for i in listed if i not in ads), key=int, reverse=True)
        known = sorted((i for i in listed if i in ads), key=lambda i: ads[i].get('r', 0))
        # Reservar un tercio para precios conocidos; el inventario nuevo no debe impedir releerlos.
        rereads = min(len(known), budget // 3)
        queue = queue[:budget - rereads] + known[:rereads] + queue[budget - rereads:] + known[rereads:]
        for ad_id in queue[:budget]:
            url = listed[ad_id]
            if '?' in url or not rules.can_fetch(client.user_agent, url): continue
            html = client.get(url)
            read += 1
            if html is None:
                ads.pop(ad_id, None); continue
            try: _, parsed = parse_ad(html, url)
            except ValueError: failed += 1; continue
            update_record(ads, ad_id, parsed, day)
            fresh.add(ad_id)
        if read >= 20 and failed > read * 0.3:
            raise ValueError(f'{failed} de {read} avisos no se pudieron leer; revisar el lector')
    except Exception as exc:
        error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:140]
    for ad_id in [i for i, r in ads.items() if r.get('x', 0) < day - KEEP_DAYS]: ads.pop(ad_id)

    medians, new_medians = market(ads, rate, day, today_year), new_car_market(ads, rate, day)
    low, high = price_range()
    for ad_id in fresh:
        if not low <= usd(ads[ad_id], rate) <= high: continue
        result = evaluate(ads, ad_id, medians, new_medians, rate, day, today_year)
        if not result: continue
        points, lines = result
        record = ads[ad_id]
        lines.append('Candidato estadísticamente excelente, no «buen auto»: pide la placa y revisa titulares, '
                     f'papeletas y siniestros antes de decidir. SUNARP: {SUNARP}')
        deals.append(Deal('Neoauto', ad_id, record['nombre'], record['u'], int(points), price=record['p'][-1][1],
                          condition='\n'.join(lines), category='Autos', currency=record['mon'], reference_kind='autos'))
    deals = sorted(deals, key=lambda d: -d.pct)  # deliver limita después de deduplicar
    models = len({k[:3] for k in medians})
    logging.getLogger('catalogs').info('Neoauto: juntando datos · %d modelos-año con %d+ comparables · %d avisos en memoria',
                                       models, MIN_COMPARABLES, len(ads))
    return deals, [('Neoauto/avisos', read, error)]

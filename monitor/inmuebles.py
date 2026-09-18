"""Grupo inmuebles: preventa de Nexo Inmobiliario y adjudicados de Scotiabank.

Urbania y Adondevivir (mismo dueño, mismos avisos) responden con el desafío antibots de Cloudflare
tras dos o tres lecturas: no se usan ni se intenta evadirlo. Tampoco se consulta SUNARP ni predial.
"""
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import statistics
from urllib.robotparser import RobotFileParser

from .http import HttpClient, Blocked
from . import infocasas

NEXO = 'https://nexoinmobiliario.pe'
PROJECT_URL = re.compile(r'^https://nexoinmobiliario\.pe/(departamentos|casas)/([a-z0-9-]+)/[a-z0-9-]+-(\d+)$')
SCOTIA_PDF = ('https://cdn.aglty.io/scotiabank-peru/PDFs/acerca-de/venta-de-inmuebles-y-muebles-adjudicados/'
              'listado-venta-inmuebles.pdf')
SUNARP = 'https://www.sunarp.gob.pe/seccion/servicios/detalles/0/c3.html'

MIN_COMPARABLES = 8
RADIUS_KM = 1.5         # micro-zona: proyectos a 1,5 km o menos, nunca el distrito entero
NEXO_EVERY = 12 * 3600
SCOTIA_EVERY = 7 * 86400
MAX_ALERTS = 3
KEEP_DAYS = 45
BAD_TEXT = ['derechos y acciones', 'acciones y derechos', '% acc', 'aires', 'posesion', 'posesión', 'sin titulo',
            'sin título', 'sin saneamiento', 'independizacion', 'independización', 'sucesion intestada',
            'sucesión intestada', 'anticresis', 'usufructo', 'ocupado', 'posesionario', 'desocupacion',
            'desocupación', 'embargo', 'medida cautelar', 'litigio', 'invadido', 'invasion', 'invasión']


def settings():
    try: rate = float(os.environ.get('TIPO_CAMBIO', '') or 3.5)
    except ValueError: rate = 3.5
    try: reads = max(10, min(120, int(os.environ.get('LECTURAS_INMUEBLES', '') or 60)))
    except ValueError: reads = 60
    return rate, reads


def bad_text(text):
    # Palabras completas: «aires» (derecho de aire) no debe descartar «Urb. Buenos Aires».
    text = re.sub(r'buenos aires', '', text.lower())
    return any(re.search(r'(?<!\w)' + re.escape(w) + r'(?!\w)', text) for w in BAD_TEXT)


def plain(text):
    table = str.maketrans('áéíóúüñ', 'aeiouun')
    return ' '.join(str(text).lower().translate(table).split())


def wanted_districts():
    """INMUEBLES_DISTRITOS, separados por comas. «Surco» basta para «Santiago de Surco»."""
    return [plain(d) for d in os.environ.get('INMUEBLES_DISTRITOS', '').split(',') if d.strip()]


def in_districts(text, districts):
    return not districts or any(d in plain(text) for d in districts)


def soles(value, currency, rate):
    return value if currency == 'PEN' else value * rate


def money(value):
    return f'S/ {value:,.0f}'


def distance_km(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


# ---- Nexo Inmobiliario (preventa y entrega inmediata) ---------------------------------

def parse_project(html, url):
    match = PROJECT_URL.match(url)
    if not match: raise ValueError('Dirección de proyecto no reconocida')
    product = None
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html or '', re.S):
        try: data = json.loads(block)
        except ValueError: continue
        if isinstance(data, dict) and data.get('@type') == 'Product': product = data; break
    if not product: raise ValueError('El proyecto no trae su ficha de producto')
    lat = re.search(r'lat"\s*:\s*"(-?\d+\.\d+)"', html)
    lng = re.search(r'lng"\s*:\s*"(-?\d+\.\d+)"', html)
    if not lat or not lng: raise ValueError('El proyecto no trae su ubicación')
    point = (float(lat.group(1)), float(lng.group(1)))
    if not (-12.6 < point[0] < -11.6 and -77.3 < point[1] < -76.6): raise ValueError('Ubicación fuera de Lima')
    stage = re.search(r'Entrega (en planos|en construcci[oó]n|inmediata)', str(product.get('description') or ''), re.I)
    models = {}
    for block in html.split('fp-modelo-disponible-content')[1:]:
        price = re.search(r'fp-modelo-disponible-price">\s*(S/|US\$)\s*([\d,]+)', block)
        name = re.search(r'fp-modelo-disponible-model">\s*([^<]{1,40}?)\s*<', block)
        feats = re.findall(r'feature-text">\s*([^<]{1,30}?)\s*<', block)[:3]
        area = next((float(f.split()[0]) for f in feats if re.fullmatch(r'\d+(?:\.\d+)?\s*m[²2]', f)), None)
        dorms = next((int(f.split()[0]) for f in feats if re.fullmatch(r'\d+\s*dorms?\.?', f)), None)
        if not price or not name or not area: continue
        value = float(price.group(2).replace(',', ''))
        # Área inverosímil (1.200 escrito por 120) o precio por m² absurdo: fuera.
        if not 18 <= area <= 600 or value <= 0: continue
        models[name.group(1)] = [area, dorms, 'PEN' if price.group(1) == 'S/' else 'USD', value]
    brand = product.get('brand') if isinstance(product.get('brand'), dict) else {}
    return match.group(3), {
        'u': url, 'tipo': match.group(1), 'dist': match.group(2).replace('-', ' ').title(),
        'nombre': str(product.get('name') or '').split(' - ')[0].strip()[:60], 'marca': str(brand.get('name') or '')[:40],
        'lat': round(point[0], 5), 'lng': round(point[1], 5), 'etapa': (stage.group(1).lower() if stage else ''),
        'modelos': models,
    }


def per_m2(project, rate):
    values = [soles(price, cur, rate) / area for area, _, cur, price in project['modelos'].values()]
    return statistics.median(values) if values else None


def update_project(store, pid, parsed, day):
    old = store.get(pid) or {}
    first = old.get('primero', {})
    for name, (_, _, cur, price) in parsed['modelos'].items():
        if name not in first or first[name][0] != cur: first[name] = [cur, price, day]
    parsed.update(primero={k: v for k, v in first.items() if k in parsed['modelos']}, r=day, x=day)
    store[pid] = parsed


def evaluate_project(store, pid, rate, day):
    project = store[pid]
    own = per_m2(project, rate)
    if not own: return None
    title = f"🏢 {project['nombre']} · {project['dist']}" + (f" · entrega {project['etapa']}" if project['etapa'] else '')
    # 1) Bajada de precio de un modelo frente a lo primero que se vio.
    drops = []
    for name, (area, dorms, cur, price) in project['modelos'].items():
        first_cur, first_price, _ = project['primero'].get(name, [cur, price, day])
        if first_cur == cur and price <= first_price * 0.9:
            drops.append((1 - price / first_price, name, area, dorms, cur, first_price, price))
    if drops:
        drop, name, area, dorms, cur, before, now_price = max(drops)
        symbol = 'S/' if cur == 'PEN' else 'US$'
        return 40 + drop * 100, [title, f"💰 {name}: {symbol} {now_price:,.0f}  |  📉 bajó {drop:.0%} (antes {symbol} {before:,.0f})",
                                 f"{area:g} m²" + (f" · {dorms} dorm." if dorms else '') + f" · {money(soles(now_price, cur, rate) / area)}/m²"]
    # 2) Precio por m² frente a proyectos a menos de 1,5 km (micro-zona).
    here = (project['lat'], project['lng'])
    near = [per_m2(p, rate) for k, p in store.items()
            if k != pid and p['tipo'] == project['tipo'] and p.get('r', 0) >= day - 30
            and distance_km(here, (p['lat'], p['lng'])) <= RADIUS_KM]
    near = [v for v in near if v]
    if len(near) < MIN_COMPARABLES: return None
    median = statistics.median(near)
    below = 1 - own / median
    # Más de la mitad bajo la zona no es una ganga: casi siempre es un error de área o de moneda.
    if not 0.23 <= below <= 0.5: return None
    return 30 + below * 100, [title,
                              f"💰 {money(own)}/m²  |  {below:.0%} bajo la zona" + (' 🚨' if below >= 0.33 else ''),
                              f"Mediana de {len(near)} proyectos a menos de {RADIUS_KM:g} km: {money(median)}/m²",
                              'Modelos: ' + '; '.join(f"{n} {a:g} m² {'S/' if c == 'PEN' else 'US$'} {p:,.0f}"
                                                      for n, (a, _, c, p) in list(project['modelos'].items())[:4]),
                              'Preventa: el descuento se paga con riesgo de obra y espera; confirmar fecha de entrega y garantías.']


def scan_nexo(state, now, rate, budget, http_factory=HttpClient):
    data = state.datos.setdefault('nexo', {})
    store = data.setdefault('proyectos', {})
    day = int(now // 86400)
    last = data.get('ultima', 0)
    if now - last < NEXO_EVERY: return [], []
    client = http_factory(delay=1.5, timeout=40, max_requests=budget + 3)
    read, failed, error, fresh = 0, 0, None, []
    try:
        robots = client.get(NEXO + '/robots.txt') or ''
        rules = RobotFileParser(); rules.parse(robots.splitlines())
        listed = {}
        for url in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', client.get(NEXO + '/sitemap-proyectos.xml') or ''):
            match = PROJECT_URL.match(url)
            if match: listed[match.group(3)] = url
        if len(listed) < 100: raise ValueError(f'Mapa de proyectos con muy pocas entradas ({len(listed)})')
        for pid in listed:
            if pid in store: store[pid]['x'] = day
        queue = [p for p in listed if p not in store] + sorted((p for p in listed if p in store), key=lambda p: store[p].get('r', 0))
        for pid in queue[:budget]:
            if not rules.can_fetch(client.user_agent, listed[pid]): continue
            html = client.get(listed[pid]); read += 1
            if html is None: store.pop(pid, None); continue
            try: _, parsed = parse_project(html, listed[pid])
            except ValueError: failed += 1; continue
            if parsed['modelos']: update_project(store, pid, parsed, day); fresh.append(pid)
        if read >= 20 and failed > read * 0.5:
            raise ValueError(f'{failed} de {read} proyectos no se pudieron leer; revisar el lector')
        data['ultima'] = int(now)
    except Exception as exc:
        error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:140]
    for pid in [p for p, v in store.items() if v.get('x', 0) < day - KEEP_DAYS]: store.pop(pid)
    found = []
    for pid in fresh:
        result = evaluate_project(store, pid, rate, day)
        if result: found.append((pid, *result))
    return found, [('Nexo Inmobiliario/proyectos', read, error)]


# ---- Scotiabank: inmuebles adjudicados (PDF mensual) -------------------------------

ROW = re.compile(r'(?m)^(\d{1,3}) (\d{2,6}(?: ?- ?[A-Z])?) ')
VALUE = re.compile(r'([\d,]+\.\d{2})\s+([\d.,]+)\s*(m2|Ha)\b')


def scotia_rows(pdf_bytes):
    from pypdf import PdfReader
    return scotia_text_rows('\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(pdf_bytes)).pages))


def scotia_text_rows(text, minimum=50):
    if 'VENTA DE INMUEBLES' not in text.upper(): raise ValueError('El PDF de adjudicados cambió de formato')
    starts = list(ROW.finditer(text))
    rows = {}
    for i, match in enumerate(starts):
        chunk = re.sub(r'\s+', ' ', text[match.start():starts[i + 1].start() if i + 1 < len(starts) else len(text)])
        value = VALUE.search(chunk)
        if not value: continue
        before = chunk[len(match.group(0)):value.start()].strip()
        rows[re.sub(r'\s', '', match.group(2))] = {
            'valor': float(value.group(1).replace(',', '')), 'area': value.group(2) + ' ' + value.group(3),
            'texto': before[:160], 'lima': bool(re.search(r'\bLIMA (LIMA|CALLAO)\b', before)),
            # Palabra completa: «TERRENO URBANO INSCRITO» termina en «NO INSCRITO» si se compara el texto a secas.
            'inscrito': bool(re.search(r'\bINSCRITO$', chunk.rstrip())) and not re.search(r'\bNO INSCRITO$', chunk.rstrip()),
            'clase': ' '.join(re.findall(r'\b(VIVIENDA|COMERCIAL|INDUSTRIAL|TERRENO URBANO|CASA HABITACION|DEPARTAMENTO|LOCAL COMERCIAL|OFICINA)\b', chunk[value.end():]))[:60],
        }
    if len(rows) < minimum: raise ValueError(f'Muy pocas filas leídas del PDF de adjudicados ({len(rows)})')
    return rows


def scan_scotia(state, now, http_factory=HttpClient):
    data = state.datos.setdefault('scotiabank', {})
    if now - data.get('ultima', 0) < SCOTIA_EVERY: return [], []
    client = http_factory(delay=1.5, timeout=60, max_requests=3)
    found, count, error = [], 0, None
    try:
        raw = client.get_bytes(SCOTIA_PDF)
        rows = scotia_rows(raw)
        count = len(rows)
        previous = data.get('filas')
        for exp, row in rows.items():
            if not row['lima'] or not row['inscrito']: continue
            if bad_text(row['texto']) or re.search(r'\bACC\b', row['texto']): continue
            before = (previous or {}).get(exp)
            title = f"🏦 Adjudicado Scotiabank · exp. {exp}"
            facts = f"{row['texto']} · {row['area']}" + (f" · {row['clase'].lower()}" if row['clase'] else '')
            if previous is None: continue  # primera lectura: solo se guarda la lista de referencia
            if before is None:
                found.append((exp, 20, row['valor'], [title, f"💰 US$ {row['valor']:,.0f}  |  nuevo en la lista", facts]))
            elif row['valor'] <= before['valor'] * 0.9:
                drop = 1 - row['valor'] / before['valor']
                found.append((exp, 40 + drop * 100, row['valor'], [title, f"💰 US$ {row['valor']:,.0f}  |  📉 bajó {drop:.0%} (antes US$ {before['valor']:,.0f})", facts]))
        for *_, lines in found:
            lines.append('Precio referencial, sujeto a la valorización final del banco. Revisar la partida registral y si está ocupado.')
        data['filas'] = {k: {'valor': v['valor']} for k, v in rows.items()}
        data['ultima'] = int(now)
    except Exception as exc:
        error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:140]
    return found, [('Scotiabank/adjudicados', count, error)]


def scan_inmuebles(state, now, http_factory=HttpClient):
    from .catalogs import Deal
    rate, budget = settings()
    projects, reports = scan_nexo(state, now, rate, budget, http_factory)
    banks, more = scan_scotia(state, now, http_factory)
    fresh, pages, error = infocasas.scan_listings(state, now, rate, http_factory)
    reports.append(('Infocasas/avisos recientes', pages, error))
    deals = []
    districts = wanted_districts()
    listings = state.datos.setdefault('infocasas', {}).setdefault('avisos', {})
    site_rate = state.datos['infocasas'].get('tc') or rate
    day = int(now // 86400)
    for key in fresh:
        listing = listings.get(key)
        if not listing or not in_districts(listing['zona'] + ' ' + listing['dist'].replace('-', ' '), districts): continue
        result = infocasas.evaluate_listing(listings, key, day, site_rate)
        if not result: continue
        points, lines = result
        lines.append(f'Antes de decidir: partida registral en SUNARP ({SUNARP}), cargas, mantenimiento real y estado del edificio.')
        deals.append(Deal('Infocasas', key, listing['titulo'], listing['u'], int(points), price=listing['usd'], currency='USD',
                          condition='\n'.join(lines), category='Inmuebles', reference_kind='inmuebles'))
    for key, points, lines in projects:
        project = state.datos['nexo']['proyectos'][key]
        if not in_districts(project['dist'], districts): continue
        lines.append(f'Antes de decidir: partida registral en SUNARP ({SUNARP}), parámetros municipales y deuda predial.')
        deals.append(Deal('Nexo', key, project['nombre'], project['u'], int(points), price=per_m2(project, rate),
                          condition='\n'.join(lines), category='Inmuebles', reference_kind='inmuebles'))
    for exp, points, value, lines in banks:
        if not in_districts(lines[2], districts): continue
        deals.append(Deal('Scotiabank', exp, 'Adjudicado ' + exp, SCOTIA_PDF, int(points), price=value, currency='USD',
                          condition='\n'.join(lines), category='Inmuebles', reference_kind='inmuebles'))
    store = state.datos.get('nexo', {}).get('proyectos', {})
    counts = [sum(v['op'] == op for v in listings.values()) for op in ('venta', 'alquiler')]
    logging.getLogger('catalogs').info('Nexo: %d proyectos · Infocasas: %d ventas y %d alquileres en memoria',
                                       len(store), *counts)
    return sorted(deals, key=lambda d: -d.pct), reports + more  # límite después de deduplicar

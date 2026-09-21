"""Áreas urbanas aproximadas del monitor; no son límites administrativos.

Las comparaciones continúan limitadas a 1,5 km dentro de cada ciudad.
"""
import math
import re
import unicodedata

CITIES = {
    'lima': ('Lima', (-12.6, -11.6, -77.3, -76.6)),
    'arequipa': ('Arequipa', (-16.6, -16.15, -71.75, -71.3)),
    'cusco': ('Cusco', (-13.65, -13.4, -72.15, -71.7)),
    'cajamarca': ('Cajamarca', (-7.3, -7.0, -78.65, -78.35)),
    'trujillo': ('Trujillo', (-8.3, -7.95, -79.2, -78.85)),
    'huaraz': ('Huaraz', (-9.7, -9.35, -77.7, -77.35)),
}


def city_at(lat, lng):
    try: lat, lng = float(lat), float(lng)
    except (ValueError, TypeError): return None
    if not math.isfinite(lat) or not math.isfinite(lng): return None
    return next((key for key, (_, (south, north, west, east)) in CITIES.items()
                 if south < lat < north and west < lng < east), None)


def listing_city(row):
    # Las memorias anteriores no tenían ciudad; se migra por coordenadas al leer.
    return city_at(row.get('lat'), row.get('lng'))


def city_label(row):
    key = listing_city(row)
    return CITIES[key][0] if key else ''


def bank_city(text):
    text = ''.join(c for c in unicodedata.normalize('NFKD', text.upper()) if not unicodedata.combining(c))
    pairs = {'lima': r'LIMA (?:LIMA|CALLAO)', 'arequipa': r'AREQUIPA AREQUIPA',
             'cusco': r'CU[ZS]CO CU[ZS]CO', 'cajamarca': r'CAJAMARCA CAJAMARCA',
             'trujillo': r'LA LIBERTAD TRUJILLO', 'huaraz': r'ANCASH HUARAZ'}
    # Pareja departamento/provincia, no una mención aislada de ciudad en la dirección.
    return next((key for key, pair in pairs.items() if re.search(r'\b'+pair+r'\b', text)), None)

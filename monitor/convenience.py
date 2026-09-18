"""Catálogos públicos de Tambo y Makro para el tema de comida/bazar."""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import json
import re
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from .http import HttpClient, Blocked

TAMBO = 'https://www.tambo.pe/pedir'
MAKRO = 'https://makro.plazavea.com.pe/api/catalog_system/pub/products/search?O=OrderByBestDiscountDESC&_from=0&_to=49'


def discount(price, regular):
    if isinstance(price, bool) or isinstance(regular, bool): return None
    try:
        p, r = Decimal(str(price)), Decimal(str(regular))
        if not p.is_finite() or not r.is_finite() or not 0 < p < r: return None
        pct = int(((1 - p/r)*100).to_integral_value(rounding=ROUND_FLOOR))
        return (float(p), float(r), pct) if 60 <= pct < 95 else None
    except (InvalidOperation, TypeError, ValueError): return None


def tambo_products(html):
    from .catalogs import Deal
    m = re.search(r'window\.__remixContext\s*=\s*', html or '')
    if not m: raise ValueError('No se reconoce el catálogo Tambo')
    data = json.JSONDecoder().raw_decode(html[m.end():])[0]
    products = data['state']['loaderData']['pages/Order/Layout/index']['menuData']['products']
    if not isinstance(products, dict) or not products: raise ValueError('Catálogo Tambo vacío o inválido')
    deals = []
    for pid, item in products.items():
        availability = item.get('availabilityAt') or {}
        if availability.get('available') is not True or availability.get('visible') is not True: continue
        values = discount(availability.get('finalPrice'), availability.get('basePrice'))
        path = item.get('path', '')
        if not values or not path.startswith('/pedir/') or path.startswith('//'): continue
        price, regular, pct = values
        deals.append(Deal('Tambo', pid, item['name'], 'https://www.tambo.pe'+path,
                          pct, price, regular, 'Tambo',
                          'Precio del pack o presentación indicada. Confirmar stock, cobertura y condiciones en Tambo.', 'Comida/bazar'))
    return deals, len(products)


def makro_products(raw):
    from .catalogs import Deal
    products = json.loads(raw)
    if not isinstance(products, list) or not products: raise ValueError('Catálogo Makro vacío o inválido')
    deals = []
    for item in products:
        url = item.get('link', '')
        if urlsplit(url).scheme != 'https' or urlsplit(url).hostname not in ('makro.plazavea.com.pe','www.makro.plazavea.com.pe'): continue
        # El catálogo puede mezclar electro/hogar; esos productos no pertenecen a este tema.
        categories = ' '.join(item.get('categories', [])).lower()
        if any(word in categories for word in ('electro', 'tecnolog', 'muebles')): continue
        for sku in item.get('items', []):
            for seller in sku.get('sellers', []):
                offer = seller.get('commertialOffer', {})
                stock = offer.get('AvailableQuantity')
                if not isinstance(stock, (int, float)) or stock <= 0 or offer.get('IsAvailable') is False: continue
                values = discount(offer.get('Price'), offer.get('ListPrice'))
                if not values: continue
                price, regular, pct = values
                deals.append(Deal('Makro', str(sku['itemId']), sku.get('nameComplete') or item['productName'],
                                  url, pct, price, regular, seller.get('sellerName') or 'Makro',
                                  'Precio por la presentación indicada, no por unidad suelta. Confirmar cantidades mínimas, stock y entrega en Lima.', 'Comida/bazar'))
    return deals, len(products)


def scan_convenience(state, now, http_factory=HttpClient):
    deals, reports = {}, []
    for name, url, parser in [('Tambo', TAMBO, tambo_products), ('Makro', MAKRO, makro_products)]:
        http = http_factory(delay=1.5, timeout=30, max_requests=5)
        count, error = 0, None
        try:
            domain = urlsplit(url).netloc
            robots = http.get('https://'+domain+'/robots.txt')
            if not robots or 'user-agent:' not in robots.lower(): raise ValueError('No se pudo verificar robots.txt')
            rules = RobotFileParser(); rules.parse(robots.splitlines())
            if not rules.can_fetch(http.user_agent, url): raise ValueError('robots.txt restringe el catálogo')
            found, count = parser(http.get(url))
            for deal in found:
                if deal.key not in deals:
                    state.observe(deal, now); deals[deal.key] = deal
        except Exception as exc:
            error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:120]
        reports.append((name, count, error))
    return list(deals.values()), reports

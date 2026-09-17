"""Lectura acotada del catálogo público VTEX; sin carrito ni sesión."""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import json
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .http import HttpClient, Blocked

SOURCES = [("Promart", "www.promart.pe"), ("Oechsle", "www.oechsle.pe"),
           ("Estilos", "www.estilos.com.pe"), ("Casaideas", "www.casaideas.com.pe"),
           ("Shopstar", "www.shopstar.pe")]
PATH = "/api/catalog_system/pub/products/search?O=OrderByBestDiscountDESC&_from=0&_to=49"


def normalized(text):
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def category_of(product):
    roots = {normalized(c.strip('/').split('/')[0]) for c in product.get('categories', [])}
    for words, category in [({'tecnologia'}, 'Tecnología'),
                            ({'electrohogar', 'electrodomesticos'}, 'Electrodomésticos'),
                            ({'muebles', 'muebles y organizacion'}, 'Muebles'),
                            ({'hogar', 'decohogar', 'deco hogar', 'decohogar menaje',
                              'dormitorio', 'cocina', 'comedor', 'living y sala de estar',
                              'jardin', 'jardin y terraza', 'terrazas', 'jardineria'}, 'Hogar')]:
        if roots & words: return category
    return None


def parse_products(raw, source, domain):
    from .catalogs import Deal
    products = json.loads(raw)
    if not isinstance(products, list): raise ValueError('El catálogo no es una lista VTEX')
    deals = []
    for product in products:
        if not isinstance(product, dict): raise ValueError('Ficha VTEX inválida')
        category = category_of(product)
        url = str(product.get('link') or '')
        parsed = urlsplit(url)
        if not category or parsed.scheme != 'https' or parsed.hostname != domain: continue
        for item in product.get('items', []):
            name = str(item.get('nameComplete') or product.get('productName') or '').strip()
            variant = str(item.get('name') or '').strip()
            if variant and normalized(variant) not in normalized(name): name += ' · ' + variant
            if not name: continue
            for seller in item.get('sellers', []):
                offer = seller.get('commertialOffer', {})
                try:
                    price = Decimal(str(offer.get('Price')))
                    regular = Decimal(str(offer.get('ListPrice')))
                    stock = Decimal(str(offer.get('AvailableQuantity')))
                    if not all(n.is_finite() for n in (price, regular, stock)): continue
                    if price < 10 or regular <= price or stock <= 0 or offer.get('IsAvailable') is False: continue
                    pct = int(((1 - price / regular) * 100).to_integral_value(rounding=ROUND_FLOOR))
                except (InvalidOperation, ValueError, TypeError): continue
                # Referencias extremas requieren verificación adicional; no producir alarmas engañosas.
                if not 60 <= pct < 95: continue
                deals.append(Deal(source, normalized(name), name, url, pct, float(price),
                                  float(regular), str(seller.get('sellerName') or source),
                                  'Precio publicado; confirmar stock y envío en Lima', category))
    return deals, len(products)


def scan_vtex(state, now, http_factory=HttpClient, sources=None):
    deals, reports = {}, []
    for source, domain in (SOURCES if sources is None else sources):
        client = http_factory(delay=1.5, timeout=20, max_requests=4)
        count, error = 0, None
        try:
            base = 'https://' + domain
            robots = client.get(base + '/robots.txt')
            if not robots or 'user-agent:' not in robots.lower():
                raise ValueError('No se pudo verificar robots.txt')
            rules = RobotFileParser(); rules.parse(robots.splitlines())
            if not rules.can_fetch(client.user_agent, base + PATH):
                raise ValueError('robots.txt no permite consultar el catálogo')
            found, count = parse_products(client.get(base + PATH), source, domain)
            for deal in found:
                # Un marketplace compartido no genera avisos repetidos por tienda.
                if deal.key not in deals:
                    state.observe(deal, now)
                    deals[deal.key] = deal
        except Exception as exc:
            error = 'acceso bloqueado; no se insiste' if isinstance(exc, Blocked) else type(exc).__name__ + ': ' + str(exc)[:120]
        reports.append((source, count, error))
    return list(deals.values()), reports


def scan_home(state, now):
    from .catalogs import scan_retail
    old, reports = scan_retail(state, now)
    new, extra = scan_vtex(state, now)
    return old + new, reports + extra

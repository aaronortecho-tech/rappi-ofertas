"""Lectura de los datos de Rappi.

Todo aquí es "puro": recibe HTML o JSON y devuelve datos, sin hacer
consultas. Así se puede probar con copias guardadas de páginas reales.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Iterator

from .models import Candidate, Offer

_NEXT_DATA_RE = re.compile(
    r'<script[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.S | re.I
)
_PCT_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_STORE_LINK_RE = re.compile(r'href="(?:https://www\.rappi\.com\.pe)?/tiendas/(\d+)-([^"/?#\s]+)(?:[?#][^"]*)?"')
_RESTAURANT_LINK_RE = re.compile(
    r'href="(?:https://www\.rappi\.com\.pe)?/restaurantes/(\d+)-([^"/?#\s]+)(?:[?#][^"]*)?"'
)
_FRIENDLY_URL_RE = re.compile(r"/restaurantes/(\d+)-([^/?#\s]+)")

# Etiquetas de descuento que no son un porcentaje sobre productos.
_IGNORED_TAG_TYPES = {"free_shipping", "value", "cashback"}


def extract_next_data(html: str | None) -> dict | None:
    """Devuelve el JSON que Next.js incrusta en cada página de Rappi."""
    if not html:
        return None
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _page_props(next_data: dict | None) -> dict:
    if not isinstance(next_data, dict):
        return {}
    props = next_data.get("props")
    if not isinstance(props, dict):
        return {}
    page_props = props.get("pageProps")
    return page_props if isinstance(page_props, dict) else {}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def discount_pct(price: float | None, regular: float | None) -> int:
    """Porcentaje de descuento redondeado como lo muestra Rappi (0 si no hay)."""
    if price is None or regular is None or regular <= 0 or price < 0 or price >= regular:
        return 0
    return _round_half_up((1 - price / regular) * 100)


def iter_dicts(root: Any, max_depth: int = 40) -> Iterator[dict]:
    """Recorre todos los diccionarios anidados (sin recursión)."""
    stack: list[tuple[Any, int]] = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > max_depth:
            continue
        if isinstance(node, dict):
            yield node
            stack.extend((value, depth + 1) for value in reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend((value, depth + 1) for value in reversed(node))


def _keep_best(offers: dict[str, Offer], offer: Offer) -> None:
    current = offers.get(offer.product_id)
    if current is None or offer.pct > current.pct:
        offers[offer.product_id] = offer


def _clean_name(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


# --------------------------------------------------------------------------
# Tiendas (supermercados, farmacias, licorerías…)
# --------------------------------------------------------------------------

def parse_store_page(next_data: dict | None) -> tuple[str | None, list[Offer]]:
    """Productos de una página de tienda (por ejemplo /tiendas/62365-wong/ofertas)."""
    page_props = _page_props(next_data)
    store_name = page_props.get("storeName")
    context = page_props.get("storeContext")
    if not store_name and isinstance(context, dict):
        store_name = context.get("name")

    offers: dict[str, Offer] = {}
    for node in iter_dicts(page_props):
        if not {"real_price", "price", "name", "id"} <= node.keys():
            continue
        price = _num(node.get("price"))
        regular = _num(node.get("real_price"))
        pct = discount_pct(price, regular)
        if pct == 0:
            continue
        product_id = str(node.get("product_id") or node.get("id"))
        _keep_best(
            offers,
            Offer(
                product_id=product_id,
                name=_clean_name(node.get("name")),
                price=price,
                regular_price=regular,
                pct=pct,
                available=node.get("in_stock") is not False,
            ),
        )
    return (_clean_name(store_name) or None), list(offers.values())


def store_links(html: str | None) -> list[tuple[int, str]]:
    """Tiendas enlazadas desde una página como /tiendas/tipo/market."""
    seen: dict[int, str] = {}
    for store_id, slug in _STORE_LINK_RE.findall(html or ""):
        seen.setdefault(int(store_id), slug)
    return list(seen.items())


# --------------------------------------------------------------------------
# Restaurantes
# --------------------------------------------------------------------------

def parse_restaurant_page(next_data: dict | None) -> tuple[dict, list[Offer]]:
    """Menú de la página pública de un restaurante (/restaurantes/<id>-<nombre>)."""
    page_props = _page_props(next_data)
    store = None
    fallback = page_props.get("fallback")
    if isinstance(fallback, dict):
        for value in fallback.values():
            if isinstance(value, dict) and isinstance(value.get("corridors"), list):
                store = value
                break
    if store is None:
        for node in iter_dicts(page_props):
            if isinstance(node.get("corridors"), list) and "name" in node:
                store = node
                break
    if store is None:
        return {}, []

    info = {
        "id": store.get("id"),
        "name": _clean_name(store.get("name")),
        "status": store.get("status"),
        "available": store.get("isCurrentlyAvailable"),
    }
    offers: dict[str, Offer] = {}
    for corridor in store["corridors"]:
        if not isinstance(corridor, dict):
            continue
        for product in corridor.get("products") or []:
            if not isinstance(product, dict):
                continue
            price = _num(product.get("price"))
            regular = _num(product.get("realPrice"))
            pct = discount_pct(price, regular)
            pro_only = bool(product.get("isDiscountPrimeExclusive"))
            if pct == 0:
                listed = _num(product.get("discountInPercent")) or 0
                if listed <= 0 or listed > 100:
                    continue
                # El descuento existe pero el precio mostrado no lo refleja
                # (suele pasar con descuentos exclusivos de Rappi Pro).
                pct = _round_half_up(listed)
                regular = price
                price = round(price * (1 - pct / 100), 2) if price is not None else None
            _keep_best(
                offers,
                Offer(
                    product_id=str(product.get("id")),
                    name=_clean_name(product.get("name")),
                    price=price,
                    regular_price=regular,
                    pct=pct,
                    available=product.get("isAvailable") is not False,
                    pro_only=pro_only,
                ),
            )
    return info, list(offers.values())


def parse_restaurant_live(data: Any, include_pro: bool) -> tuple[dict, list[Offer]]:
    """Menú en vivo de un restaurante (respuesta de restaurants-bus/store/id/<id>/)."""
    if not isinstance(data, dict):
        return {}, []
    info = {
        "id": data.get("store_id"),
        "name": _clean_name(data.get("name")),
        "status": data.get("status"),
        "available": data.get("is_currently_available"),
    }
    offers: dict[str, Offer] = {}
    for corridor in data.get("corridors") or []:
        if not isinstance(corridor, dict):
            continue
        for product in corridor.get("products") or []:
            if not isinstance(product, dict):
                continue
            regular = _num(product.get("real_price"))
            discounts = product.get("discounts")
            best: tuple[int, float | None, bool, bool] | None = None
            for discount in discounts or []:
                if not isinstance(discount, dict):
                    continue
                pro_only = bool(discount.get("is_prime_exclusive"))
                if pro_only and not include_pro:
                    continue
                if not pro_only and discount.get("apply_to_user") is False:
                    continue
                price = _num(discount.get("price"))
                pct = discount_pct(price, regular) if price is not None else 0
                if pct == 0 and discount.get("type") in (None, "global_offer", "percentage"):
                    value = _num(discount.get("value")) or 0
                    if 0 < value < 100 and regular:
                        pct = _round_half_up(value)
                        price = round(regular * (1 - pct / 100), 2)
                if pct <= 0:
                    continue
                candidate = (pct, price, pro_only, bool(discount.get("is_viral_deal")))
                if best is None or pct > best[0]:
                    best = candidate
            if best is None and not discounts:
                # Algunos productos solo traen el porcentaje (sin detalle que
                # diga si es exclusivo de Rappi Pro).
                listed = _num(product.get("discount_percentage")) or 0
                base = _num(product.get("price"))
                if 0 < listed < 100 and regular:
                    reduced = discount_pct(base, regular)
                    pct = reduced or _round_half_up(listed)
                    price = base if reduced else round(regular * (1 - pct / 100), 2)
                    best = (pct, price, False, False)
            if best is None:
                continue
            pct, price, pro_only, viral = best
            product_id = str(product.get("product_id") or product.get("id"))
            _keep_best(
                offers,
                Offer(
                    product_id=product_id,
                    name=_clean_name(product.get("name")),
                    price=price,
                    regular_price=regular,
                    pct=pct,
                    available=product.get("in_schedule") is not False,
                    pro_only=pro_only,
                    viral=viral,
                ),
            )
    return info, list(offers.values())


def _tag_pct(tag: dict) -> int | None:
    match = _PCT_RE.search(str(tag.get("tag") or ""))
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return _round_half_up(value) if 0 < value <= 100 else None


def _slug(store: dict) -> str:
    friendly = store.get("friendly_url")
    if isinstance(friendly, dict):
        friendly = friendly.get("friendly_url")
    if isinstance(friendly, str) and friendly:
        match = _FRIENDLY_URL_RE.search(friendly)
        return match.group(2) if match else friendly.strip("/")
    return "restaurante"


def restaurant_candidates(
    stores: Any,
    min_discount: int,
    include_pro: bool,
    max_distance_km: float | None = None,
) -> list[Candidate]:
    """Restaurantes de la lista "Promos" que anuncian un descuento >= mínimo."""
    result: list[Candidate] = []
    if not isinstance(stores, list):
        return result
    for store in stores:
        if not isinstance(store, dict):
            continue
        store_id = store.get("store_id")
        if not isinstance(store_id, int):
            continue
        if store.get("status") not in (None, "OPEN"):
            continue
        if store.get("is_currently_available") is False:
            continue
        distance = _num(store.get("distance_v2"))
        distance_km = round(distance / 1000, 1) if distance is not None else None
        if max_distance_km and distance_km is not None and distance_km > max_distance_km:
            continue

        candidate = Candidate(
            store_id=store_id,
            slug=_slug(store),
            name=_clean_name(store.get("name") or store.get("brand_name")),
            distance_km=distance_km,
        )
        for tag in store.get("discount_tags") or []:
            if not isinstance(tag, dict) or tag.get("type") in _IGNORED_TAG_TYPES:
                continue
            if tag.get("is_prime_exclusive") and not include_pro:
                continue
            pct = _tag_pct(tag)
            if pct is None:
                continue  # 2x1 y promociones sin porcentaje
            text = _clean_name(tag.get("tag"))
            if tag.get("is_prime_exclusive"):
                text += " (Rappi Pro)"
            if tag.get("type") == "percentage":
                if pct > candidate.store_wide_pct:
                    candidate.store_wide_pct, candidate.store_wide_text = pct, text
            elif pct > candidate.product_pct:
                candidate.product_pct, candidate.product_tag = pct, text
        if candidate.best_pct >= min_discount:
            result.append(candidate)

    result.sort(key=lambda c: (-c.best_pct, c.distance_km if c.distance_km is not None else 999))
    return result


def chain_restaurants(html: str | None) -> list[tuple[int, str]]:
    """Locales de una cadena (/lima/restaurantes/delivery/<id>-<cadena>)."""
    found: dict[int, str] = {}
    brand = _page_props(extract_next_data(html)).get("brand")
    if isinstance(brand, dict):
        for store in brand.get("stores") or []:
            if not isinstance(store, dict):
                continue
            match = _FRIENDLY_URL_RE.search(str(store.get("friendlyUrl") or ""))
            if match:
                found.setdefault(int(match.group(1)), match.group(2))
            elif isinstance(store.get("storeId"), int):
                found.setdefault(store["storeId"], "restaurante")
    if not found:
        for store_id, slug in _RESTAURANT_LINK_RE.findall(html or ""):
            found.setdefault(int(store_id), slug)
    return list(found.items())

"""Revisión de restaurantes, tiendas y cadenas."""

from __future__ import annotations

import logging
import math
import time
from typing import Callable, Protocol

from .config import Config
from .http import Blocked, BudgetExceeded
from .models import Alert, Offer, ScanResult
from .parsers import (
    chain_restaurants,
    extract_next_data,
    parse_restaurant_live,
    parse_restaurant_page,
    parse_store_page,
    restaurant_candidates,
    store_links,
    store_home_paths,
)
from .state import State


class Browser(Protocol):
    def promo_restaurants(self) -> list[dict]: ...

    def restaurant_menu(self, store_id: int) -> dict | None: ...


def good_offers(offers: list[Offer], cfg: Config) -> list[Offer]:
    result = [
        offer
        for offer in offers
        if offer.pct >= cfg.min_discount
        and offer.available
        and (cfg.rappi_pro or not offer.pro_only)
    ]
    return sorted(result, key=lambda offer: (-offer.pct, offer.name))


class Deadline:
    """Límite de tiempo para una sección, para que una ronda nunca se alargue demasiado."""

    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + seconds

    def expired(self) -> bool:
        return self._clock() >= self._end


def _error_text(exc: BaseException) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text[:200]


# --------------------------------------------------------------------------
# Restaurantes (lista "Promos" con navegador oculto)
# --------------------------------------------------------------------------

def scan_restaurants(
    cfg: Config,
    browser_factory: Callable[[], object],
    http,
    log: logging.Logger,
    deadline: Deadline | None = None,
) -> ScanResult:
    result = ScanResult("restaurantes")
    deadline = deadline or Deadline(cfg.restaurant_budget_s)
    try:
        with browser_factory() as browser:  # type: ignore[attr-defined]
            stores = browser.promo_restaurants()
            candidates = restaurant_candidates(
                stores, cfg.min_discount, cfg.rappi_pro, cfg.max_distance_km
            )
            result.notes.append(
                f"{len(stores)} restaurantes con promo; {len(candidates)} anuncian -{cfg.min_discount}% o más"
            )
            if len(candidates) > cfg.max_candidates:
                result.notes.append(f"se revisan los {cfg.max_candidates} con mayor descuento")
            for number, candidate in enumerate(candidates[: cfg.max_candidates]):
                if deadline.expired():
                    result.notes.append("se acabó el tiempo; el resto se revisa en la próxima ronda")
                    break
                if number and cfg.request_delay > 0:
                    time.sleep(cfg.request_delay)  # consultas espaciadas también en el navegador
                alert = _check_restaurant(cfg, browser, http, candidate, result, log)
                if alert is not None:
                    result.alerts.append(alert)
            result.checked = len(stores)
    except Exception as exc:  # noqa: BLE001 - se informa y se sigue con las tiendas
        result.error = _error_text(exc)
        result.blocked = isinstance(exc, Blocked)
        log.debug("Detalle del error en restaurantes", exc_info=True)
    return result


def _check_restaurant(cfg, browser, http, candidate, result: ScanResult, log) -> Alert | None:
    url = f"{cfg.base_url}/restaurantes/{candidate.store_id}-{candidate.slug}"
    offers: list[Offer] = []
    menu = None
    try:
        menu = browser.restaurant_menu(candidate.store_id)
    except (Blocked, BudgetExceeded):
        raise
    except Exception as exc:  # noqa: BLE001
        log.debug("Menú en vivo no disponible para %s: %s", candidate.store_id, exc)
    if menu is not None:
        _, offers = parse_restaurant_live(menu, cfg.rappi_pro)
    else:
        try:
            html = http.get(url)
            _, offers = parse_restaurant_page(extract_next_data(html))
        except (Blocked, BudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo leer la página de %s: %s", candidate.store_id, exc)
    result.remember_top(offers, candidate.name)

    alert = Alert(
        kind="restaurante",
        store_id=str(candidate.store_id),
        store_name=candidate.name,
        url=url,
        offers=good_offers(offers, cfg),
        distance_km=candidate.distance_km,
    )
    if candidate.store_wide_pct >= cfg.min_discount:
        alert.store_wide_text = candidate.store_wide_text
        alert.store_wide_pct = candidate.store_wide_pct
    if not alert.offers and candidate.product_pct >= cfg.min_discount:
        alert.announced_text = candidate.product_tag
        alert.announced_pct = candidate.product_pct
    return None if alert.is_empty() else alert


# --------------------------------------------------------------------------
# Tiendas (supermercados, farmacias, licorerías…)
# --------------------------------------------------------------------------

def load_store_list(cfg: Config, http, state: State, now: float, log) -> list[tuple[int, str]]:
    cached = state.cached_stores(now)
    sources = {"city": cfg.city, "types": cfg.store_types, "market": cfg.check_market}
    if cached and state.store_list.get("sources") == sources:
        return cached
    found: dict[int, str] = {}
    for store_type in cfg.store_types:
        try:
            html = http.get(f"{cfg.base_url}/tiendas/tipo/{store_type}")
        except (Blocked, BudgetExceeded):
            raise
        except Exception as exc:  # noqa: BLE001 - se sigue con los demás tipos
            log.info("No se pudo leer el tipo de tienda %s: %s", store_type, exc)
            continue
        links = store_links(html)
        log.debug("Tipo %s: %d tiendas", store_type, len(links))
        for store_id, slug in links:
            found.setdefault(store_id, slug)
    if cfg.check_market:
        # El directorio general omite algunos locales de Turbo/Market.
        # La ruta por ciudad evita incorporar sucursales de otras ciudades.
        html = http.get(f"{cfg.base_url}/{cfg.city}/tiendas/marca-turbo")
        branches = store_links(html)
        if not branches:
            raise RuntimeError("no se pudo leer el directorio de Rappi Market/Turbo")
        for store_id, slug in branches:
            found.setdefault(store_id, slug)
    stores = sorted(found.items())
    if stores:
        state.set_stores(stores, now)
        state.store_list["sources"] = sources
    return stores


def store_batch(stores: list, size: int, now: float, every_minutes: int) -> tuple[list, int, int]:
    """Parte de la lista que toca revisar en esta ronda (rota con la hora)."""
    if not stores:
        return [], 0, 0
    total_batches = max(1, math.ceil(len(stores) / size))
    index = int(now // (every_minutes * 60)) % total_batches
    start = index * size
    return stores[start : start + size], index + 1, total_batches


def scan_stores(cfg: Config, http, state: State, now: float, log: logging.Logger,
                deadline: Deadline | None = None) -> ScanResult:
    result = ScanResult("tiendas")
    deadline = deadline or Deadline(cfg.store_budget_s)
    try:
        stores = load_store_list(cfg, http, state, now, log)
        if not stores:
            raise RuntimeError("no se encontraron tiendas en rappi.com.pe/tiendas/tipo/…")
        batch, number, total = store_batch(stores, cfg.store_batch, now, cfg.run_every_minutes)
        result.notes.append(f"{len(stores)} tiendas en total; grupo {number} de {total}")
        read_ok = attempted = market_checked = home_checked = home_failed = 0
        for store_id, slug in batch:
            if deadline.expired():
                result.notes.append("se acabó el tiempo; el resto se revisa en la próxima ronda")
                break
            url = f"{cfg.base_url}/tiendas/{store_id}-{slug}"
            attempted += 1
            try:
                html = http.get(f"{url}/ofertas")
            except (Blocked, BudgetExceeded):
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("No se pudo leer la tienda %s: %s", store_id, exc)
                continue
            data = extract_next_data(html)
            if data is None:
                continue
            read_ok += 1
            name, offers = parse_store_page(data)
            store_name = name or slug.replace("-", " ").title()
            is_market = any(word in f"{slug} {store_name}".lower()
                            for word in ("turbo", "rappi-market", "rappi market"))
            if cfg.check_market and is_market:
                market_checked += 1
                merged = {offer.product_id: offer for offer in offers}
                for path in store_home_paths(html, store_id):
                    if deadline.expired():
                        home_failed += 1
                        break
                    try:
                        extra = extract_next_data(http.get(f"{cfg.base_url}{path}"))
                        if extra is None:
                            home_failed += 1
                            continue
                        _, extra_offers = parse_store_page(extra)
                        home_checked += 1
                        for offer in extra_offers:
                            previous = merged.get(offer.product_id)
                            if previous is None or offer.pct > previous.pct:
                                merged[offer.product_id] = offer
                    except (Blocked, BudgetExceeded):
                        raise
                    except Exception:  # un pasillo fallido no descarta las demás ofertas
                        home_failed += 1
                offers = list(merged.values())
            result.remember_top(offers, store_name)
            best = good_offers(offers, cfg)
            if best:
                result.alerts.append(
                    Alert(kind="tienda", store_id=str(store_id), store_name=store_name, url=url, offers=best)
                )
        result.checked = read_ok
        if cfg.check_market:
            result.notes.append(f"Rappi Market/Turbo: {market_checked} locales y "
                                f"{home_checked} pasillos de hogar/bazar revisados en este grupo")
        if home_failed:
            result.error = f"no se pudieron revisar {home_failed} pasillos de hogar/bazar"
        if attempted and read_ok == 0:
            raise RuntimeError("no se pudo leer ninguna tienda del grupo")
    except Exception as exc:  # noqa: BLE001
        result.error = _error_text(exc)
        result.blocked = isinstance(exc, Blocked)
        log.debug("Detalle del error en tiendas", exc_info=True)
    return result


# --------------------------------------------------------------------------
# Cadenas conocidas (respaldo si falla la lista de restaurantes)
# --------------------------------------------------------------------------

def _scan_chain(cfg: Config, http, chain: str, result: ScanResult) -> None:
    chain_url = f"{cfg.base_url}/{cfg.city}/restaurantes/delivery/{chain}"
    html = http.get(chain_url)
    branches = chain_restaurants(html)[: cfg.branches_per_chain]
    best: dict[str, Offer] = {}
    chain_name = chain.split("-", 1)[-1].replace("-", " ").title()
    for store_id, slug in branches:
        page = http.get(f"{cfg.base_url}/restaurantes/{store_id}-{slug}")
        info, offers = parse_restaurant_page(extract_next_data(page))
        if info:
            result.checked += 1
        result.remember_top(offers, info.get("name") or chain_name)
        for offer in good_offers(offers, cfg):
            key = offer.name.lower()
            if key not in best or offer.pct > best[key].pct:
                best[key] = offer
    if best:
        result.alerts.append(
            Alert(
                kind="cadena",
                store_id=f"cadena-{chain.split('-', 1)[0]}",
                store_name=chain_name,
                url=chain_url,
                offers=sorted(best.values(), key=lambda offer: -offer.pct),
            )
        )


def scan_chains(cfg: Config, http, log: logging.Logger) -> ScanResult:
    result = ScanResult("cadenas")
    last_error: Exception | None = None
    try:
        for chain in cfg.chains:
            try:
                _scan_chain(cfg, http, chain, result)
            except (Blocked, BudgetExceeded):
                raise
            except Exception as exc:  # noqa: BLE001 - se sigue con las demás cadenas
                last_error = exc
                log.debug("No se pudo revisar la cadena %s: %s", chain, exc)
        if result.checked == 0 and cfg.chains:
            raise last_error or RuntimeError("no se pudo leer ningún local de las cadenas")
    except Exception as exc:  # noqa: BLE001
        result.error = _error_text(exc)
        result.blocked = isinstance(exc, Blocked)
        log.debug("Detalle del error en cadenas", exc_info=True)
    return result

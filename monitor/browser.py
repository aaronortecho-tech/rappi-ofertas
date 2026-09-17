"""Navegador oculto (Playwright) para la lista de restaurantes con "Promos".

La web de Rappi arma esa lista desde el navegador, así que se abre
/restaurantes con tu ubicación, se activa el filtro "Promos" y se aprovecha
esa misma sesión para pedir:

* la lista completa de restaurantes con descuento en productos, y
* el menú actualizado de los restaurantes que anuncian el descuento mínimo.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import urllib.parse
from typing import Any

from .config import Config
from .http import USER_AGENT, Blocked

PROMOS_CHECKBOX = "#popular_filters-Promos"
FILTERS_PATH = "/restaurants-bus/stores/filters"
_FILTERS_RE = re.compile(r"restaurants-bus/stores/filters/?(?=$|\?)")
_REWRITE_RE = re.compile(r"/restaurants-bus/")
_FORBIDDEN_HEADER_RE = re.compile(
    r"^(host|content-length|cookie|user-agent|referer|origin|connection|accept-encoding)$|^sec-|^:",
    re.I,
)

_POST_JS = """async ({url, headers, body, timeoutMs}) => {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      method: 'POST', headers, body: JSON.stringify(body), signal: controller.signal,
    });
    return {status: response.status, text: await response.text()};
  } catch (error) {
    return {status: 0, text: String(error)};
  } finally {
    clearTimeout(timer);
  }
}"""

_CLICK_JS = """(selector) => {
  const element = document.querySelector(selector);
  if (!element) return 'missing';
  if (!element.checked) element.click();
  return 'ok';
}"""


class BrowserError(RuntimeError):
    """No se pudo obtener la lista de restaurantes con promo."""


def location_cookie_value(lat: float, lng: float) -> str:
    """Valor de la cookie `currentLocation` que la web de Rappi usa para tu dirección."""
    data = {
        "id": 1,
        "city": "Lima",
        "url": "lima",
        "lat": lat,
        "lng": lng,
        "country": "PE",
        "autoLocation": False,
        "address": "Mi ubicación",
        "active": True,
        "isInitialLocation": False,
    }
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    encoded = urllib.parse.quote(text, safe="-_.!~*'()")
    return base64.b64encode(encoded.encode("ascii")).decode("ascii")


def _same_type(original: Any, value: float) -> Any:
    return str(value) if isinstance(original, str) else value


def rewrite_location(body: str | None, lat: float, lng: float) -> str | None:
    """Fuerza tu ubicación en el cuerpo JSON de una consulta, si trae lat/lng."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    changed = False
    targets = [data]
    if isinstance(data, dict) and isinstance(data.get("state"), dict):
        targets.append(data["state"])
    for target in targets:
        if isinstance(target, dict) and "lat" in target and "lng" in target:
            target["lat"] = _same_type(target["lat"], lat)
            target["lng"] = _same_type(target["lng"], lng)
            changed = True
    return json.dumps(data) if changed else None


class RappiBrowser:
    def __init__(self, cfg: Config, log: logging.Logger | None = None, wait_ms: int = 45_000) -> None:
        self.cfg = cfg
        self.log = log or logging.getLogger("monitor")
        self.wait_ms = wait_ms
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._api: dict | None = None
        self._last_post: float | None = None
        self._blocked = False

    def _check_status(self, status):
        if self._blocked or status in (403, 429):
            self._blocked = True
            raise Blocked("Rappi limitó el acceso (403/429); se detiene esta ronda")

    # ------------------------------------------------------------------
    def __enter__(self) -> "RappiBrowser":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise BrowserError("Playwright no está instalado (pip install -r requirements.txt)") from exc
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(headless=self.cfg.headless)
            self._context = self._browser.new_context(
                locale="es-PE",
                timezone_id="America/Lima",
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            host = urllib.parse.urlparse(self.cfg.base_url).hostname or "www.rappi.com.pe"
            self._context.add_cookies(
                [
                    {
                        "name": "currentLocation",
                        "value": location_cookie_value(self.cfg.lat, self.cfg.lng),
                        "domain": host,
                        "path": "/",
                    }
                ]
            )
            self._page = self._context.new_page()
            self._page.set_default_timeout(self.wait_ms)
            self._page.route(_REWRITE_RE, self._force_location)
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc_info) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001 - al cerrar no importa el error
                pass
        try:
            if self._playwright is not None:
                self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        self._playwright = self._browser = self._context = self._page = None

    # ------------------------------------------------------------------
    def _force_location(self, route, request) -> None:
        if request.method == "POST":
            body = rewrite_location(request.post_data, self.cfg.lat, self.cfg.lng)
            if body is not None:
                route.continue_(post_data=body)
                return
        route.continue_()

    def _post(self, url: str, payload: dict) -> Any:
        self._check_status(None)
        if self._last_post is not None:
            time.sleep(max(0, self.cfg.request_delay - (time.monotonic() - self._last_post)))
        self._last_post = time.monotonic()
        assert self._page is not None and self._api is not None
        result = self._page.evaluate(
            _POST_JS,
            {"url": url, "headers": self._api["headers"], "body": payload, "timeoutMs": 30_000},
        )
        status = result.get("status") if isinstance(result, dict) else None
        self._check_status(status)
        if status != 200:
            level = logging.DEBUG if status == 404 else logging.INFO
            self.log.log(level, "Consulta a Rappi sin éxito (estado %s)", status)
            return None
        try:
            return json.loads(result.get("text") or "")
        except ValueError:
            return None

    # ------------------------------------------------------------------
    def promo_restaurants(self) -> list[dict]:
        """Restaurantes con descuentos cerca de tu ubicación."""
        page = self._page
        if page is None:
            raise BrowserError("el navegador no está abierto")
        navigation = page.goto(f"{self.cfg.base_url}/restaurantes", wait_until="domcontentloaded",
                  timeout=max(self.wait_ms, 60_000))
        self._check_status(navigation.status if navigation else None)
        try:
            page.wait_for_selector(PROMOS_CHECKBOX, state="attached", timeout=self.wait_ms)
        except Exception as exc:
            raise BrowserError(
                "no apareció el filtro 'Promos' en rappi.com.pe/restaurantes "
                "(la web pudo cambiar o no cargó)"
            ) from exc
        try:
            # Deja que la web termine de cargar la lista de locales antes de filtrar.
            page.wait_for_load_state("networkidle", timeout=min(self.wait_ms, 15_000))
        except Exception:  # noqa: BLE001 - la analítica puede mantener la red ocupada
            pass

        def is_filters(response) -> bool:
            return FILTERS_PATH in response.url and response.request.method == "POST"

        with page.expect_response(is_filters, timeout=self.wait_ms) as info:
            if page.evaluate(_CLICK_JS, PROMOS_CHECKBOX) != "ok":
                raise BrowserError("no se pudo activar el filtro 'Promos'")
        response = info.value
        self._check_status(response.status)
        self._last_post = time.monotonic()
        request = response.request
        try:
            body = json.loads(request.post_data or "{}")
        except ValueError:
            body = {}
        headers = {
            name: value
            for name, value in request.all_headers().items()
            if not _FORBIDDEN_HEADER_RE.search(name)
        }
        self._api = {"url": request.url, "headers": headers, "body": body}

        ui_list: list[dict] = []
        if response.ok:
            try:
                data = response.json()
                if isinstance(data, list):
                    ui_list = [item for item in data if isinstance(item, dict)]
            except Exception:  # noqa: BLE001
                ui_list = []

        # La lista de la web se corta en 350 locales. Pidiendo solo los que
        # tienen descuento en productos (y aparte los de % en toda la carta)
        # se obtiene la lista completa.
        stores: dict[Any, dict] = {}
        complete = True
        for types in (["offer_by_product"], ["percentage"]):
            payload = dict(body)
            payload["lat"], payload["lng"] = self.cfg.lat, self.cfg.lng
            payload["filters"] = {"discounts": {"types": types}}
            result = self._post(request.url, payload)
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict):
                        stores[item.get("store_id")] = item
            else:
                complete = False
        if not complete:
            if not response.ok:
                raise BrowserError(f"Rappi respondió {response.status} al pedir la lista de promos")
            if not ui_list and not stores:
                raise BrowserError("Rappi no entregó la lista de restaurantes con promo")
            self.log.info("Se usará también la lista que muestra la web (máx. 350 locales)")
            for item in ui_list:
                stores.setdefault(item.get("store_id"), item)
        return list(stores.values())

    def restaurant_menu(self, store_id: int) -> dict | None:
        """Menú actualizado de un restaurante (o None si no se pudo)."""
        if self._api is None:
            return None
        url, count = _FILTERS_RE.subn(f"restaurants-bus/store/id/{store_id}/", self._api["url"])
        if count != 1:
            return None
        payload = {
            "lat": self.cfg.lat,
            "lng": self.cfg.lng,
            "store_type": "restaurant",
            "is_prime": self.cfg.rappi_pro,
            "prime_config": {"unlimited_shipping": False},
        }
        data = self._post(url, payload)
        if isinstance(data, dict) and isinstance(data.get("corridors"), list):
            return data
        return None

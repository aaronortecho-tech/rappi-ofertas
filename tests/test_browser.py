"""Prueba del navegador oculto contra un servidor local que imita a Rappi."""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import ROOT, fixture_json, fixture_text

from monitor.browser import BrowserError, RappiBrowser, location_cookie_value, rewrite_location
from monitor.config import Config
from monitor.http import Blocked

pytest.importorskip("playwright.sync_api")

PAGE = """<!DOCTYPE html><html><body>
<label for="popular_filters-Promos">Promos</label>
<input type="checkbox" id="popular_filters-Promos">
<script>
document.getElementById('popular_filters-Promos').addEventListener('change', () => {
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/web-gateway/web/restaurants-bus/stores/filters/');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.setRequestHeader('Authorization', 'Bearer token-de-prueba');
  xhr.setRequestHeader('deviceid', 'abc-123');
  xhr.send(JSON.stringify({lat: -12.145395, lng: -77.021936, store_type: 'restaurant',
                           store_ids: [1, 2, 3, 4], filters: {discounts: {types: []}}}));
});
</script></body></html>"""

PAGE_WITHOUT_FILTER = "<!DOCTYPE html><html><body>Sin filtro</body></html>"


def store(store_id, tag, kind="offer_by_product"):
    return {"store_id": store_id, "name": f"Local {store_id}", "status": "OPEN",
            "friendly_url": {"friendly_url": f"local-{store_id}"},
            "discount_tags": [{"type": kind, "tag": tag, "is_prime_exclusive": False}]}


class FakeRappi(BaseHTTPRequestHandler):
    bodies: list = []
    cookies: list = []
    page = PAGE
    typed_fail = False  # las consultas filtradas por tipo responden 500
    blocked_status = None
    ui_stores: list | None = None  # lista que devuelve la consulta de la web

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        html = "text/html; charset=utf-8"
        if self.path == "/restaurantes":
            FakeRappi.cookies.append(self.headers.get("Cookie", ""))
            self._send(200, FakeRappi.page, html)
        elif self.path == "/tiendas/tipo/market":
            self._send(200, fixture_text("tipo_market.html"), html)
        elif self.path == "/tiendas/62365-wong/ofertas":
            self._send(200, fixture_text("store_ofertas_wong.html"), html)
        elif self.path.startswith("/restaurantes/1-"):
            self._send(200, fixture_text("restaurant_ssg_23402.html"), html)
        else:
            self._send(404, "{}", html)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        FakeRappi.bodies.append((self.path, body, self.headers.get("Authorization")))
        if FakeRappi.blocked_status:
            self._send(FakeRappi.blocked_status, "{}")
            return
        if self.headers.get("Authorization") != "Bearer token-de-prueba":
            self._send(401, "{}")
        elif self.path.endswith("/restaurants-bus/stores/filters/"):
            types = body.get("filters", {}).get("discounts", {}).get("types", [])
            if types and FakeRappi.typed_fail:
                self._send(500, "{}")
                return
            if not types and FakeRappi.ui_stores is not None:
                self._send(200, json.dumps(FakeRappi.ui_stores))
                return
            if types == ["offer_by_product"]:
                data = [store(1, "Hasta 70% Off"), store(3, "Hasta 65% Off")]
            elif types == ["percentage"]:
                data = [store(4, "60% Off: mín S/40", kind="percentage")]
            else:
                data = [store(1, "Hasta 70% Off"), store(2, "Envío gratis", kind="free_shipping")]
            self._send(200, json.dumps(data))
        elif self.path.endswith("/restaurants-bus/store/id/23402/"):
            self._send(200, json.dumps(fixture_json("restaurant_live_23402.json")))
        else:
            self._send(404, "{}")


@pytest.fixture
def server():
    FakeRappi.bodies = []
    FakeRappi.cookies = []
    FakeRappi.page = PAGE
    FakeRappi.typed_fail = False
    FakeRappi.blocked_status = None
    FakeRappi.ui_stores = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeRappi)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def browser_cfg(server):
    cfg = Config()
    cfg.base_url = server
    cfg.lat, cfg.lng = -12.0977, -77.0365
    return cfg


def _chromium_available():
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:  # noqa: BLE001
        return False


needs_chromium = pytest.mark.skipif(not _chromium_available(), reason="Chromium de Playwright no instalado")


def test_location_cookie_matches_rappi_format():
    value = location_cookie_value(-12.0977, -77.0365)
    decoded = json.loads(urllib.parse.unquote(base64.b64decode(value).decode("ascii")))
    assert decoded["lat"] == -12.0977 and decoded["lng"] == -77.0365
    assert decoded["address"] == "Mi ubicación" and decoded["autoLocation"] is False
    # Mismo formato que btoa(encodeURIComponent(JSON.stringify(...))) en la web.
    assert base64.b64decode(value).decode("ascii").startswith("%7B%22id%22%3A1%2C")


def test_rewrite_location():
    body = json.dumps({"lat": -12.1, "lng": -77.0, "state": {"lat": "-12.1", "lng": "-77.0"}, "x": 1})
    data = json.loads(rewrite_location(body, -12.5, -76.9))
    assert (data["lat"], data["lng"]) == (-12.5, -76.9)
    assert (data["state"]["lat"], data["state"]["lng"]) == ("-12.5", "-76.9")
    assert rewrite_location(json.dumps({"store_ids": [1]}), 1, 2) is None
    assert rewrite_location("no json", 1, 2) is None
    assert rewrite_location(None, 1, 2) is None


@needs_chromium
def test_promo_list_and_menu_through_browser(browser_cfg):
    with RappiBrowser(browser_cfg, logging.getLogger("test"), wait_ms=10_000) as browser:
        stores = browser.promo_restaurants()
        menu = browser.restaurant_menu(23402)
        missing = browser.restaurant_menu(99999)

    assert sorted(s["store_id"] for s in stores) == [1, 3, 4]
    assert menu["store_id"] == 23402 and len(menu["corridors"]) == 4
    assert missing is None

    # Todas las consultas salieron con tu ubicación y con el permiso de la página.
    assert len(FakeRappi.bodies) == 5
    for path, body, auth in FakeRappi.bodies:
        assert (float(body["lat"]), float(body["lng"])) == (-12.0977, -77.0365), path
        assert auth == "Bearer token-de-prueba"
    first_path, first_body, _ = FakeRappi.bodies[0]
    assert first_path.endswith("/stores/filters/") and first_body["store_ids"] == [1, 2, 3, 4]
    # La cookie de ubicación llegó al cargar la página.
    assert "currentLocation=" + location_cookie_value(-12.0977, -77.0365) in FakeRappi.cookies[0]


@needs_chromium
def test_missing_filter_raises_clear_error(browser_cfg):
    FakeRappi.page = PAGE_WITHOUT_FILTER
    with RappiBrowser(browser_cfg, logging.getLogger("test"), wait_ms=2_000) as browser:
        with pytest.raises(BrowserError, match="no apareció el filtro 'Promos'"):
            browser.promo_restaurants()
        assert browser.restaurant_menu(23402) is None


@needs_chromium
def test_falls_back_to_the_web_list(browser_cfg):
    FakeRappi.typed_fail = True
    with RappiBrowser(browser_cfg, logging.getLogger("test"), wait_ms=10_000) as browser:
        stores = browser.promo_restaurants()
    assert sorted(s["store_id"] for s in stores) == [1, 2]


@needs_chromium
def test_no_promo_list_at_all_is_an_error(browser_cfg):
    FakeRappi.typed_fail = True
    FakeRappi.ui_stores = []
    with RappiBrowser(browser_cfg, logging.getLogger("test"), wait_ms=10_000) as browser:
        with pytest.raises(BrowserError, match="no entregó la lista"):
            browser.promo_restaurants()


@needs_chromium
def test_full_run_against_fake_rappi(server, tmp_path):
    """Ejecuta `python -m monitor` de verdad (HTTP + navegador) sin enviar nada."""
    env = {k: v for k, v in os.environ.items() if "proxy" not in k.lower()}
    env.update({
        "RAPPI_BASE_URL": server,
        "RAPPI_UBICACION": "-12.0977, -77.0365",
        "TIPOS_TIENDA": "market",
        "REVISAR_RAPPI_MARKET": "no",
        "PAUSA_ENTRE_CONSULTAS": "0",
        "NTFY_TOPIC": "",
        "ARCHIVO_MEMORIA": str(tmp_path / "state.json"),
    })
    proc = subprocess.run(
        [sys.executable, "-m", "monitor", "--sin-enviar", "--prueba"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    out = proc.stdout
    assert proc.returncode == 0, out + proc.stderr
    assert "Restaurantes: 3 restaurantes con promo; 3 anuncian -60% o más" in out
    # El local 1 no tiene menú en vivo: se usa su página pública.
    assert "-70% en Local 1" in out and "Gran Dúo Cheesy" in out
    assert "hasta -65% en Local 3" in out and "no vi el producto en la web" in out
    assert "Descuento en toda la carta: 60% Off" in out
    assert "-65% en Wong" in out and "6x Nieto Senetiner" in out
    assert "Prueba del monitor de Rappi" in out
    assert "-12.0977" not in out  # la ubicación no aparece en los registros
    assert not (tmp_path / "state.json").exists()


@needs_chromium
@pytest.mark.parametrize("status", [403, 429])
def test_blocked_promo_request_stops_browser(browser_cfg, status):
    FakeRappi.blocked_status = status
    with RappiBrowser(browser_cfg, wait_ms=5_000) as browser:
        with pytest.raises(Blocked):
            browser.promo_restaurants()
    assert len(FakeRappi.bodies) == 1

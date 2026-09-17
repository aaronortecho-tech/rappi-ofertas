import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))

from monitor.config import Config  # noqa: E402

BASE = "https://www.rappi.com.pe"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def fixture_json(name: str):
    return json.loads(fixture_text(name))


class FakeHttp:
    """Responde con páginas guardadas; lo que no está registrado devuelve None (404)."""

    def __init__(self, pages: dict[str, str] | None = None, errors: dict[str, Exception] | None = None):
        self.pages = pages or {}
        self.errors = errors or {}
        self.calls: list[str] = []
        self.posts: list[tuple[str, dict, dict]] = []
        self.post_status = 200

    def get(self, url: str):
        self.calls.append(url)
        if url in self.errors:
            raise self.errors[url]
        return self.pages.get(url)

    def post_json(self, url, payload, headers=None):
        self.posts.append((url, payload, headers or {}))
        return self.post_status


class FakeBrowser:
    def __init__(self, stores=None, menus=None, error: Exception | None = None):
        self.stores = stores if stores is not None else fixture_json("filters_promos.json")
        self.menus = menus if menus is not None else {23402: fixture_json("restaurant_live_23402.json")}
        self.error = error
        self.menu_calls: list[int] = []
        self.closed = False

    def __enter__(self):
        if self.error:
            raise self.error
        return self

    def __exit__(self, *exc):
        self.closed = True

    def promo_restaurants(self):
        return self.stores

    def restaurant_menu(self, store_id):
        self.menu_calls.append(store_id)
        return self.menus.get(store_id)


@pytest.fixture
def cfg(tmp_path):
    config = Config()
    config.ntfy_topic = "prueba-tema-123"
    config.request_delay = 0
    config.state_path = str(tmp_path / "state.json")
    config.store_types = ["market"]
    config.check_market = False
    config.chains = ["6419-fridays"]
    return config


@pytest.fixture
def store_pages():
    return {
        f"{BASE}/tiendas/tipo/market": fixture_text("tipo_market.html"),
        f"{BASE}/tiendas/62365-wong/ofertas": fixture_text("store_ofertas_wong.html"),
    }

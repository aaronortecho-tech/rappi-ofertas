import io
import urllib.error

import pytest

from monitor import http as http_module
from monitor.http import Blocked, BudgetExceeded, HttpClient, safe_url


def test_safe_url():
    assert safe_url("https://www.rappi.com.pe/restaurantes/14291-mcdonald's-postres") == (
        "https://www.rappi.com.pe/restaurantes/14291-mcdonald's-postres"
    )
    assert safe_url("https://x.pe/tiendas/1-piñata café") == "https://x.pe/tiendas/1-pi%C3%B1ata%20caf%C3%A9"
    assert safe_url("https://x.pe/a%20b?q=1&r=2") == "https://x.pe/a%20b?q=1&r=2"


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status=200, encoding=""):
        super().__init__(body)
        self.status = status
        self.headers = _Headers({"Content-Encoding": encoding, "Content-Type": "text/html; charset=utf-8"})

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Headers(dict):
    def get_content_charset(self):
        return "utf-8"


def make_client(monkeypatch, responses):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(http_module.urllib.request, "urlopen", fake_urlopen)
    client = HttpClient(delay=0, sleep=lambda s: None, max_requests=5)
    return client, calls


def http_error(code):
    return urllib.error.HTTPError("https://x.pe", code, "error", {}, None)


def test_get_decodes_gzip_and_sends_browser_headers(monkeypatch):
    import gzip

    client, calls = make_client(monkeypatch, [FakeResponse(gzip.compress("hola ñ".encode()), encoding="gzip")])
    assert client.get("https://x.pe/tiendas/1-piñata") == "hola ñ"
    assert calls[0].full_url == "https://x.pe/tiendas/1-pi%C3%B1ata"
    assert calls[0].get_header("Accept-language") == "es-PE,es;q=0.9"


def test_get_retries_server_errors_and_returns_none_on_404(monkeypatch):
    client, calls = make_client(monkeypatch, [http_error(502), OSError("reset"), FakeResponse(b"ok"), http_error(404)])
    assert client.get("https://x.pe/a") == "ok"
    assert client.get("https://x.pe/b") is None
    assert len(calls) == 4


def test_block_stops_everything(monkeypatch):
    client, calls = make_client(monkeypatch, [http_error(429)])
    with pytest.raises(Blocked):
        client.get("https://x.pe/a")
    with pytest.raises(Blocked):
        client.get("https://x.pe/b")
    assert len(calls) == 1


def test_request_budget(monkeypatch):
    client, _ = make_client(monkeypatch, [FakeResponse(b"ok") for _ in range(6)])
    for _ in range(5):
        client.get("https://x.pe/a")
    with pytest.raises(BudgetExceeded):
        client.get("https://x.pe/a")


def test_waits_between_requests():
    slept = []
    clock = iter([0.0, 0.2, 1.0])
    client = HttpClient(delay=1.0, sleep=slept.append, clock=lambda: next(clock))
    client._wait_turn()
    client._wait_turn()
    assert slept == [pytest.approx(0.8)]


def test_post_json(monkeypatch):
    client, calls = make_client(monkeypatch, [FakeResponse(b"{}"), http_error(400)])
    assert client.post_json("https://ntfy.sh/", {"topic": "t", "title": "¡Oferta!"}, {"Authorization": "Bearer x"}) == 200
    assert calls[0].data.decode("utf-8") == '{"topic": "t", "title": "¡Oferta!"}'
    assert calls[0].get_header("Authorization") == "Bearer x"
    assert client.post_json("https://ntfy.sh/", {}) == 400

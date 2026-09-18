"""Cliente HTTP sencillo y respetuoso (pausas, reintentos y límite de consultas)."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Callable

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def safe_url(url: str) -> str:
    """Codifica espacios y letras con tilde (algunos enlaces de Rappi las traen)."""
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%-._~")


class Blocked(RuntimeError):
    """Rappi rechazó las consultas (403/429). No se insiste en esta ronda."""


class BudgetExceeded(RuntimeError):
    """Se alcanzó el máximo de consultas permitido por ronda."""


class HttpClient:
    def __init__(
        self,
        delay: float = 1.0,
        timeout: float = 30.0,
        max_requests: int = 400,
        user_agent: str = USER_AGENT,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.delay = delay
        self.timeout = timeout
        self.max_requests = max_requests
        self.user_agent = user_agent
        self.requests_made = 0
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._blocked_reason: str | None = None

    @property
    def blocked(self) -> str | None:
        return self._blocked_reason

    def _wait_turn(self) -> None:
        if self._last_request is not None and self.delay > 0:
            remaining = self.delay - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def get(self, url: str, headers: dict | None = None) -> str | None:
        """Devuelve el HTML de la página, o None si no existe (404)."""
        result = self._fetch(url, headers)
        return None if result is None else result[0].decode(result[1], errors="replace")

    def get_bytes(self, url: str, headers: dict | None = None) -> bytes | None:
        """Igual que get, pero sin decodificar (documentos PDF)."""
        result = self._fetch(url, headers)
        return None if result is None else result[0]

    def _fetch(self, url: str, headers: dict | None = None) -> tuple[bytes, str] | None:
        if self._blocked_reason:
            raise Blocked(self._blocked_reason)
        last_error: Exception | None = None
        for attempt in range(3):
            if self.requests_made >= self.max_requests:
                raise BudgetExceeded(f"se llegó al máximo de {self.max_requests} consultas")
            self._wait_turn()
            self.requests_made += 1
            request = urllib.request.Request(
                safe_url(url),
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "es-PE,es;q=0.9",
                    "Accept-Encoding": "gzip, deflate",
                    **(headers or {}),
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = response.read()
                    encoding = (response.headers.get("Content-Encoding") or "").lower()
                    charset = response.headers.get_content_charset() or "utf-8"
                if encoding == "gzip":
                    body = gzip.decompress(body)
                elif encoding == "deflate":
                    body = zlib.decompress(body)
                return body, charset
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    return None
                if exc.code in (403, 429):
                    self._blocked_reason = f"Rappi respondió {exc.code} (acceso limitado)"
                    raise Blocked(self._blocked_reason) from exc
                last_error = exc
                if exc.code < 500:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
            if attempt < 2:
                self._sleep(3 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def post_json(self, url: str, payload: dict, headers: dict | None = None) -> int:
        """Envía JSON (se usa para ntfy). Devuelve el código HTTP."""
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "monitor-ofertas-rappi/1.0",
                **(headers or {}),
            },
        )
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.status
            except urllib.error.HTTPError as exc:
                if exc.code < 500 and exc.code != 429:
                    return exc.code
                last_error = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_error = exc
            if attempt < 2:
                self._sleep(5 * (attempt + 1))
        if isinstance(last_error, urllib.error.HTTPError):
            return last_error.code
        raise last_error  # type: ignore[misc]

"""Memoria entre ejecuciones (archivo JSON que se guarda en el repositorio).

Guarda solo lo necesario para no repetir avisos. Las claves de las ofertas se
guardan como hashes SHA-256. Esto evita publicar los identificadores en claro,
pero no es cifrado ni garantiza anonimato frente a ofertas conocidas.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

VERSION = 1


def offer_key(*parts: Any) -> str:
    text = "|".join(str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class State:
    def __init__(self, data: dict | None = None, existed: bool = False) -> None:
        data = data if isinstance(data, dict) else {}
        self.existed = existed
        self.started_at: int | None = _int_or_none(data.get("started_at"))
        self.saved_at: int | None = _int_or_none(data.get("saved_at"))
        seen = data.get("seen")
        self.seen: dict[str, int] = (
            {str(k): int(v) for k, v in seen.items() if isinstance(v, (int, float))}
            if isinstance(seen, dict)
            else {}
        )
        failures = data.get("failures")
        self.failures: dict[str, int] = (
            {str(k): int(v) for k, v in failures.items() if isinstance(v, (int, float))}
            if isinstance(failures, dict)
            else {}
        )
        self.last_failure_notice: int | None = _int_or_none(data.get("last_failure_notice"))
        stores = data.get("store_list")
        self.store_list: dict = stores if isinstance(stores, dict) else {}
        self._original = self._serialize(include_saved_at=False)

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | os.PathLike, log: logging.Logger | None = None) -> "State":
        file = Path(path)
        if not file.exists():
            return cls()
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            if log:
                log.warning("No se pudo leer la memoria (%s); se empieza de cero.", exc)
            return cls(existed=True)
        return cls(data, existed=True)

    def _serialize(self, include_saved_at: bool = True) -> dict:
        data: dict[str, Any] = {
            "version": VERSION,
            "started_at": self.started_at,
            "seen": dict(sorted(self.seen.items())),
            "failures": dict(sorted((k, v) for k, v in self.failures.items() if v)),
            "last_failure_notice": self.last_failure_notice,
            "store_list": self.store_list,
        }
        if include_saved_at:
            data["saved_at"] = self.saved_at
        return data

    def changed(self) -> bool:
        return self._serialize(include_saved_at=False) != self._original

    def save(self, path: str | os.PathLike, now: float) -> bool:
        """Escribe el archivo solo si algo cambió."""
        if self.existed and not self.changed():
            return False
        self.saved_at = int(now)
        file = Path(path)
        file.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._serialize(), ensure_ascii=False, indent=1) + "\n"
        fd, tmp = tempfile.mkstemp(dir=file.parent, prefix=".state-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp, file)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        self._original = self._serialize(include_saved_at=False)
        self.existed = True
        return True

    # ------------------------------------------------------------------
    @property
    def first_run(self) -> bool:
        return self.started_at is None

    def mark_started(self, now: float) -> None:
        if self.started_at is None:
            self.started_at = int(now)

    def is_new(self, key: str, now: float, window_hours: float) -> bool:
        last = self.seen.get(key)
        return last is None or now - last >= window_hours * 3600

    def mark_seen(self, key: str, now: float) -> None:
        self.seen[key] = int(now)

    def prune(self, now: float, keep_hours: float) -> None:
        limit = now - keep_hours * 3600
        self.seen = {k: v for k, v in self.seen.items() if v >= limit}

    def record_result(self, section: str, ok: bool) -> int:
        """Actualiza el contador de fallas seguidas y lo devuelve."""
        if ok:
            self.failures.pop(section, None)
            return 0
        self.failures[section] = self.failures.get(section, 0) + 1
        return self.failures[section]

    def can_notify_failure(self, now: float, cooldown_hours: float = 24) -> bool:
        last = self.last_failure_notice
        return last is None or now - last >= cooldown_hours * 3600

    def cached_stores(self, now: float, max_age_hours: float = 24) -> list[tuple[int, str]] | None:
        fetched = self.store_list.get("fetched_at")
        stores = self.store_list.get("stores")
        if not isinstance(fetched, (int, float)) or not isinstance(stores, list):
            return None
        if now - fetched >= max_age_hours * 3600:
            return None
        result = []
        for item in stores:
            if isinstance(item, list) and len(item) == 2 and isinstance(item[0], int):
                result.append((item[0], str(item[1])))
        return result or None

    def set_stores(self, stores: list[tuple[int, str]], now: float) -> None:
        self.store_list = {"fetched_at": int(now), "stores": [[sid, slug] for sid, slug in stores]}


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

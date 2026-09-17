"""Configuración del monitor, leída de variables de entorno.

Todas las variables son opcionales salvo NTFY_TOPIC (necesaria para enviar
alertas). Un valor vacío cuenta como "no definido", así que en GitHub Actions
se pueden dejar variables sin crear.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Mapping

# Punto que Rappi usa por defecto para Lima (zona Barranco/Miraflores).
DEFAULT_LAT = -12.145395
DEFAULT_LNG = -77.021936

DEFAULT_STORE_TYPES = ["market", "farmacia", "express-big", "licores", "rappimall-parent"]

# Cadenas que se revisan como respaldo si falla la lista de restaurantes con
# promo. Formato: "<id>-<nombre>" tal como aparece en
# rappi.com.pe/lima/restaurantes/delivery/<id>-<nombre>
DEFAULT_CHAINS = [
    "6419-fridays",
    "4569-chilis",
    "6059-bembos",
    "5593-chinawok",
    "6498-kfc",
    "6030-popeyes",
    "3831-papa-johns",
    "4488-mcdonalds",
    "8079-little-caesars",
]

_TRUE = {"1", "si", "sí", "s", "yes", "y", "true", "verdadero", "on"}
_FALSE = {"0", "no", "n", "false", "falso", "off"}


class ConfigError(ValueError):
    """Error de configuración con un mensaje pensado para el usuario."""


def _get(env: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _int(env, names, default, minimum, maximum):
    raw = _get(env, *names)
    if raw is None:
        return default
    try:
        value = int(float(raw.replace("%", "").replace(",", ".")))
    except ValueError as exc:
        raise ConfigError(f"{names[0]} debe ser un número entero (recibí {raw!r}).") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{names[0]} debe estar entre {minimum} y {maximum} (recibí {value}).")
    return value


def _float(env, names, default, minimum, maximum):
    raw = _get(env, *names)
    if raw is None:
        return default
    try:
        value = float(raw.replace(",", "."))
    except ValueError as exc:
        raise ConfigError(f"{names[0]} debe ser un número (recibí {raw!r}).") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{names[0]} debe estar entre {minimum} y {maximum} (recibí {value}).")
    return value


def _bool(env, names, default):
    raw = _get(env, *names)
    if raw is None:
        return default
    value = raw.lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ConfigError(f"{names[0]} debe ser 'si' o 'no' (recibí {raw!r}).")


def _list(env, names, default):
    raw = _get(env, *names)
    if raw is None:
        return list(default)
    items = [item.strip() for item in re.split(r"[,;\n]", raw)]
    return [item for item in items if item]


def parse_location(raw: str) -> tuple[float, float]:
    """Convierte "-12.0977, -77.0365" (formato de Google Maps) en (lat, lng)."""
    error = ConfigError(
        "RAPPI_UBICACION debe tener el formato 'latitud, longitud', "
        "por ejemplo: -12.0977, -77.0365 (cópialo desde Google Maps)."
    )
    text = raw.strip().strip("()[] ")
    parts = [part for part in re.split(r"[\s,;]+", text) if part]
    # "-12,0977; -77,0365" (decimales con coma) queda partido en cuatro trozos.
    if len(parts) == 4 and all(re.fullmatch(r"-?\d+", part) for part in parts):
        parts = [f"{parts[0]}.{parts[1]}", f"{parts[2]}.{parts[3]}"]
    if len(parts) != 2:
        raise error
    try:
        lat, lng = float(parts[0]), float(parts[1])
    except ValueError as exc:
        raise error from exc
    # Perú está aproximadamente entre las latitudes -19 y 0 y las longitudes -82 y -68.
    if not (-19.0 <= lat <= 0.5 and -82.0 <= lng <= -68.0):
        raise ConfigError(
            "La ubicación no parece estar en Perú. Revisa RAPPI_UBICACION: primero va la "
            "latitud (ej. -12.09) y luego la longitud (ej. -77.03)."
        )
    return lat, lng


def parse_quiet_hours(raw: str | None) -> tuple[int, int] | None:
    """Convierte "23-7" en (23, 7): de 11 p. m. a 7 a. m. (hora de Lima)."""
    if raw is None or raw.strip().lower() in {"", "no", "0", "ninguna", "ninguno"}:
        return None
    match = re.fullmatch(r"\s*(\d{1,2})(?::00)?\s*(?:-|a|hasta)\s*(\d{1,2})(?::00)?\s*", raw.lower())
    if not match:
        raise ConfigError("HORAS_SILENCIO debe tener el formato 'inicio-fin', por ejemplo 23-7.")
    start, end = int(match.group(1)), int(match.group(2))
    if not (0 <= start <= 23 and 0 <= end <= 23):
        raise ConfigError("HORAS_SILENCIO usa horas de 0 a 23, por ejemplo 23-7.")
    return (start, end) if start != end else None


@dataclass
class Config:
    min_discount: int = 60
    alarm_from: int = 80
    quiet_hours: tuple[int, int] | None = None
    city: str = "lima"
    lat: float = DEFAULT_LAT
    lng: float = DEFAULT_LNG
    custom_location: bool = False
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str | None = None
    ntfy_token: str | None = None
    rappi_pro: bool = False
    store_types: list[str] = field(default_factory=lambda: list(DEFAULT_STORE_TYPES))
    store_batch: int = 40
    chains: list[str] = field(default_factory=lambda: list(DEFAULT_CHAINS))
    branches_per_chain: int = 2
    max_distance_km: float | None = None
    max_candidates: int = 30
    max_alerts_per_run: int = 8
    realert_hours: int = 168
    request_delay: float = 1.0
    run_every_minutes: int = 30
    base_url: str = "https://www.rappi.com.pe"
    state_path: str = "state/state.json"
    check_restaurants: bool = True
    check_stores: bool = True
    chains_always: bool = False
    headless: bool = True
    verbose: bool = False
    restaurant_budget_s: int = 6 * 60
    store_budget_s: int = 8 * 60

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        cfg = cls()
        cfg.min_discount = _int(env, ("DESCUENTO_MINIMO", "MIN_DISCOUNT"), 60, 1, 100)
        cfg.alarm_from = _int(env, ("ALARMA_DESDE",), 80, 1, 100)
        cfg.quiet_hours = parse_quiet_hours(_get(env, "HORAS_SILENCIO"))
        city = (_get(env, "CIUDAD") or cfg.city).lower()
        if not re.fullmatch(r"[a-z-]{2,40}", city):
            raise ConfigError("CIUDAD debe ser el nombre de la ciudad como aparece en Rappi, ej. lima.")
        cfg.city = city

        location = _get(env, "RAPPI_UBICACION")
        lat_raw, lng_raw = _get(env, "RAPPI_LAT"), _get(env, "RAPPI_LNG")
        if location:
            cfg.lat, cfg.lng = parse_location(location)
            cfg.custom_location = True
        elif lat_raw and lng_raw:
            cfg.lat, cfg.lng = parse_location(f"{lat_raw}, {lng_raw}")
            cfg.custom_location = True

        cfg.ntfy_server = (_get(env, "NTFY_SERVER") or cfg.ntfy_server).rstrip("/")
        if not cfg.ntfy_server.startswith(("https://", "http://")):
            raise ConfigError("NTFY_SERVER debe empezar con https://")
        cfg.ntfy_topic = _get(env, "NTFY_TOPIC")
        if cfg.ntfy_topic and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cfg.ntfy_topic):
            raise ConfigError(
                "NTFY_TOPIC solo puede tener letras, números, guiones y guiones bajos (máx. 64)."
            )
        cfg.ntfy_token = _get(env, "NTFY_TOKEN")
        cfg.rappi_pro = _bool(env, ("RAPPI_PRO",), False)
        cfg.store_types = _list(env, ("TIPOS_TIENDA",), DEFAULT_STORE_TYPES)
        cfg.store_batch = _int(env, ("TIENDAS_POR_RONDA",), 40, 1, 1000)
        cfg.chains = _list(env, ("CADENAS",), DEFAULT_CHAINS)
        cfg.branches_per_chain = _int(env, ("LOCALES_POR_CADENA",), 2, 1, 30)
        max_km = _float(env, ("DISTANCIA_MAXIMA_KM",), 0.0, 0.0, 100.0)
        cfg.max_distance_km = max_km or None
        cfg.max_candidates = _int(env, ("MAX_RESTAURANTES_A_REVISAR",), 30, 1, 200)
        cfg.max_alerts_per_run = _int(env, ("MAX_AVISOS_POR_RONDA",), 8, 1, 50)
        cfg.realert_hours = _int(env, ("REPETIR_AVISO_HORAS",), 168, 1, 24 * 60)
        cfg.request_delay = _float(env, ("PAUSA_ENTRE_CONSULTAS",), 1.0, 0.0, 30.0)
        cfg.run_every_minutes = _int(env, ("MINUTOS_ENTRE_RONDAS",), 30, 5, 24 * 60)
        cfg.base_url = (_get(env, "RAPPI_BASE_URL") or cfg.base_url).rstrip("/")
        cfg.state_path = _get(env, "ARCHIVO_MEMORIA") or cfg.state_path
        cfg.check_restaurants = _bool(env, ("REVISAR_RESTAURANTES",), True)
        cfg.check_stores = _bool(env, ("REVISAR_TIENDAS",), True)
        cfg.chains_always = _bool(env, ("REVISAR_CADENAS_SIEMPRE",), False)
        cfg.headless = _bool(env, ("NAVEGADOR_OCULTO",), True)
        cfg.verbose = _bool(env, ("DETALLE_EN_LOGS",), False)
        cfg.restaurant_budget_s = _int(env, ("TIEMPO_MAX_RESTAURANTES_SEG",), 6 * 60, 30, 60 * 60)
        cfg.store_budget_s = _int(env, ("TIEMPO_MAX_TIENDAS_SEG",), 8 * 60, 30, 60 * 60)
        return cfg

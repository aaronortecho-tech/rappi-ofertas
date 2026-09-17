import pytest

from monitor.config import DEFAULT_LAT, Config, ConfigError, parse_location, parse_quiet_hours


def test_defaults_with_empty_values():
    cfg = Config.from_env({"DESCUENTO_MINIMO": "", "NTFY_TOPIC": " ", "RAPPI_UBICACION": ""})
    assert cfg.min_discount == 60
    assert cfg.alarm_from == 80
    assert cfg.ntfy_topic is None
    assert cfg.lat == DEFAULT_LAT and not cfg.custom_location
    assert cfg.store_batch == 40
    assert cfg.quiet_hours is None
    assert "market" in cfg.store_types


def test_values_are_read():
    cfg = Config.from_env(
        {
            "DESCUENTO_MINIMO": "65%",
            "ALARMA_DESDE": "85",
            "NTFY_TOPIC": "ofertas_aaron-2026",
            "RAPPI_UBICACION": "-12.0977, -77.0365",
            "RAPPI_PRO": "Sí",
            "TIPOS_TIENDA": "market; farmacia",
            "HORAS_SILENCIO": "23-7",
            "DISTANCIA_MAXIMA_KM": "6,5",
            "NTFY_SERVER": "https://ntfy.example.com/",
        }
    )
    assert cfg.min_discount == 65
    assert cfg.alarm_from == 85
    assert cfg.ntfy_topic == "ofertas_aaron-2026"
    assert (cfg.lat, cfg.lng) == (-12.0977, -77.0365) and cfg.custom_location
    assert cfg.rappi_pro is True
    assert cfg.store_types == ["market", "farmacia"]
    assert cfg.quiet_hours == (23, 7)
    assert cfg.max_distance_km == 6.5
    assert cfg.ntfy_server == "https://ntfy.example.com"


@pytest.mark.parametrize(
    "raw",
    ["-12.0977, -77.0365", "(-12.0977,-77.0365)", "-12,0977; -77,0365", "-12.0977 -77.0365", " -12.0977 ,  -77.0365 "],
)
def test_location_formats(raw):
    assert parse_location(raw) == (-12.0977, -77.0365)


@pytest.mark.parametrize("raw", ["abc", "-12.0977", "-77.0365, -12.0977", "40.71, -74.00", "1, 2, 3"])
def test_bad_locations(raw):
    with pytest.raises(ConfigError):
        parse_location(raw)


def test_quiet_hours():
    assert parse_quiet_hours("23-7") == (23, 7)
    assert parse_quiet_hours("0 a 6") == (0, 6)
    assert parse_quiet_hours("no") is None
    assert parse_quiet_hours("5-5") is None
    with pytest.raises(ConfigError):
        parse_quiet_hours("25-7")
    with pytest.raises(ConfigError):
        parse_quiet_hours("de noche")


@pytest.mark.parametrize(
    "env",
    [
        {"DESCUENTO_MINIMO": "abc"},
        {"DESCUENTO_MINIMO": "0"},
        {"DESCUENTO_MINIMO": "150"},
        {"NTFY_TOPIC": "mi tema"},
        {"RAPPI_PRO": "quizás"},
        {"NTFY_SERVER": "ntfy.sh"},
        {"CIUDAD": "Lima 1"},
    ],
)
def test_invalid_values_raise_friendly_errors(env):
    with pytest.raises(ConfigError):
        Config.from_env(env)

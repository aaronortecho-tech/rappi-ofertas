import logging

from monitor.privacy import PrivateFormatter


def test_formatter_hides_secrets_in_exception_traceback(cfg):
    formatter = PrivateFormatter(cfg)
    try:
        raise RuntimeError(f"request {cfg.ntfy_topic} lat={cfg.lat} lng={cfg.lng}")
    except RuntimeError:
        import sys
        record = logging.LogRecord("test", logging.ERROR, "test", 1, "falló", (), sys.exc_info())
    output = formatter.format(record)
    assert "RuntimeError" in output and "[oculto]" in output
    assert cfg.ntfy_topic not in output
    assert str(cfg.lat) not in output and str(cfg.lng) not in output

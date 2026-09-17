"""Oculta secretos y coordenadas también en excepciones de bibliotecas."""

import logging
import urllib.parse

from .browser import location_cookie_value


class PrivateFormatter(logging.Formatter):
    def __init__(self, cfg):
        super().__init__("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
        values = [cfg.ntfy_topic, cfg.ntfy_token, str(cfg.lat), str(cfg.lng),
                  location_cookie_value(cfg.lat, cfg.lng)]
        self.values = sorted({value for value in values if value}, key=len, reverse=True)

    def redact(self, text):
        for value in self.values:
            text = text.replace(value, "[oculto]")
            text = text.replace(urllib.parse.quote(value, safe=""), "[oculto]")
        return text

    def format(self, record):
        return self.redact(super().format(record))

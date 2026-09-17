"""Mensajes para el celular (ntfy)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import Config
from .models import Alert, Offer

LIMA = timezone(timedelta(hours=-5))
MAX_MESSAGE_BYTES = 3800  # ntfy acepta hasta 4096 bytes de texto
MAX_LINES = 6

KIND_LABEL = {"restaurante": "Restaurante", "tienda": "Tienda", "cadena": "Cadena"}


def format_price(value: float | None) -> str:
    return "?" if value is None else f"S/ {value:,.2f}"


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def offer_line(offer: Offer) -> str:
    line = f"• -{offer.pct}% {_short(offer.name, 60)}: {format_price(offer.price)}"
    if offer.regular_price:
        line += f" (antes {format_price(offer.regular_price)})"
    if offer.pro_only:
        line += " [Rappi Pro]"
    return line


def truncate_bytes(text: str, limit: int = MAX_MESSAGE_BYTES) -> str:
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[: limit - 3].decode("utf-8", errors="ignore").rstrip() + "…"


def alert_title(alert: Alert) -> str:
    icon = "🚨" if alert.best_pct >= 80 else "🔥"
    only_announced = not alert.offers and not alert.store_wide_text
    amount = f"hasta -{alert.best_pct}%" if only_announced else f"-{alert.best_pct}%"
    return _short(f"{icon} {amount} en {alert.store_name}", 120)


def alert_message(alert: Alert, show_distance: bool = True) -> str:
    lines: list[str] = []
    if alert.store_wide_text:
        lines.append(f"• Descuento en toda la carta: {alert.store_wide_text}")
    offers = sorted(alert.offers, key=lambda offer: -offer.pct)
    for offer in offers[:MAX_LINES]:
        lines.append(offer_line(offer))
    if len(offers) > MAX_LINES:
        lines.append(f"…y {len(offers) - MAX_LINES} ofertas más")
    if alert.announced_text:
        lines.append(
            f"• Anuncia «{alert.announced_text}», pero no vi el producto en la web: revisa la app."
        )
    footer = KIND_LABEL.get(alert.kind, "Local")
    if alert.kind == "cadena":
        footer += " (revisa si aplica a tu zona)"
    if show_distance and alert.distance_km is not None:
        footer += f" · a {alert.distance_km:.1f} km"
    lines.append(footer)
    return truncate_bytes("\n".join(lines))


def in_quiet_hours(quiet: tuple[int, int] | None, now: float) -> bool:
    if not quiet:
        return False
    start, end = quiet
    hour = datetime.fromtimestamp(now, LIMA).hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def alert_priority(alert: Alert, cfg: Config, now: float) -> int:
    if in_quiet_hours(cfg.quiet_hours, now):
        return 2  # llega sin sonido y sin vibración
    return 5 if alert.best_pct >= cfg.alarm_from else 4


class Notifier:
    """Envía notificaciones a ntfy (o las muestra en pantalla con --sin-enviar)."""

    def __init__(self, cfg: Config, http, dry_run: bool = False, log: logging.Logger | None = None):
        self.cfg = cfg
        self.http = http
        self.dry_run = dry_run
        self.log = log or logging.getLogger("monitor")
        self.sent = 0
        self.printed: list[dict] = []

    def send(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: list[str] | None = None,
        click: str | None = None,
    ) -> bool:
        payload: dict = {
            "topic": self.cfg.ntfy_topic or "sin-tema",
            "title": _short(title, 200),
            "message": truncate_bytes(message),
            "priority": priority,
        }
        if tags:
            payload["tags"] = tags
        if click:
            payload["click"] = click
            payload["actions"] = [{"action": "view", "label": "Abrir en Rappi", "url": click}]
        if self.dry_run:
            self.printed.append(payload)
            print(f"\n[{priority}] {payload['title']}\n{payload['message']}\n{click or ''}".rstrip())
            return True
        headers = {"Authorization": f"Bearer {self.cfg.ntfy_token}"} if self.cfg.ntfy_token else {}
        try:
            status = self.http.post_json(f"{self.cfg.ntfy_server}/", payload, headers)
        except Exception as exc:  # noqa: BLE001 - un aviso fallido no debe detener el monitor
            self.log.warning("No se pudo enviar la notificación: %s", exc)
            return False
        if 200 <= status < 300:
            self.sent += 1
            return True
        self.log.warning("ntfy respondió %s al enviar la notificación", status)
        return False

    def send_alert(self, alert: Alert, now: float) -> bool:
        tags = ["rotating_light"] if alert.best_pct >= 80 else ["fire"]
        return self.send(
            alert_title(alert),
            alert_message(alert),
            priority=alert_priority(alert, self.cfg, now),
            tags=tags,
            click=alert.url,
        )

    def send_overflow(self, alerts: list[Alert], now: float) -> bool:
        lines = [f"• -{a.best_pct}% {_short(a.store_name, 50)}" for a in alerts[:15]]
        if len(alerts) > 15:
            lines.append(f"…y {len(alerts) - 15} locales más")
        quiet = in_quiet_hours(self.cfg.quiet_hours, now)
        return self.send(
            f"🔥 {len(alerts)} locales más con descuentos altos",
            "\n".join(lines),
            priority=2 if quiet else 3,
            tags=["fire"],
            click=f"{self.cfg.base_url}/restaurantes",
        )

"""Punto de entrada: python -m monitor"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import replace

from . import __version__
from .browser import RappiBrowser
from .config import Config, ConfigError
from .http import HttpClient
from .models import Alert, ScanResult
from .notify import Notifier
from .scan import scan_chains, scan_restaurants, scan_stores
from .state import State, offer_key
from .privacy import PrivateFormatter

FAILURES_BEFORE_NOTICE = 3


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m monitor",
        description="Revisa Rappi Perú y avisa al celular (ntfy) cuando hay descuentos altos.",
    )
    parser.add_argument("--prueba", action="store_true",
                        help="envía una notificación de prueba con lo que encuentre")
    parser.add_argument("--sin-enviar", action="store_true",
                        help="muestra las notificaciones en pantalla en vez de enviarlas")
    parser.add_argument("--solo-restaurantes", action="store_true")
    parser.add_argument("--solo-tiendas", action="store_true")
    parser.add_argument("--memoria", help="ruta del archivo de memoria (por defecto state/state.json)")
    parser.add_argument("--version", action="version", version=__version__)
    return parser.parse_args(argv)


def setup_logging(verbose: bool) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    return logging.getLogger("monitor")


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "si", "sí", "true", "yes", "y", "s"}


def item_keys(alert: Alert) -> list[tuple[str, object]]:
    """Claves (para no repetir avisos) de cada cosa que trae la alerta."""
    keys: list[tuple[str, object]] = []
    for offer in alert.offers:
        ident = offer.name.lower() if alert.kind == "cadena" else offer.product_id
        keys.append((offer_key("o", alert.kind, alert.store_id, ident, offer.pct), offer))
    if alert.store_wide_text:
        keys.append((offer_key("w", alert.store_id, alert.store_wide_pct), "store_wide"))
    if alert.announced_text:
        keys.append((offer_key("a", alert.store_id, alert.announced_pct), "announced"))
    return keys


def only_new(alert: Alert, state: State, now: float, window_hours: float) -> tuple[Alert | None, list[str]]:
    """Deja en la alerta solo lo que no se avisó recientemente."""
    fresh = [(key, item) for key, item in item_keys(alert) if state.is_new(key, now, window_hours)]
    if not fresh:
        return None, []
    items = [item for _, item in fresh]
    new_alert = replace(
        alert,
        offers=[item for item in items if not isinstance(item, str)],
        store_wide_text=alert.store_wide_text if "store_wide" in items else "",
        store_wide_pct=alert.store_wide_pct if "store_wide" in items else 0,
        announced_text=alert.announced_text if "announced" in items else "",
        announced_pct=alert.announced_pct if "announced" in items else 0,
    )
    return new_alert, [key for key, _ in fresh]


_NOUNS = {
    "restaurantes": ("restaurante revisado", "restaurantes revisados"),
    "tiendas": ("tienda revisada", "tiendas revisadas"),
    "cadenas": ("local de cadena revisado", "locales de cadenas revisados"),
}


def count_text(result: ScanResult) -> str:
    one, many = _NOUNS.get(result.name, ("revisado", "revisados"))
    return f"{result.checked} {one if result.checked == 1 else many}"


def summarize(results: list[ScanResult], cfg: Config) -> str:
    parts = []
    for result in results:
        if result.error:
            parts.append(f"{result.name}: falló ({result.error})")
        else:
            parts.append(f"{count_text(result)}, {len(result.alerts)} con -{cfg.min_discount}% o más")
    return "; ".join(parts) or "no se revisó nada"


def test_message(results: list[ScanResult], cfg: Config, alerts: list[Alert]) -> str:
    problems = not results or any(result.error for result in results)
    lines = ["La prueba detectó problemas; revisa el detalle." if problems else "El monitor funciona."]
    for result in results:
        if result.error:
            lines.append(f"⚠️ {result.name.capitalize()}: no se pudo revisar ({result.error}).")
        else:
            lines.append(f"✅ {count_text(result).capitalize()}.")
    if alerts:
        lines.append(f"Ahora mismo hay {len(alerts)} locales con -{cfg.min_discount}% o más:")
        for alert in sorted(alerts, key=lambda a: -a.best_pct)[:5]:
            lines.append(f"• -{alert.best_pct}% {alert.store_name}")
    else:
        top = sorted((item for r in results for item in r.top_offers), key=lambda item: -item[0])[:3]
        lines.append("No se puede confirmar si hay ofertas en las secciones que fallaron."
                     if problems else f"Ahora no hay nada con -{cfg.min_discount}% o más.")
        if top:
            lines.append("Lo mejor que vi:")
            lines.extend(f"• -{pct}% {name} ({store})" for pct, name, store in top)
    if not cfg.custom_location:
        lines.append("Nota: falta tu ubicación (RAPPI_UBICACION); estoy usando una zona de Lima por defecto.")
    return "\n".join(lines)


def run(cfg: Config, args: argparse.Namespace, log: logging.Logger, now: float | None = None,
        browser_factory=None, http=None, notifier=None) -> int:
    now = time.time() if now is None else now
    privacy = PrivateFormatter(cfg)
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setFormatter(privacy)
    state_path = args.memoria or cfg.state_path
    state = State.load(state_path, log)
    http = http or HttpClient(delay=cfg.request_delay, max_requests=400)
    notifier = notifier or Notifier(cfg, http, dry_run=args.sin_enviar, log=log)
    browser_factory = browser_factory or (lambda: RappiBrowser(cfg, log))
    test_mode = args.prueba or _truthy(os.environ.get("MODO_PRUEBA"))

    do_restaurants = cfg.check_restaurants and not args.solo_tiendas
    do_stores = cfg.check_stores and not args.solo_restaurantes
    log.info("Monitor de ofertas Rappi %s · mínimo -%d%%%s", __version__, cfg.min_discount,
             "" if cfg.custom_location else " · ubicación por defecto")

    results: list[ScanResult] = []
    if do_restaurants:
        restaurants = scan_restaurants(cfg, browser_factory, http, log)
        results.append(restaurants)
        if not restaurants.blocked and (restaurants.error or cfg.chains_always):
            if restaurants.error:
                log.warning("Restaurantes: %s. Se revisan cadenas conocidas como respaldo.", restaurants.error)
            results.append(scan_chains(cfg, http, log))
    if do_stores:
        if any(result.blocked for result in results):
            results.append(ScanResult("tiendas", error="ronda detenida por bloqueo de Rappi", blocked=True))
        else:
            results.append(scan_stores(cfg, http, state, now, log))

    for result in results:
        if result.error:
            result.error = privacy.redact(result.error)
        for note in result.notes:
            log.info("%s: %s", result.name.capitalize(), note)
    log.info("Resumen: %s", summarize(results, cfg))

    # ---- avisos nuevos -------------------------------------------------
    all_alerts = [alert for result in results for alert in result.alerts]
    all_alerts.sort(key=lambda alert: (-alert.best_pct, alert.store_name))
    pending: list[tuple[Alert, list[str]]] = []
    for alert in all_alerts:
        fresh, keys = only_new(alert, state, now, cfg.realert_hours)
        if fresh is not None:
            pending.append((fresh, keys))

    sent = 0
    delivery_failed = False
    overflow_sent = 0
    overflow: list[tuple[Alert, list[str]]] = []
    for alert, keys in pending:
        if sent >= cfg.max_alerts_per_run:
            overflow.append((alert, keys))
            continue
        if notifier.send_alert(alert, now):
            sent += 1
            if not args.sin_enviar:
                for key in keys:
                    state.mark_seen(key, now)
            if cfg.verbose:
                log.info("Aviso: -%d%% %s", alert.best_pct, alert.store_name)
        else:
            delivery_failed = True
    if overflow and notifier.send_overflow([alert for alert, _ in overflow], now):
        overflow_sent = len(overflow)
        if not args.sin_enviar:
            for _, keys in overflow:
                for key in keys:
                    state.mark_seen(key, now)
    if overflow and not overflow_sent:
        delivery_failed = True
    log.info("Avisos nuevos: %d enviados%s", sent,
             f" + resumen de {overflow_sent} más" if overflow_sent else "")

    # ---- mensajes del sistema -------------------------------------------
    if state.first_run and not args.sin_enviar:
        welcome_sent = notifier.send(
            "✅ Monitor de ofertas activado",
            f"Te avisaré cuando haya descuentos de -{cfg.min_discount}% o más en Rappi. "
            f"Los de -{cfg.alarm_from}% o más llegan como alarma.",
            priority=3, tags=["white_check_mark"],
        )
        if welcome_sent:
            state.mark_started(now)
        else:
            delivery_failed = True
    if test_mode:
        if not notifier.send("🧪 Prueba del monitor de Rappi", test_message(results, cfg, all_alerts),
                             priority=3, tags=["test_tube"]):
            delivery_failed = True

    problems = []
    failure_notified = False
    for result in results:
        if result.name == "cadenas":
            continue
        count = state.record_result(result.name, result.error is None)
        if count >= FAILURES_BEFORE_NOTICE:
            problems.append(f"{result.name} ({count} rondas seguidas): {result.error}")
    if problems:
        for problem in problems:
            print(f"::warning::No se pudo revisar {problem}")
        if state.can_notify_failure(now) and not args.sin_enviar:
            ok = notifier.send(
                "⚠️ El monitor de Rappi tiene problemas",
                "No pude revisar " + "; ".join(problems) + ".\n"
                "Si sigue así, abre la carpeta del proyecto en Claude Code y pídele que lo revise.",
                priority=3, tags=["warning"],
            )
            if ok:
                state.last_failure_notice = int(now)
                failure_notified = True

    state.prune(now, max(cfg.realert_hours, 24) * 2)
    if not args.sin_enviar and state.save(state_path, now):
        log.info("Memoria actualizada")

    _write_step_summary(results, cfg, sent + overflow_sent)
    if delivery_failed:
        log.error("No se pudieron entregar todas las notificaciones a ntfy.")
        return 1
    if test_mode and (not results or any(result.error for result in results)):
        return 1
    # Se marca la ejecución como fallida solo cuando también se avisó al
    # celular (como mucho una vez al día), para no llenar el correo de avisos.
    return 1 if failure_notified else 0


def _write_step_summary(results: list[ScanResult], cfg: Config, alerts: int) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["### Monitor de ofertas Rappi", "", "| Sección | Revisados | Con descuento alto | Estado |",
             "|---|---|---|---|"]
    for result in results:
        status = f"⚠️ {result.error}" if result.error else "✅"
        lines.append(f"| {result.name} | {result.checked} | {len(result.alerts)} | {status} |")
    lines += ["", f"Descuento mínimo: -{cfg.min_discount}% · Avisos enviados: {alerts}", ""]
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cfg = Config.from_env()
    except ConfigError as exc:
        setup_logging(False)
        print(f"::error::{exc}")
        logging.getLogger("monitor").error("Configuración inválida: %s", exc)
        return 2
    log = setup_logging(cfg.verbose)
    if not cfg.ntfy_topic and not args.sin_enviar:
        message = "Falta NTFY_TOPIC (el tema de ntfy donde recibirás las alertas)."
        if os.environ.get("GITHUB_EVENT_NAME") == "schedule":
            # Mientras no se configure, las rondas automáticas no fallan en rojo
            # (GitHub enviaría un correo por cada una).
            print(f"::warning::{message} El monitor no hará nada hasta que lo configures.")
            return 0
        print(f"::error::{message}")
        log.error("Falta NTFY_TOPIC. Configúralo o usa --sin-enviar para probar.")
        return 2
    try:
        return run(cfg, args, log)
    except KeyboardInterrupt:
        return 130

"""Monitores separados de hogar/tecnología y beneficios de viajes.

Solo datos públicos: no compra, no inicia sesión y no evade bloqueos.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from datetime import datetime, date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from html.parser import HTMLParser
import json
import logging
import math
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit, urljoin

from .config import Config
from .http import HttpClient, Blocked
from .notify import Notifier, LIMA, in_quiet_hours
from .parsers import extract_next_data
from .privacy import PrivateFormatter
from .state import State, offer_key
from .vtex import SOURCES as VTEX_SOURCES, scan_home
from .flights import scan_trips, INCOMPLETE
from .convenience import scan_convenience
from .autos import scan_autos
from .inmuebles import scan_inmuebles

DINERS_URL = "https://dinersclubperu.pe/establecimientos/modotravel/categoria/viajes"
UNAVAILABLE = {"comida": "Mass y Listo: pendientes; no se verificó un catálogo con precios comparables automatizable.", "hogar": "Ripley: acceso público bloqueado (403).",
               "viajes": "LATAM y Despegar: acceso público bloqueado. No se consultan tarifas en vivo. Travelpayouts solo con el secreto TRAVELPAYOUTS_TOKEN.",
               "autos": "Derco, retención relativa y resumen semanal: pendientes. Mercado Libre y Autocosmos no se usan (robots/pausas).",
               "inmuebles": "Urbania, Adondevivir y RE/MAX: bloqueo antibots de Cloudflare. Century 21, remates judiciales y otros bancos: pendientes."}
TOPICS = {'hogar': 'NTFY_TOPIC_HOGAR', 'viajes': 'NTFY_TOPIC_VIAJES', 'comida': 'NTFY_TOPIC',
          'autos': 'NTFY_TOPIC_AUTOS', 'inmuebles': 'NTFY_TOPIC_INMUEBLES'}
TITLES = {'hogar': 'Hogar y tecnología', 'viajes': 'Viajes y escapadas', 'comida': 'Comida y bazar',
          'autos': 'Autos', 'inmuebles': 'Inmuebles'}
# Grupos lentos: pocas y buenas. Como mucho 3 avisos por ronda y sin repetir en 60 días.
SLOW_GROUPS = {'autos', 'inmuebles'}
CATEGORIES = [("Tecnología", "cat40793/Tecnologia"), ("Muebles", "cat40700/Muebles"),
              ("Electrodomésticos", "cat40584/Electrohogar"), ("Hogar", "cat40474/Decoracion")]
RETAIL_SOURCES = [(shop, category, base + path)
                  for shop, base in [("Falabella", "https://www.falabella.com.pe/falabella-pe/category/"),
                                     ("Sodimac", "https://www.sodimac.com.pe/sodimac-pe/lista/")]
                  for category, path in CATEGORIES]


STABLE_KINDS = {"flight_distance", "autos", "inmuebles"}


@dataclass
class Deal:
    source: str
    identity: str
    name: str
    url: str
    pct: int
    price: float | None = None
    regular: float | None = None
    seller: str = ""
    condition: str = ""
    category: str = ""
    previous_min: float | None = None
    currency: str = "PEN"
    reference_kind: str = "published"
    note: str = ""          # solo se muestra; no entra en la clave (p. ej. «visto hace 5 h»)
    rank: float = 0.0       # orden dentro del resumen de hogar; tampoco entra en la clave

    @property
    def key(self):
        if self.reference_kind in STABLE_KINDS:
            # El porcentaje de estas señales se recalcula con medianas que cambian cada ronda:
            # no debe volver a avisar el mismo precio solo porque varió la referencia.
            return offer_key(self.reference_kind, self.source, self.identity, self.price)
        scope = "retail" if self.source in ("Falabella", "Sodimac") else ("vtex" if self.source in {name for name, _ in VTEX_SOURCES} else self.source)
        return offer_key("catalog", scope, self.identity, self.seller.lower(),
                         self.price, self.pct, self.condition)

    @property
    def history_key(self):
        scope = "retail" if self.source in ("Falabella", "Sodimac") else ("vtex" if self.source in {name for name, _ in VTEX_SOURCES} else self.source)
        return offer_key("price", scope, self.identity, self.seller.lower(), self.condition)


class CatalogState(State):
    def __init__(self, data=None, existed=False):
        data = data if isinstance(data, dict) else {}
        self.flight_alerts = data.get("flight_alerts", {})
        if not isinstance(self.flight_alerts, dict): self.flight_alerts = {}
        self.history = data.get("history", {})
        # Memoria propia de cada grupo nuevo (autos, inmuebles, bandas de vuelos).
        self.datos = data.get("datos", {})
        if not isinstance(self.datos, dict): self.datos = {}
        self.cursors = data.get("cursors", {})
        if not isinstance(self.history, dict): self.history = {}
        if not isinstance(self.cursors, dict): self.cursors = {}
        super().__init__(data, existed)

    def _serialize(self, include_saved_at=True):
        data = super()._serialize(include_saved_at)
        # State conserva esta instantánea para detectar cambios. No compartir los
        # diccionarios mutables o una ronda sin avisos perdería su historial nuevo.
        data.update(history=deepcopy(self.history), cursors=deepcopy(self.cursors),
                    flight_alerts=deepcopy(self.flight_alerts), datos=deepcopy(self.datos))
        return data

    def observe(self, deal, now):
        if deal.price is None: return
        day = int(now // 86400)
        rows = self.history.get(deal.history_key, [])
        rows = [r for r in rows if isinstance(r, (list, tuple)) and len(r) == 2
                and isinstance(r[0], int) and isinstance(r[1], (int, float))
                and day - 30 <= r[0] <= day]
        # Se consulta antes de registrar el precio actual.
        deal.previous_min = min((r[1] for r in rows), default=None)
        values = dict(rows)
        values[day] = min(values.get(day, deal.price), deal.price)
        self.history[deal.history_key] = sorted(values.items())

    def prune(self, now, keep_hours):
        super().prune(now, keep_hours)
        self.flight_alerts = {k: v for k, v in self.flight_alerts.items()
                              if isinstance(v, dict) and isinstance(v.get("created"), (int, float))
                              and now - 7 * 86400 <= v["created"] <= now}
        self.flight_alerts = dict(sorted(self.flight_alerts.items(), key=lambda kv: kv[1]["created"])[-2000:])
        day = int(now // 86400)
        self.history = {k: [r for r in rows if r[0] >= day - 30]
                        for k, rows in self.history.items() if isinstance(rows, list)}
        self.history = {k: v for k, v in self.history.items() if v}
        # Memoria acotada: no acumular cientos de miles de productos en git.
        recent = sorted(self.history, key=lambda k: self.history[k][-1][0])[-12000:]
        self.history = {k: self.history[k] for k in recent}


def money(raw):
    if isinstance(raw, bool): return None
    value = str(raw).strip().replace(",", "")
    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", value): return None
    try: return Decimal(value)
    except InvalidOperation: return None


def retail_products(html, source, category):
    data = extract_next_data(html)
    pp = (data or {}).get("props", {}).get("pageProps", {})
    products = pp.get("results")
    if not isinstance(products, list):
        raise ValueError("catálogo sin datos de productos (la página cambió o falló)")
    pagination = pp.get("pagination") or {}
    if not products and pagination.get("count") != 0:
        raise ValueError("catálogo vacío sin confirmación de resultados")
    result = []
    for item in products:
        if not isinstance(item, dict): continue
        url = item.get("url", "")
        expected = "www.falabella.com.pe" if source == "Falabella" else "www.sodimac.com.pe"
        if urlsplit(url).scheme != "https" or urlsplit(url).hostname != expected: continue
        if item.get("isAvailable") is False or item.get("inStock") is False: continue
        amounts = {}
        for entry in item.get("prices", []):
            raw = entry.get("price", [])
            if entry.get("symbol", "").strip() != "S/" or not isinstance(raw, list) or len(raw) != 1: continue
            amount = money(raw[0])
            if amount is not None and amount > 0: amounts[entry.get("type")] = amount
        regular = amounts.get("normalPrice")
        standard = min((amounts[k] for k in ("internetPrice", "eventPrice") if k in amounts), default=None)
        if regular is None or regular <= 0: continue
        variants = [(standard, "Precio web; confirmar stock y envío")]
        if amounts.get("cmrPrice") is not None:
            variants.append((amounts['cmrPrice'], "Requiere tarjeta CMR; confirmar condiciones y envío"))
        for price, condition in variants:
            if price is None or price >= regular: continue
            # No redondear 59.6% a 60%: el usuario pidió al menos el umbral.
            pct = int(((1 - price / regular) * 100).to_integral_value(rounding=ROUND_FLOOR))
            result.append(Deal(source, str(item.get("skuId") or item.get("productId")),
                               str(item.get("displayName") or "Producto"), url, pct,
                               float(price), float(regular), str(item.get("sellerName") or "No informado"),
                               condition, category))
    return result, len(products), pagination


def scan_retail(state, now, http_factory=HttpClient, sources=None):
    deals, reports, clients = {}, [], {}
    for source, category, base in (RETAIL_SOURCES if sources is None else sources):
        if source not in clients: clients[source] = http_factory(delay=1.5, max_requests=20)
        client = clients[source]
        if client.blocked:
            reports.append((source + "/" + category, 0, "omitida tras bloqueo del sitio")); continue
        checked, error = 0, None
        cursor_key = offer_key(source, category)
        try:
            query = {"f.range.derived.variant.discount": "60% dcto y más"}
            html = client.get(base + "?" + urlencode(query))
            products, count, pagination = retail_products(html, source, category)
            checked += count
            pages = max(1, math.ceil(pagination.get("count", 0) / max(1, pagination.get("perPage", 48))))
            page = state.cursors.get(cursor_key, 2)
            page = page if isinstance(page, int) and 2 <= page <= pages else 2
            if pages >= 2:
                query["page"] = page
                more, count, _ = retail_products(client.get(base + "?" + urlencode(query)), source, category)
                products += more; checked += count
                state.cursors[cursor_key] = page + 1 if page < pages else 2
            for deal in products:
                old = deals.get(deal.history_key)
                if old is None or deal.price < old.price:
                    deals[deal.history_key] = deal
        except Exception as exc:
            error = "acceso bloqueado; no se insiste" if isinstance(exc, Blocked) else type(exc).__name__ + ": " + str(exc)[:140]
        reports.append((source + "/" + category, checked, error))
    # Si tanto CMR como web superan el umbral se envía una sola ficha,
    # priorizando la opción que no requiere tarjeta.
    chosen = {}
    for deal in deals.values():
        state.observe(deal, now)
        if deal.pct < 60: continue
        key = (deal.identity, deal.seller.lower())
        old = chosen.get(key)
        if old is None or (old.condition.startswith("Requiere") and not deal.condition.startswith("Requiere")):
            chosen[key] = deal
    return list(chosen.values()), reports


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.skip = 0; self.parts = []
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style"): self.skip = max(0, self.skip - 1)
    def handle_data(self, data):
        if not self.skip and data.strip(): self.parts.append(data.strip())


def plain_text(html):
    parser = TextParser(); parser.feed(html or "")
    return " ".join(parser.parts)


class DinersCards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.current = None; self.cards = []
        self.in_span = False; self.in_p = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "all__item" in attrs.get("class", "").split():
            self.current = {"url": attrs.get("href", ""), "name": [], "text": []}
        if self.current is not None:
            if tag == "span": self.in_span = True
            if tag == "p": self.in_p = True
    def handle_endtag(self, tag):
        if tag == "span": self.in_span = False
        if tag == "p": self.in_p = False
        if tag == "a" and self.current is not None:
            self.cards.append({k: " ".join(v).strip() if isinstance(v, list) else v for k, v in self.current.items()})
            self.current = None
    def handle_data(self, data):
        if self.current is not None:
            if self.in_span: self.current['name'].append(data.strip())
            if self.in_p: self.current['text'].append(data.strip())


MONTHS = {name: i + 1 for i, name in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split())}
MONTHS['setiembre'] = 9
MONTH_PATTERN = '|'.join(MONTHS)


def validity(text):
    """Rangos explícitos de compra en español; sin vigencia verificable no se avisa."""
    pattern = (rf"(?:v[aá]lid[oa]|vigencia|compras).*?(?:del|desde el|desde)\s+(\d{{1,2}})"
               rf"(?:\s+de\s+({MONTH_PATTERN})(?:\s+de(?:l)?\s+(\d{{4}}))?)?"
               rf"\s+(?:al|hasta el|hasta)\s+(\d{{1,2}})\s+de\s+({MONTH_PATTERN})\s+de(?:l)?\s+(\d{{4}})")
    match = re.search(pattern, text.lower())
    if not match: return None
    start_day, start_month, start_year, end_day, end_month, year = match.groups()
    try:
        end = date(int(year), MONTHS[end_month], int(end_day))
        start = date(int(start_year or year), MONTHS[start_month or end_month], int(start_day))
    except ValueError: return None
    return (start, end) if start <= end else None


def exact_discount(text):
    matches = list(re.finditer(r"(\d{1,3}(?:[.,]\d+)?)\s*%\s*(?:de\s*)?(?:descuento|dcto|dto)", text, re.I))
    values = []
    for match in matches:
        preceding = text[max(0, match.start() - 35):match.start()].lower()
        if re.search(r"hasta(?:\s+(?:un|el))?\s*$", preceding): continue
        value = float(match.group(1).replace(',', '.'))
        if 0 < value <= 100: values.append(int(value))
    return max(values, default=0)


def diners_deal(card, html, today):
    text = plain_text(html)
    conditions = text.split("Condiciones", 1)[-1]
    dates = validity(conditions)
    if not dates or not dates[0] <= today <= dates[1]: return None
    pct = exact_discount(card['text'])
    if pct < 50: return None
    # Evitar enviar itinerarios que salgan explícitamente de otra ciudad.
    origins = re.findall(r"(?:salidas?\s+desde|origen\s*:)\s*([A-Za-zÁÉÍÓÚáéíóúñÑ ]{2,45})", conditions, re.I)
    if origins and not any("lima" in origin.lower() for origin in origins): return None
    conditions = re.split(r"Leer más|Teléfono:", conditions, maxsplit=1)[0].strip()
    return Deal("Diners", card['url'], card['name'], card['url'], pct,
                condition=f"Tarjeta Diners Club. Vigencia: {dates[0]} a {dates[1]}. "
                          f"{card['text']}\n{conditions[:1300]}", category="Viajes")


def scan_travel(state, now, http_factory=HttpClient):
    http = http_factory(delay=1.5, max_requests=25)
    try:
        html = http.get(DINERS_URL)
        parser = DinersCards(); parser.feed(html or "")
        cards = [c for c in parser.cards if c['name'] and c['text']
                 and urlsplit(c['url']).hostname == 'dinersclubperu.pe'
                 and urlsplit(c['url']).path.startswith('/establecimientos/modotravel/')]
        if not cards: raise ValueError("no se encontraron promociones Diners")
        deals = []
        today = datetime.fromtimestamp(now, LIMA).date()
        for card in cards:
            # Los anuncios «hasta» no garantizan el mínimo; tampoco cuotas/regalos.
            if exact_discount(card['text']) < 50: continue
            detail = http.get(card['url'])
            if not detail: raise ValueError("no se pudo leer una promoción Diners")
            deal = diners_deal(card, detail, today)
            if deal: deals.append(deal)
        return deals, [("Diners/viajes", len(cards), None)]
    except Exception as exc:
        return [], [("Diners/viajes", 0, "acceso bloqueado" if isinstance(exc, Blocked) else type(exc).__name__ + ": " + str(exc)[:140])]


def deal_text(deal):
    if deal.reference_kind == 'flight_history':
        return (f"Caída observada: {deal.pct}% · {deal.source} · {deal.name}\n"
                f"Ahora desde {deal.currency} {deal.price:,.2f}\n"
                f"Mínimo previo observado (ventana de 30 días): {deal.currency} {deal.regular:,.2f}\n"
                f"Comparación basada en al menos 3 días previos, no descuento anunciado.\n"
                f"{deal.condition}\n{deal.url}")
    if deal.reference_kind == 'flight_distance':
        return (f"✈️ {deal.name}\n"
                f"💰 Desde {deal.currency} {deal.price:,.2f}  |  {deal.pct}% bajo lo normal para esa distancia\n"
                f"Lo habitual en ese tramo: ~{deal.currency} {deal.regular:,.2f}\n"
                f"{deal.source} · medida en centavos por km, no descuento anunciado\n"
                f"{deal.condition}\n{deal.url}")
    if deal.reference_kind in ('autos', 'inmuebles'):
        # El texto lo arma el propio grupo: cada uno explica su criterio.
        return deal.condition + "\n" + deal.url
    lines = [f"🛒 {deal.name}"]
    if deal.price is not None:
        lines.append(f"💰 S/ {deal.price:,.2f}  |  -{deal.pct}%")
        lines.append(f"Antes (publicado): S/ {deal.regular:,.2f}")
        # El usuario lee en el celular: vendedor, historial y avisos genéricos de stock se ven al abrir
        # el enlace. Solo se muestra el historial cuando advierte que antes estuvo más barato.
        if deal.previous_min is not None and deal.previous_min < deal.price:
            lines.append(f"Ojo: estuvo a S/ {deal.previous_min:,.2f} en los últimos 30 días")
    if deal.price is None: lines.append(f"Descuento: {deal.pct}%")
    if deal.note: lines.append(deal.note)
    if deal.condition.startswith("Requiere tarjeta CMR"): lines.append("💳 Solo con tarjeta CMR")
    elif not deal.condition.startswith(("Precio web", "Precio publicado")): lines.append(deal.condition)
    lines.append(deal.url)
    return "\n".join(lines)


URGENT_HOME_PCT = 80      # estas no esperan al resumen: son las que más rápido se agotan
QUEUE_HOURS = 24          # una oferta que no se vuelve a ver en un día sale de la cola
QUEUE_MAX = 300           # unos 190 avisos caben al día (8 resúmenes de 24): el resto nunca saldría


PERMANENT_DAYS = 7        # días con el mismo precio para concluir que el «antes» es decorativo


def min_savings():
    try: return max(0.0, float(os.environ.get('AHORRO_MINIMO_HOGAR', '') or 20))
    except ValueError: return 20.0


def quality(state, deal, now):
    """Qué tan real es la oferta, con el historial de precios que el propio monitor guarda.

    Devuelve (puntaje, nota, motivo_de_descarte). El precio tachado lo pone el vendedor; lo que
    sí se puede comprobar es si el precio bajó frente a lo observado y cuánto se ahorra en soles."""
    today = int(now // 86400)
    before = {d: p for d, p in state.history.get(deal.history_key, []) if d < today}
    savings = (deal.regular or 0) - (deal.price or 0)
    if deal.price is None or savings < min_savings(): return 0, '', 'ahorro bajo'
    rank = deal.pct + 12 * math.log10(max(savings, 1))
    if len(before) >= PERMANENT_DAYS and all(abs(p - deal.price) <= deal.price * 0.02 for p in before.values()):
        # Mismo precio una semana entera: el descuento es permanente, el «antes» no es real.
        return rank, '', 'descuento permanente'
    note = ''
    if before and deal.price < min(before.values()) * 0.97:
        rank += 25
        note = f'📉 Precio más bajo visto en {len(before)} días (antes S/ {min(before.values()):,.2f})'
    return rank, note, None


def summary_every():
    try: return max(0.5, float(os.environ.get('HORAS_RESUMEN_HOGAR', '') or 3)) * 3600
    except ValueError: return 3 * 3600


def hold_home(state, deals, now):
    """Hogar se revisa cada 30 minutos pero avisa en un resumen cada HORAS_RESUMEN_HOGAR (3 h).

    Todas las candidatas, urgentes incluidas, pasan por una cola guardada en la memoria con una
    sola entrada por producto (vendedor y condición): la última observación reemplaza a la
    anterior, así nunca salen dos precios del mismo producto. Las de 80 % o más salen en cada
    ronda y las demás cuando toca el resumen. Nada sale de la cola hasta que se envía, se
    supera por otra observación o pasan 24 horas sin volver a verla.
    Devuelve (ofertas que tocan ahora, si incluye el resumen, métricas)."""
    queue = state.datos.setdefault('cola_hogar', {})
    stats = {'entradas': 0, 'caducadas': 0, 'ahorro bajo': 0, 'descuento permanente': 0}
    for deal in deals:
        key = deal.history_key
        if not state.is_new(deal.key, now, 168):
            queue.pop(key, None)  # ese mismo precio ya se avisó: cualquier versión anterior queda superada
            continue
        deal.rank, deal.note, reason = quality(state, deal, now)
        if reason:
            queue.pop(key, None); stats[reason] += 1
            continue
        if key not in queue: stats['entradas'] += 1
        queue[key] = {'oferta': asdict(deal), 'visto': int(now)}
    for key, item in list(queue.items()):
        deal = Deal(**item['oferta'])
        if item['visto'] < now - QUEUE_HOURS * 3600:
            queue.pop(key); stats['caducadas'] += 1
        elif not state.is_new(deal.key, now, 168) or quality(state, deal, now)[2]:
            queue.pop(key)
    # Límite solo para las no urgentes: las de 80 % o más nunca se recortan (salen en cada ronda).
    normal = sorted((k for k in queue if queue[k]['oferta']['pct'] < URGENT_HOME_PCT),
                    key=lambda k: queue[k]['oferta'].get('rank', 0), reverse=True)
    for key in normal[QUEUE_MAX:]: queue.pop(key)
    stats['recortadas'] = max(0, len(normal) - QUEUE_MAX)
    digest = now - state.datos.get('ultimo_resumen_hogar', 0) >= summary_every()
    due = []
    for item in queue.values():
        deal = Deal(**item['oferta'])
        if deal.pct < URGENT_HOME_PCT and not digest: continue
        hours = (now - item['visto']) / 3600
        if hours >= 1: deal.note = '\n'.join(filter(None, [deal.note, f'Visto hace {hours:.0f} h: confirmar que siga vigente']))
        due.append(deal)
    oldest = max(((now - v['visto']) / 3600 for v in queue.values()), default=0)
    stats.update(pendientes=len(queue), mas_antigua_h=round(oldest, 1))
    return due, digest and any(d.pct < URGENT_HOME_PCT for d in due), stats


def deliver(deals, state, notifier, now, group, dry_run=False):
    pending = [d for d in deals if state.is_new(d.key, now, 1440 if group in SLOW_GROUPS else 168)]
    pending.sort(key=lambda d: (-d.pct, d.source, d.name))
    if group == 'hogar':
        pending.sort(key=lambda d: (-d.rank, -d.pct, d.source, d.name))
        # El mismo producto al mismo precio publicado por dos vendedores o tiendas sale una sola vez.
        # Se exige también la misma categoría para no fundir productos distintos de nombre parecido.
        unique, twins = [], {}
        for deal in pending:
            same = (' '.join(deal.name.lower().split()), deal.price, deal.category)
            if same in twins: twins[same].append(deal)
            else: twins[same] = [deal]; unique.append(deal)
        pending = unique
        # Primero las de 80 % o más; el resto alterna las cuatro categorías para que decoración
        # no desplace a muebles o tecnología.
        def alternate(deals):
            buckets, ordered = {}, []
            for deal in deals: buckets.setdefault(deal.category, []).append(deal)
            while any(buckets.values()):
                for category in sorted(buckets):
                    if buckets[category]: ordered.append(buckets[category].pop(0))
            return ordered
        urgent = alternate([d for d in pending if d.pct >= URGENT_HOME_PCT])
        rest = alternate([d for d in pending if d.pct < URGENT_HOME_PCT])
        # Las urgentes van primero pero ocupan como mucho 16 de los 24 cupos si hay otras
        # pendientes: las que no caben siguen en la cola y salen en la ronda siguiente.
        room = 16 if rest else len(urgent)
        pending = urgent[:room] + rest + urgent[room:]
    sent, failed = 0, False
    # Máximo 8 mensajes: una oferta detallada por mensaje de viaje,
    # hasta 3 productos por mensaje de hogar. Nunca marcar lo que no se envió.
    size = 1 if group in ('viajes', *SLOW_GROUPS) else 3
    for start in range(0, min(len(pending), 3 if group in SLOW_GROUPS else size * 8), size):
        batch = pending[start:start + size]
        message = "\n\n──────────\n\n".join(deal_text(d) for d in batch)
        if group == 'viajes' and batch[0].source == 'Diners': message += "\nBeneficio general; para vuelos, confirmar aplicabilidad a salida de Lima."
        # Reducir el lote si excede el límite de ntfy, sin perder ofertas en la memoria.
        while len(message.encode('utf-8')) > 3600 and len(batch) > 1:
            batch = batch[:-1]; message = "\n\n──────────\n\n".join(deal_text(d) for d in batch)
        title = {'hogar': f"🏠 {len(batch)} ofertas de hogar/tecnología", 'comida': f"🛒 {len(batch)} ofertas de comida/bazar",
                 'viajes': "✈️ 1 oferta de viajes", 'autos': "🚗 Oportunidad en autos",
                 'inmuebles': "🏢 Oportunidad en inmuebles"}[group]
        priority = 2 if in_quiet_hours(notifier.cfg.quiet_hours, now) else 4
        if notifier.send(title, message, priority=priority, click=batch[0].url):
            sent += len(batch)
            if not dry_run:
                for deal in batch:
                    state.mark_seen(deal.key, now)
                    # Las copias del mismo producto y precio de otros vendedores quedan avisadas con él:
                    # si no, saldrían en el resumen siguiente.
                    if group == 'hogar':
                        for twin in twins.get((' '.join(deal.name.lower().split()), deal.price, deal.category), [])[1:]:
                            state.mark_seen(twin.key, now)
        else: failed = True
    return sent, failed


def run_group(group, *, dry_run=False, test=False, now=None, scanner=None, notifier=None, state_path=None):
    now = time.time() if now is None else now
    cfg = Config.from_env()
    cfg.ntfy_topic = os.environ.get(TOPICS[group], '').strip() or None
    if cfg.ntfy_topic and not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', cfg.ntfy_topic):
        raise ValueError('El tema de notificaciones no tiene un formato válido')
    # Autos e inmuebles pasan semanas juntando comparables antes de avisar: sin tema todavía,
    # la ronda igual lee y guarda la memoria, pero no envía nada.
    collect_only = not cfg.ntfy_topic and not dry_run and notifier is None and group in SLOW_GROUPS
    if not cfg.ntfy_topic and not dry_run and notifier is None and not collect_only:
        raise ValueError('Falta el secreto del tema de notificaciones de ' + group)
    cfg.min_discount = 50 if group == 'viajes' else 60
    log = logging.getLogger('catalogs')
    privacy = PrivateFormatter(cfg)
    for handler in logging.getLogger().handlers: handler.setFormatter(privacy)
    state_path = state_path or f'state/{group}.json'
    state = CatalogState.load(state_path, log)
    scanner = scanner or {'hogar': scan_home, 'viajes': scan_trips, 'comida': scan_convenience,
                          'autos': scan_autos, 'inmuebles': scan_inmuebles}[group]
    deals, reports = scanner(state, now)
    found = len(deals)
    digest, stats = False, {}
    if group == 'hogar': deals, digest, stats = hold_home(state, deals, now)
    reports = [(name, count, privacy.redact(error) if error else None) for name, count, error in reports]
    if collect_only: log.info('%s: sin tema de ntfy configurado; solo se junta información', group)
    notifier = notifier or Notifier(cfg, HttpClient(), dry_run=dry_run or collect_only, log=log)
    sent, failed = deliver(deals, state, notifier, now, group, dry_run or collect_only)
    if group == 'hogar':
        queue = state.datos.get('cola_hogar', {})
        for key in [k for k, v in queue.items() if not state.is_new(Deal(**v['oferta']).key, now, 168)]: queue.pop(key)
        # Solo un resumen entregado sin fallas mueve el reloj; si ntfy falló, se reintenta en la próxima ronda.
        if digest and not failed and not dry_run: state.datos['ultimo_resumen_hogar'] = int(now)
        log.info('hogar: %d candidatas vistas · %d entraron a la cola · %d descartadas por ahorro menor a S/ %.0f · '
                 '%d por descuento permanente · %d caducaron sin volver a verse · %d recortadas por puntaje bajo · '
                 '%d pendientes (la más antigua, %.1f h)%s',
                 found, stats.get('entradas', 0), stats.get('ahorro bajo', 0), min_savings(),
                 stats.get('descuento permanente', 0), stats.get('caducadas', 0), stats.get('recortadas', 0), len(queue),
                 stats.get('mas_antigua_h', 0),
                 ' · resumen enviado' if digest and not failed else '')
    for name, count, error in reports:
        log.info('%s: %d revisados · %s', name, count, error or 'OK')
    log.info("%s: %d ofertas cumplen el mínimo; %d enviadas", group, found, sent)
    problems = [name for name, count, error in reports if state.record_result(name, not error) >= 3]
    if problems and state.can_notify_failure(now) and not dry_run and not collect_only:
        if notifier.send('⚠️ Monitor de ' + group + ': revisión incompleta',
                         'No se pudo revisar: ' + ', '.join(problems) + '. Consulta GitHub Actions.', priority=3):
            state.last_failure_notice = int(now)
        else: failed = True
    if test:
        lines = ([f"{len(deals)} oportunidades · {sent} enviadas. Las primeras semanas solo junta comparables."]
                 if group in SLOW_GROUPS else [f"Mínimo: {cfg.min_discount}% · {found} ofertas válidas · {sent} enviadas" + (" ahora (el resto va en el resumen cada 3 horas)." if group == "hogar" else ".")])
        lines += [f"{'⚠️' if error else '✅'} {name}: {error or str(count) + ' revisados'}" for name, count, error in reports]
        lines.append(UNAVAILABLE[group])
        if group == 'viajes': lines.append('Diners: descuentos explícitos de 50%. JetSMART/SKY: caídas de 50% del precio publicado desde Lima, frente al mínimo observado en al menos 3 días previos (ventana de 30 días), o 50% bajo lo normal por kilómetro en su tramo de distancia (con al menos 20 tarifas del tramo). Al inicio solo se construye historial. No son tarifas garantizadas en vivo; revisar tasas y equipaje.')
        if not notifier.send('🧪 Prueba de ' + TITLES[group], '\n'.join(lines), priority=3): failed = True
    state.prune(now, 24 * 60 if group in SLOW_GROUPS else 336)
    if not dry_run: state.save(state_path, now)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write(f"### {group}\n\nUmbral: {cfg.min_discount}% · Ofertas: {found} · Enviadas: {sent}\n\n")
            for name, count, error in reports: f.write(f"- {name}: {count} revisados; {error or 'OK'}\n")
            f.write('\nFuentes no activadas: ' + UNAVAILABLE[group] + '\n\n')
    # Una revisión incompleta cuenta para el aviso al celular (3 seguidas), pero no vuelve roja la ronda.
    return 1 if failed or any(error and not error.startswith(INCOMPLETE) for _, _, error in reports) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--grupo', choices=list(TOPICS), required=True)
    parser.add_argument('--sin-enviar', action='store_true')
    parser.add_argument('--prueba', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    try:
        return run_group(args.grupo, dry_run=args.sin_enviar,
                         test=args.prueba or os.environ.get('MODO_PRUEBA') == 'si')
    except Exception as exc:
        logging.error('No se pudo ejecutar el monitor (%s). Revisar configuración y fuentes.', type(exc).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

"""Relectura acotada de catálogos públicos antes de notificar ofertas acumuladas."""
from dataclasses import asdict, replace
from urllib.parse import urlsplit, parse_qs
from urllib.robotparser import RobotFileParser
from .http import HttpClient

MAX_PAGES = 8
MAX_REQUESTS = 16
MAX_CONFIRMED = 24


def allowed_url(deal):
    from .catalogs import RETAIL_SOURCES
    from .vtex import SOURCES, PATH
    url = deal.check_url
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.fragment: return False
    if deal.source in dict(SOURCES):
        return url == 'https://' + dict(SOURCES)[deal.source] + PATH
    for source, category, base in RETAIL_SOURCES:
        if source != deal.source or category != deal.category: continue
        base_parts = urlsplit(base)
        query = parse_qs(parsed.query)
        if parsed.netloc != base_parts.netloc or parsed.path != base_parts.path: continue
        if set(query) - {'f.range.derived.variant.discount', 'page'}: continue
        if query.get('f.range.derived.variant.discount') != ['60% dcto y más']: continue
        if 'page' in query and (len(query['page']) != 1 or not query['page'][0].isdigit()): continue
        return True
    return False


def validate(selected, state, now, observations, reports, http_factory=HttpClient):
    from .catalogs import retail_products, quality, home_notice_key
    from .vtex import parse_products
    queue = state.datos.setdefault('cola_hogar', {})
    current = {d.history_key: d for d in observations}
    clients, rules, cache = {}, {}, {}
    unavailable = {name.split('/')[0] for name, _, error in reports if error}
    stats = dict(confirmadas_ronda=0, revalidadas=0, cambiadas=0, no_confirmadas=0,
                 errores_fuente=0, paginas_releidas=0, consultas_extra=0, consideradas=0, equivalentes_omitidas=0)
    accepted, accepted_keys = [], set()

    def fetch(client, url):
        # Incluye los reintentos internos del cliente en el presupuesto global.
        spent = sum(getattr(c, 'requests_made', 0) for c in clients.values())
        if spent >= MAX_REQUESTS: raise ValueError('Presupuesto de revalidación agotado')
        client.max_requests = getattr(client, 'requests_made', 0) + MAX_REQUESTS - spent
        stats['consultas_extra'] += 1
        return client.get(url)

    for old in selected:
        if len(accepted) >= MAX_CONFIRMED: break
        stats['consideradas'] += 1
        if home_notice_key(old) in accepted_keys:
            stats['equivalentes_omitidas'] += 1
            continue  # conservar alternativas hasta confirmar una; después no gastar red
        fresh = current.get(old.history_key)
        from_round = fresh is not None
        if fresh is None and allowed_url(old) and old.source not in unavailable:
            url = old.check_url
            host = urlsplit(url).netloc
            if url not in cache and stats['paginas_releidas'] < MAX_PAGES:
                cache[url] = []
                try:
                    if host not in clients: clients[host] = http_factory(delay=1.5, timeout=20, max_requests=MAX_REQUESTS)
                    client = clients[host]
                    if host not in rules:
                        robots = fetch(client, 'https://' + host + '/robots.txt') or ''
                        if 'user-agent:' not in robots.lower(): raise ValueError('robots no verificable')
                        robot = RobotFileParser(); robot.parse(robots.splitlines()); rules[host] = robot
                    if not rules[host].can_fetch(client.user_agent, url):
                        unavailable.add(old.source)
                    else:
                        stats['paginas_releidas'] += 1
                        raw = fetch(client, url)
                        if raw is not None:
                            if old.source in ('Falabella', 'Sodimac'):
                                found, _, _ = retail_products(raw, old.source, old.category)
                            else:
                                found, _ = parse_products(raw, old.source, host)
                            cache[url] = found
                except Exception:
                    # También si fue 403/429: nunca volver a consultar la fuente en esta ronda.
                    unavailable.add(old.source)
                    stats['errores_fuente'] += 1
            fresh = next((d for d in cache.get(url, []) if d.history_key == old.history_key), None)
        if fresh is None:
            stats['no_confirmadas'] += 1
            continue  # no estar en esa página no demuestra agotamiento; esperar nueva observación
        fresh = replace(fresh, check_url=fresh.check_url or old.check_url)
        state.observe(fresh, now)
        fresh.rank, fresh.note, reason = quality(state, fresh, now)
        changed = fresh.price != old.price or fresh.pct < 60 or fresh.currency != old.currency
        if changed or reason:
            stats['cambiadas'] += 1
            queue.pop(old.history_key, None)
            if not reason and fresh.pct >= 60:
                queue[fresh.history_key] = {'oferta': asdict(fresh), 'visto': int(now)}
            continue  # reevaluar el precio nuevo en la próxima ronda, nunca enviar el anterior
        queue[fresh.history_key] = {'oferta': asdict(fresh), 'visto': int(now)}
        fresh.note = '\n'.join(filter(None, [fresh.note, 'Precio observado en esta ronda; disponibilidad final en la tienda']))
        identity = home_notice_key(fresh)
        if identity in accepted_keys:
            stats['equivalentes_omitidas'] += 1
            continue
        accepted_keys.add(identity)
        accepted.append(fresh)
        stats['confirmadas_ronda' if from_round else 'revalidadas'] += 1
    stats['consultas_extra'] = max(stats['consultas_extra'], sum(getattr(c, 'requests_made', 0) for c in clients.values()))
    stats['fuentes_sin_relectura'] = sorted(unavailable)
    stats['cupo_completo'] = len(accepted) >= MAX_CONFIRMED
    return accepted, stats


def record_metrics(state, now, stats, sent, failed):
    """Totales diarios de rondas (no productos únicos diarios), conservados 28 días."""
    day = int(now // 86400)
    data = state.datos.setdefault('metricas_hogar', {})
    for key in list(data):
        if int(key) < day - 27: data.pop(key)
    row = data.setdefault(str(day), {})
    values = dict(stats, enviadas=sent, rondas=1, rondas_con_fallo_envio=int(failed))
    for key, value in values.items():
        if key in ('pendientes', 'mas_antigua_h'): continue
        if isinstance(value, (int, float)): row[key] = row.get(key, 0) + value
    queue = state.datos.get('cola_hogar', {})
    row['pendientes_final'] = len(queue)
    row['edad_maxima_h'] = round(max(((now-v['visto'])/3600 for v in queue.values()), default=0), 2)
    state.datos['ultima_ronda_hogar'] = dict(values, pendientes_final=len(queue), momento=int(now))

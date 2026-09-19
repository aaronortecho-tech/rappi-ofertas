from monitor.catalogs import CatalogState, Deal, run_group
from monitor.config import Config

NOW = 1789689600


def item(n, pct=65, price=100.0):
    return Deal('Falabella', f'sku{n}', f'Producto {n}', f'https://www.falabella.com.pe/{n}', pct, price, 400.0,
                'Tienda', 'Precio web; confirmar stock y envío', 'Muebles')


class Phone:
    cfg = Config()
    def __init__(self): self.messages = []
    def send(self, title, message, **kw):
        self.messages.append(message); return True


def run(path, when, deals, phone):
    return run_group('hogar', now=when, scanner=lambda s, n: (list(deals), []), notifier=phone, state_path=path)


def test_summary_every_three_hours_urgent_now_and_nothing_lost(tmp_path, monkeypatch):
    monkeypatch.setenv('NTFY_TOPIC_HOGAR', 'tema-de-prueba')
    path = str(tmp_path / 'hogar.json')
    phone = Phone()
    run(path, NOW, [item(1)], phone)                       # primer resumen: sale de inmediato
    assert sum('Producto 1' in m for m in phone.messages) == 1
    phone.messages.clear()
    run(path, NOW + 1800, [item(1), item(2), item(3, pct=85)], phone)
    text = '\n'.join(phone.messages)
    assert 'Producto 3' in text and 'Producto 2' not in text and 'Producto 1' not in text   # solo la urgente
    phone.messages.clear()
    run(path, NOW + 2 * 3600, [item(2, price=90.0)], phone)  # reaparece más barato: queda el último precio
    assert phone.messages == []
    run(path, NOW + 3 * 3600 + 60, [], phone)               # resumen: sale aunque esta ronda no la haya visto
    text = '\n'.join(phone.messages)
    assert 'Producto 2' in text and 'S/ 90.00' in text and 'S/ 100.00' not in text and 'Producto 3' not in text


def test_what_does_not_fit_waits_for_the_next_summary(tmp_path, monkeypatch):
    monkeypatch.setenv('NTFY_TOPIC_HOGAR', 'tema-de-prueba')
    path = str(tmp_path / 'hogar.json')
    phone = Phone()
    many = [item(n, pct=60 + n % 15) for n in range(30)]
    run(path, NOW, many, phone)
    first = sum(m.count('🛒') for m in phone.messages)
    assert first == 24
    state = CatalogState.load(path)
    assert len(state.datos['cola_hogar']) == 6              # guardadas en la memoria, no perdidas
    phone.messages.clear()
    run(path, NOW + 3 * 3600 + 60, many, phone)
    assert sum(m.count('🛒') for m in phone.messages) == 6


def test_same_product_turning_urgent_keeps_only_the_latest_price(tmp_path, monkeypatch):
    monkeypatch.setenv('NTFY_TOPIC_HOGAR', 'tema-de-prueba')
    path = str(tmp_path / 'hogar.json')
    phone = Phone()
    run(path, NOW, [item(9)], phone)                         # primer resumen (vacía la cola inicial)
    phone.messages.clear()
    run(path, NOW + 1800, [item(1, pct=65, price=100.0)], phone)
    run(path, NOW + 3600, [item(1, pct=85, price=60.0)], phone)   # pasa a urgente: sale al momento
    run(path, NOW + 4 * 3600, [], phone)                     # resumen siguiente: el precio viejo no sale
    text = '\n'.join(phone.messages)
    assert text.count('Producto 1') == 1 and 'S/ 60.00' in text and 'S/ 100.00' not in text


def test_urgent_overflow_is_kept_and_sent_next_round(tmp_path, monkeypatch):
    monkeypatch.setenv('NTFY_TOPIC_HOGAR', 'tema-de-prueba')
    path = str(tmp_path / 'hogar.json')
    phone = Phone()
    run(path, NOW, [item(n, pct=85) for n in range(30)], phone)
    assert sum(m.count('🛒') for m in phone.messages) == 24
    phone.messages.clear()
    run(path, NOW + 1800, [], phone)                         # no reaparecen, igual salen: estaban guardadas
    assert sum(m.count('🛒') for m in phone.messages) == 6


def test_failed_summary_is_retried_next_round_and_says_when_it_was_seen(tmp_path, monkeypatch):
    monkeypatch.setenv('NTFY_TOPIC_HOGAR', 'tema-de-prueba')
    path = str(tmp_path / 'hogar.json')

    class Down(Phone):
        def send(self, *a, **k): return False

    assert run(path, NOW, [item(1)], Down()) == 1
    phone = Phone()
    run(path, NOW + 1800, [], phone)                         # el reloj no avanzó: reintenta ya
    assert any('Producto 1' in m for m in phone.messages)
    phone = Phone()
    run(path, NOW + 1800, [item(2)], phone)
    run(path, NOW + 1800 + 3 * 3600 + 60, [], phone)
    assert any('Visto hace 3 h' in m for m in phone.messages)


def test_quality_filter_and_ranking():
    from monitor.catalogs import hold_home, quality
    state = CatalogState()
    day = int(NOW // 86400)
    # Descuento permanente: el mismo precio siete días seguidos.
    fixed = item(1, pct=70, price=100.0)
    state.history[fixed.history_key] = [[day - d, 100.0] for d in range(7, 0, -1)]
    assert quality(state, fixed, NOW)[2] == 'descuento permanente'
    # Con menos de siete días todavía no se concluye nada.
    state.history[fixed.history_key] = [[day - d, 100.0] for d in range(3, 0, -1)]
    assert quality(state, fixed, NOW)[2] is None
    # Ahorro menor a S/ 20: un cojín de S/ 30 a S/ 12 no entra.
    cushion = Deal('Falabella', 'c', 'Cojín', 'https://x/c', 60, 12.0, 30.0, 'T', 'Precio web; confirmar stock y envío', 'Hogar')
    assert quality(state, cushion, NOW)[2] == 'ahorro bajo'
    # Nuevo mínimo: bajó frente a lo observado antes; sube en el orden y lo dice.
    low = item(2, pct=60, price=150.0)
    state.history[low.history_key] = [[day - 2, 200.0], [day - 1, 190.0]]
    rank_low, note, reason = quality(state, low, NOW)
    assert reason is None and 'Precio más bajo visto en 2 días (antes S/ 190.00)' in note
    # A igual porcentaje, manda el ahorro en soles.
    sofa = Deal('Falabella', 's', 'Sofá', 'https://x/s', 60, 800.0, 2000.0, 'T', 'Precio web; confirmar stock y envío', 'Muebles')
    lamp = Deal('Falabella', 'l', 'Lámpara', 'https://x/l', 62, 20.0, 60.0, 'T', 'Precio web; confirmar stock y envío', 'Hogar')
    assert quality(state, sofa, NOW)[0] > quality(state, lamp, NOW)[0]
    due, digest, stats = hold_home(state, [fixed, cushion, low, sofa, lamp], NOW)
    assert digest and [d.name for d in sorted(due, key=lambda d: -d.rank)][0] == 'Producto 2'
    assert stats['ahorro bajo'] == 1 and len(state.datos['cola_hogar']) == 4


def test_permanent_discount_leaves_the_queue_and_is_never_urgent(tmp_path, monkeypatch):
    monkeypatch.setenv('NTFY_TOPIC_HOGAR', 'tema-de-prueba')
    path = str(tmp_path / 'hogar.json')
    state = CatalogState()
    deal = item(5, pct=85, price=100.0)
    day = int(NOW // 86400)
    state.history[deal.history_key] = [[day - d, 100.0] for d in range(7, 0, -1)]
    state.save(path, NOW - 60)
    phone = Phone()
    run(path, NOW, [deal], phone)
    assert not any('Producto 5' in m for m in phone.messages)


def test_same_product_same_price_from_two_sellers_goes_once():
    from monitor.catalogs import deliver
    a = item(1)
    b = Deal('Sodimac', 'sku1', 'Producto  1', 'https://www.sodimac.com.pe/1', 65, 100.0, 400.0, 'Otra', 'Precio web; confirmar stock y envío', 'Muebles')
    phone = Phone()
    deliver([a, b], CatalogState(), phone, NOW, 'hogar')
    assert '\n'.join(phone.messages).count('🛒') == 1


def test_queue_keeps_only_the_best_300_and_never_drops_urgent(monkeypatch):
    import monitor.catalogs as catalogs
    from monitor.catalogs import hold_home
    monkeypatch.setattr(catalogs, 'QUEUE_MAX', 5)
    state = CatalogState()
    state.datos['ultimo_resumen_hogar'] = NOW
    deals = [item(n, pct=60, price=100.0 - n) for n in range(8)] + [item(99, pct=85, price=100.0)]
    deals.append(Deal('Falabella', 'big', 'Televisor', 'https://x/tv', 60, 1000.0, 2500.0, 'T', 'Precio web; confirmar stock y envío', 'Tecnología'))
    _, _, stats = hold_home(state, deals, NOW + 60)
    names = {v['oferta']['name'] for v in state.datos['cola_hogar'].values()}
    # Cinco no urgentes (las mejores por puntaje) más la urgente, que queda fuera del límite.
    assert len(names) == 6 and 'Producto 99' in names and 'Televisor' in names and stats['recortadas'] == 4


def test_more_urgent_than_the_cap_are_all_kept(monkeypatch):
    import monitor.catalogs as catalogs
    from monitor.catalogs import hold_home
    monkeypatch.setattr(catalogs, 'QUEUE_MAX', 5)
    state = CatalogState()
    due, _, stats = hold_home(state, [item(n, pct=85) for n in range(8)], NOW)
    assert len(due) == 8 and stats['recortadas'] == 0


def test_seller_twin_is_not_sent_in_the_next_summary():
    from monitor.catalogs import deliver
    a = item(1)
    b = Deal('Sodimac', 'sku1', 'Producto  1', 'https://www.sodimac.com.pe/1', 65, 100.0, 400.0, 'Otra',
             'Precio web; confirmar stock y envío', 'Muebles')
    state = CatalogState()
    assert deliver([a, b], state, Phone(), NOW, 'hogar') == (1, False)
    assert deliver([a, b], state, Phone(), NOW + 3 * 3600, 'hogar') == (0, False)
    # Otra categoría no se funde: puede ser un producto distinto con el mismo nombre.
    c = Deal('Sodimac', 'c', 'Producto 1', 'https://x/c', 65, 100.0, 400.0, 'Otra', 'Precio web; confirmar stock y envío', 'Hogar')
    assert deliver([c], state, Phone(), NOW + 6 * 3600, 'hogar') == (1, False)

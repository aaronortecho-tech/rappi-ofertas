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

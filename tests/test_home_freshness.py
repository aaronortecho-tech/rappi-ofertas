from dataclasses import asdict, replace

import pytest

from monitor.catalogs import CatalogState, Deal, hold_home, run_group
from monitor.config import Config

NOW = 1789849858


def item(identity, **changes):
    return replace(Deal('Falabella', identity, f'Producto {identity}',
                        f'https://example.org/{identity}', 60, 100., 250.,
                        'A', 'Precio web', 'Muebles'), **changes)


def memory(deals):
    state = CatalogState()
    state.datos['cola_hogar'] = {
        d.history_key: {'oferta': asdict(d), 'visto': NOW-3600} for d in deals}
    state.datos['ultimo_resumen_hogar'] = NOW-10800
    return state


class Phone:
    cfg = Config()
    def __init__(self): self.messages = []
    def send(self, title, message, **kwargs):
        self.messages.append(message)
        return True


def test_urgent_alone_does_not_postpone_normal_summary(tmp_path):
    normal, urgent = item('normal'), item('urgent', pct=80, regular=500.)
    state = memory([normal])
    state.history[urgent.history_key] = [[NOW//86400-i, 200.] for i in (1, 2, 3)]
    path = tmp_path/'home.json'; state.save(path, NOW-60)
    phone = Phone()
    run_group('hogar', now=NOW, scanner=lambda s,n: ([urgent], []), notifier=phone, state_path=path)
    saved = CatalogState.load(path)
    assert len(phone.messages) == 1 and 'Producto urgent' in phone.messages[0]
    assert saved.datos['ultimo_resumen_hogar'] == NOW-10800
    assert saved.datos['ultima_ronda_hogar']['normales_enviadas'] == 0
    assert saved.datos['ultima_ronda_hogar']['urgentes_enviadas'] == 1
    phone.messages.clear()
    run_group('hogar', now=NOW+1800, scanner=lambda s,n: ([normal], []), notifier=phone, state_path=path)
    assert len(phone.messages) == 1 and 'Producto normal' in phone.messages[0]
    assert CatalogState.load(path).datos['ultimo_resumen_hogar'] == NOW+1800


@pytest.mark.parametrize('dry_run,ok', [(True, True), (False, False)])
def test_uncommitted_normal_delivery_does_not_advance_clock(tmp_path, dry_run, ok):
    normal = item('normal'); state = memory([])
    path = tmp_path/'home.json'; state.save(path, NOW-60)
    class Sink(Phone):
        def send(self, *args, **kwargs): return ok
    run_group('hogar', now=NOW, scanner=lambda s,n: ([normal], []), notifier=Sink(),
              state_path=path, dry_run=dry_run)
    assert CatalogState.load(path).datos['ultimo_resumen_hogar'] == NOW-10800


def test_current_candidate_survives_full_stale_queue_and_is_sent(tmp_path):
    old = [item(f'old{i}', pct=90, regular=1000.) for i in range(300)]
    fresh = item('fresh')
    path = tmp_path/'home.json'; memory(old).save(path, NOW-60)
    phone = Phone()
    run_group('hogar', now=NOW, scanner=lambda s,n: ([fresh], []), notifier=phone, state_path=path)
    saved = CatalogState.load(path); stats = saved.datos['ultima_ronda_hogar']
    assert len(phone.messages) == 1 and 'Producto fresh' in phone.messages[0]
    assert stats['recientes_rescatadas'] == 1
    assert stats['observadas_ronda_enviadas'] == 1 and stats['consultas_extra'] == 0
    assert len(saved.datos['cola_hogar']) == 299


def test_fresh_reserve_preserves_categories_and_historical_priority(monkeypatch):
    import monitor.catalogs as catalogs
    monkeypatch.setattr(catalogs, 'QUEUE_MAX', 12)
    categories = ['Muebles', 'Hogar', 'Tecnología', 'Electrodomésticos']
    old = [item(f'{cat}{i}', category=cat, pct=90, regular=1000.)
           for cat in categories for i in range(6)]
    backed = [item(f'backed{cat}', category=cat) for cat in categories]
    fresh = [item(f'fresh{cat}', category=cat) for cat in categories]
    state = memory(old+backed)
    for d in backed: state.history[d.history_key] = [[NOW//86400-i, 200.] for i in (1,2,3)]
    _, _, stats = hold_home(state, fresh, NOW)
    queue = state.datos['cola_hogar']
    assert len(queue) == 12 and stats['recientes_rescatadas'] == 4
    for cat in categories:
        assert sum(v['oferta']['category'] == cat for v in queue.values()) == 3
    assert all(d.history_key in queue for d in backed+fresh)


def test_historical_candidates_take_precedence_over_fresh_reserve(monkeypatch):
    import monitor.catalogs as catalogs
    monkeypatch.setattr(catalogs, 'QUEUE_MAX', 3)
    backed = [item(f'backed{i}') for i in range(3)]
    state = memory(backed)
    for d in backed: state.history[d.history_key] = [[NOW//86400-i, 200.] for i in (1,2,3)]
    hold_home(state, [item('fresh')], NOW)
    assert set(state.datos['cola_hogar']) == {d.history_key for d in backed}

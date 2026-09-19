from dataclasses import replace

import pytest

from monitor.catalogs import CatalogState, Deal, deliver, hold_home, home_notice_key, run_group
from monitor.config import Config

NOW = 1789689600


def offer(**changes):
    return replace(Deal('Falabella', 'sku123', 'Televisor Samsung UN55CU7000 negro',
                        'https://example.org/a', 85, 100., 700., 'A',
                        'Precio web; confirmar stock y envío', 'Tecnología'), **changes)


class Phone:
    cfg = Config()
    def __init__(self, ok=True): self.ok, self.messages = ok, []
    def send(self, title, message, **kw):
        self.messages.append(message)
        return self.ok


def test_later_seller_is_suppressed_after_reload_and_leaves_queue(tmp_path):
    path = tmp_path / 'home.json'
    a, b = offer(), offer(source='Sodimac', identity='different', seller='B')
    assert run_group('hogar', now=NOW, scanner=lambda s,n: ([a], []), notifier=Phone(), state_path=path) == 0
    phone = Phone()
    assert run_group('hogar', now=NOW+1800, scanner=lambda s,n: ([b], []), notifier=phone, state_path=path) == 0
    assert phone.messages == []
    assert not CatalogState.load(path).datos['cola_hogar']


@pytest.mark.parametrize('changes', [
    {'condition': 'Requiere tarjeta CMR'}, {'currency': 'USD'}, {'price': 90.},
    {'name': 'Televisor Samsung UN55CU7000 blanco'}, {'category': 'Otra'},
])
def test_conditions_currency_price_and_variant_remain_distinct(changes):
    a, b = offer(), offer(source='Sodimac', seller='B', **changes)
    state = CatalogState()
    assert deliver([a], state, Phone(), NOW, 'hogar') == (1, False)
    assert deliver([b], state, Phone(), NOW+1800, 'hogar') == (1, False)


def test_cmr_cannot_hide_unrestricted_price_in_same_batch():
    a = offer(condition='Requiere tarjeta CMR')
    b = offer(source='Sodimac', seller='B')
    phone = Phone()
    assert deliver([a,b], CatalogState(), phone, NOW, 'hogar') == (2, False)
    assert '\n'.join(phone.messages).count('🛒') == 2


def test_generic_names_require_shared_sku():
    a = offer(name='Mesa')
    b = offer(name='Mesa', source='Sodimac', identity='other', seller='B')
    assert home_notice_key(a) != home_notice_key(b)
    assert home_notice_key(a) == home_notice_key(replace(b, identity=a.identity))
    assert deliver([a,b], CatalogState(), Phone(), NOW, 'hogar') == (2, False)


def test_failure_and_dry_run_do_not_suppress_alternatives():
    a, b = offer(), offer(source='Sodimac', identity='other', seller='B')
    for ok, dry in [(False, False), (True, True)]:
        state = CatalogState()
        deliver([a], state, Phone(ok), NOW, 'hogar', dry_run=dry)
        assert not state.seen
        assert deliver([b], state, Phone(), NOW+1800, 'hogar') == (1, False)


def test_shared_reference_expires_and_rank_or_list_price_does_not_realert():
    state = CatalogState()
    a = offer()
    deliver([a], state, Phone(), NOW, 'hogar')
    b = offer(source='Sodimac', identity='other', seller='B', pct=90, regular=1000., rank=999, note='Otra nota')
    assert deliver([b], state, Phone(), NOW+1800, 'hogar') == (0, False)
    assert deliver([b], state, Phone(), NOW+168*3600, 'hogar') == (1, False)


def test_current_seller_survives_unverifiable_equivalent(tmp_path):
    from dataclasses import asdict
    old = offer(check_url='')
    fresh = offer(source='Sodimac', seller='B', url='https://example.org/fresh')
    state = CatalogState()
    state.datos['cola_hogar'] = {old.history_key: {'oferta': asdict(old), 'visto': NOW-3600}}
    path = tmp_path/'home.json'; state.save(path, NOW-60)
    phone = Phone()
    assert run_group('hogar', now=NOW, scanner=lambda s,n: ([fresh], []),
                     notifier=phone, state_path=path) == 0
    assert len(phone.messages) == 1 and fresh.url in phone.messages[0]
    saved = CatalogState.load(path)
    assert saved.datos['ultima_ronda_hogar']['enviadas'] == 1
    assert saved.datos['ultima_ronda_hogar']['consultas_extra'] == 0
    assert not saved.datos['cola_hogar']


def test_long_batches_send_every_product_without_skipping():
    deals = [offer(identity=str(i), name=f'Producto {i} ' + 'x'*1400) for i in range(6)]
    phone, state = Phone(), CatalogState()
    assert deliver(deals, state, phone, NOW, 'hogar') == (6, False)
    assert len(phone.messages) == 3
    assert all(len(m.encode('utf-8')) <= 3600 for m in phone.messages)
    for i, deal in enumerate(deals):
        assert '\n'.join(phone.messages).count(f'Producto {i} ') == 1
        assert not state.is_new(deal.key, NOW, 168)


def test_long_batches_keep_eight_message_limit_and_unsent_memory():
    deals = [offer(identity=str(i), name=f'Producto {i:02} ' + 'x'*2000) for i in range(24)]
    phone, state = Phone(), CatalogState()
    assert deliver(deals, state, phone, NOW, 'hogar') == (8, False)
    assert len(phone.messages) == 8
    assert sum(not state.is_new(d.key, NOW, 168) for d in deals) == 8


def test_failed_long_batch_remains_unseen_without_skipping_later_products():
    deals = [offer(identity=str(i), name=f'Producto {i} ' + 'x'*1400) for i in range(6)]
    class FailsOnce(Phone):
        def send(self, title, message, **kw):
            self.messages.append(message)
            return len(self.messages) != 1
    phone, state = FailsOnce(), CatalogState()
    assert deliver(deals, state, phone, NOW, 'hogar') == (4, True)
    assert len(phone.messages) == 3
    assert all(state.is_new(d.key, NOW, 168) for d in deals[:2])
    assert all(not state.is_new(d.key, NOW, 168) for d in deals[2:])

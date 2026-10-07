from dataclasses import replace
import pytest
from monitor.catalogs import CatalogState, Deal
from monitor.flight_value import observe_route, route_key, savings, prune_routes

NOW = 1789689600

def fare(identity='target', depart='2026-10-19', price=250):
    return Deal('Test','id-'+identity,'Lima a Cusco','https://example.com',0,price,price,
                currency='PEN', reference_kind='flight_history',
                flight_context={'depart':depart,'destination':'CUZ','airline':'XX',
                                'service':'economy-basic','taxes':'included','stops':0})

@pytest.mark.parametrize('p,r,c,expected', [(300,400,'PEN',25),(300.01,400,'PEN',None),
    (60,80,'PEN',None),(75,100,'USD',25),(75.01,100,'USD',None),(10,400,'PEN',None)])
def test_savings_boundaries(p,r,c,expected):
    assert savings(p,r,c) == expected

def seed(state, days=3, dates=5):
    for offset in range(days,0,-1):
        for i in range(dates):
            observe_route(state,fare(str(i),f'2026-10-{12+i:02}',400),NOW-offset*86400)

def test_route_requires_prior_days_and_independent_dates():
    state=CatalogState(); seed(state,days=2)
    assert observe_route(state,fare(),NOW) is None
    state=CatalogState(); seed(state,dates=4)
    assert observe_route(state,fare(),NOW) is None
    state=CatalogState(); seed(state)
    alert=observe_route(state,fare(),NOW)
    assert alert.regular == 400 and alert.pct == 37 and alert.reference_kind == 'flight_route'
    assert observe_route(state,fare(price=250),NOW+8*86400) is None
    prune_routes(state,NOW+40*86400)
    assert not state.datos['rutas_vuelos_v2']

@pytest.mark.parametrize('field,value', [('destination','BOG'),('airline','YY'),('service','business'),
    ('taxes','extra'),('stops',1),('depart','2026-11-19'),('back','2026-10-25')])
def test_route_does_not_mix_conditions(field,value):
    original=fare(); changed=replace(original,flight_context={**original.flight_context,field:value})
    assert route_key(original,NOW) != route_key(changed,NOW)
    assert route_key(original,NOW) != route_key(replace(original,currency='USD'),NOW)

def test_unknown_stops_cannot_be_assumed_direct():
    deal=fare(); deal.flight_context['stops']=None
    assert route_key(deal,NOW) is None

import json
from pathlib import Path
import pytest
from monitor.convenience import discount, tambo_products, makro_products, scan_convenience
from monitor.catalogs import CatalogState, Deal, deal_text, run_group
from monitor.config import Config
from monitor.http import Blocked

FIX = Path(__file__).parent / 'fixtures'

@pytest.mark.parametrize('p,r,expected', [(40,100,(40,100,60)),(40.01,100,None),
    (0,100,None),(10,200,None),('NaN',100,None),(1,None,None),(True,100,None)])
def test_discount_filters(p,r,expected):
    assert discount(p,r) == expected

def test_real_catalogs_and_tambo_unavailable():
    html = (FIX/'tambo.html').read_text(encoding='utf-8')
    assert tambo_products(html)[1] == 5
    payload = json.JSONDecoder().raw_decode(html.split(' = ',1)[1])[0]
    rows = payload['state']['loaderData']['pages/Order/Layout/index']['menuData']['products']
    first = next(iter(rows.values()))
    first['availabilityAt'].update(finalPrice=20,basePrice=100)
    build = lambda: '<script>window.__remixContext = '+json.dumps(payload)+';</script>'
    assert tambo_products(build())[0][0].pct == 80
    first['availabilityAt']['available'] = False
    assert not tambo_products(build())[0]
    assert makro_products((FIX/'makro.json').read_text(encoding='utf-8'))[1] == 5

def test_makro_pack_stock_and_electro_exclusion():
    rows = json.loads((FIX/'makro.json').read_text(encoding='utf-8'))[:1]
    offer = rows[0]['items'][0]['sellers'][0]['commertialOffer']
    offer.update(Price=20,ListPrice=100,AvailableQuantity=10,IsAvailable=True)
    deals,_ = makro_products(json.dumps(rows))
    assert len(deals)==1 and 'presentación' in deals[0].condition
    offer['AvailableQuantity']=0
    assert not makro_products(json.dumps(rows))[0]
    offer['AvailableQuantity']=10;rows[0]['categories']=['/Electrohogar/']
    assert not makro_products(json.dumps(rows))[0]

def test_block_does_not_retry_site_and_other_source_continues():
    calls=[]
    class HTTP:
        user_agent='Mozilla/5.0'
        def __init__(self,**kw):pass
        def get(self,url):
            calls.append(url)
            if 'tambo' in url:raise Blocked('403')
            if url.endswith('robots.txt'):return 'User-agent: *\nDisallow: /checkout'
            return (FIX/'makro.json').read_text(encoding='utf-8')
    _,reports=scan_convenience(CatalogState(),1,HTTP)
    assert reports[0][2] and reports[1][1]==5 and not reports[1][2]
    assert len(calls)==3

def test_mobile_layout_preserves_conditions():
    text=deal_text(Deal('Makro','1','Pack de agua','https://example.com',60,20,50,'Makro','Compra mínima 2 packs'))
    assert text.splitlines()[:3]==['🛒 Pack de agua','💰 S/ 20.00  |  -60%','Antes (publicado): S/ 50.00']
    assert 'Compra mínima 2 packs' in text and '**' not in text

def test_food_uses_original_topic_and_separate_memory(monkeypatch,tmp_path):
    monkeypatch.setenv('NTFY_TOPIC','prueba-comida')
    class Notifier:
        cfg=Config();sent=[]
        def send(self,title,message,**kw):self.sent.append((title,message));return True
    n=Notifier()
    assert run_group('comida',test=True,notifier=n,state_path=tmp_path/'comida.json',
        scanner=lambda state,now:([],[('Tambo',5,None)]))==0
    assert 'Comida y bazar' in n.sent[-1][0] and '60%' in n.sent[-1][1]

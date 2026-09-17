from conftest import fixture_json, fixture_text

from monitor.config import Config
from monitor.parsers import (
    chain_restaurants,
    discount_pct,
    extract_next_data,
    parse_restaurant_live,
    parse_restaurant_page,
    parse_store_page,
    restaurant_candidates,
    store_links,
)
from monitor.scan import good_offers


def by_id(offers):
    return {offer.product_id: offer for offer in offers}


def test_discount_pct_rounding_and_edge_cases():
    assert discount_pct(29.9, 99.8) == 70
    assert discount_pct(269.91, 779.4) == 65
    assert discount_pct(0, 10) == 100
    assert discount_pct(10, 10) == 0
    assert discount_pct(12, 10) == 0
    assert discount_pct(None, 10) == 0
    assert discount_pct(5, 0) == 0
    assert discount_pct(-1, 10) == 0


def test_extract_next_data_handles_garbage():
    assert extract_next_data(None) is None
    assert extract_next_data("<html>sin datos</html>") is None
    assert extract_next_data('<script id="__NEXT_DATA__" type="application/json">{roto</script>') is None
    data = extract_next_data(fixture_text("store_ofertas_wong.html"))
    assert data["page"] == "/ssg/[friendly_url]/[aisle_friendly_url]"


def test_store_page_offers():
    name, offers = parse_store_page(extract_next_data(fixture_text("store_ofertas_wong.html")))
    assert name == "Wong"
    offers = by_id(offers)
    assert set(offers) == {"2093144566", "2093144571", "1074119052", "1074120650", "9999999999"}
    assert offers["2093144566"].pct == 65
    assert offers["2093144566"].price == 269.91
    assert offers["2093144566"].regular_price == 779.4
    assert offers["1074120650"].pct == 54
    assert offers["9999999999"].available is False


def test_good_offers_filters_threshold_availability_and_pro():
    _, offers = parse_store_page(extract_next_data(fixture_text("store_ofertas_wong.html")))
    cfg = Config()
    assert [offer.pct for offer in good_offers(offers, cfg)] == [65]
    cfg.min_discount = 50
    assert [offer.pct for offer in good_offers(offers, cfg)] == [65, 54]


def test_store_links_are_unique_and_ignore_other_links():
    links = store_links(fixture_text("tipo_market.html"))
    assert links == [
        (95979, "inkafarmape-market-nc"),
        (72317, "gas-station"),
        (62365, "wong"),
        (11214, "metro"),
        (74150, "rappi-market-nc"),
    ]
    assert store_links(None) == []


def test_restaurant_ssg_page():
    info, offers = parse_restaurant_page(extract_next_data(fixture_text("restaurant_ssg_23402.html")))
    assert info["id"] == 23402
    offers = by_id(offers)
    assert offers["2092703306"].pct == 70
    assert offers["2092703306"].price == 29.9
    assert offers["2092993350"].available is False
    pro = offers["2092993399"]
    assert pro.pro_only and pro.pct == 65
    assert pro.regular_price == 35 and pro.price == 12.25
    assert "2093011969" not in offers  # sin descuento

    cfg = Config()
    assert [o.pct for o in good_offers(list(offers.values()), cfg)] == [70, 67, 62]
    cfg.rappi_pro = True
    assert [o.pct for o in good_offers(list(offers.values()), cfg)] == [70, 67, 65, 62]


def test_restaurant_live_menu():
    info, offers = parse_restaurant_live(fixture_json("restaurant_live_23402.json"), include_pro=False)
    assert info["name"] == "Big Cheese Pizza - Miraflores"
    offers = by_id(offers)
    assert len(offers) == 6  # el producto repetido cuenta una vez
    assert offers["2092703306"].pct == 70
    assert offers["2092703306"].price == 29.9
    assert offers["2092703306"].regular_price == 99.8
    assert offers["2093011138"].pct == 34
    assert parse_restaurant_live(None, include_pro=False) == ({}, [])


def test_restaurant_live_menu_pro_discounts():
    data = {
        "store_id": 1,
        "name": "Local",
        "corridors": [
            {
                "products": [
                    {
                        "product_id": 10,
                        "name": "Combo",
                        "price": 50,
                        "real_price": 50,
                        "discounts": [
                            {"type": "global_offer", "value": 70, "price": 15, "is_prime_exclusive": True},
                            {"type": "global_offer", "value": 40, "price": 30, "is_prime_exclusive": False},
                        ],
                    },
                    {
                        "product_id": 11,
                        "name": "Solo porcentaje",
                        "price": 20,
                        "real_price": 20,
                        "discount_percentage": 61,
                        "discounts": [],
                    },
                    {
                        "product_id": 12,
                        "name": "No aplica al usuario",
                        "price": 20,
                        "real_price": 20,
                        "discounts": [{"type": "global_offer", "value": 90, "price": 2, "apply_to_user": False}],
                    },
                ]
            }
        ],
    }
    _, normal = parse_restaurant_live(data, include_pro=False)
    normal = by_id(normal)
    assert normal["10"].pct == 40 and not normal["10"].pro_only
    assert normal["11"].pct == 61 and normal["11"].price == 7.8
    assert "12" not in normal

    _, pro = parse_restaurant_live(data, include_pro=True)
    pro = by_id(pro)
    assert pro["10"].pct == 70 and pro["10"].pro_only and pro["10"].price == 15


def test_restaurant_candidates_from_promos_list():
    stores = fixture_json("filters_promos.json")
    candidates = restaurant_candidates(stores, 60, include_pro=False)
    assert [(c.store_id, c.best_pct) for c in candidates] == [(1792, 100), (23402, 70), (632, 66)]
    fridays = candidates[0]
    assert fridays.slug == "tgi-fridays"
    assert fridays.product_tag == "Hasta 100% Off"
    assert fridays.distance_km == 5.4

    with_pro = restaurant_candidates(stores, 60, include_pro=True)
    pizza_hut = next(c for c in with_pro if c.store_id == 15533)
    assert pizza_hut.product_pct == 60 and "Rappi Pro" in pizza_hut.product_tag

    # "Agrega 2, paga 1" no tiene porcentaje; el 20% de Seitan es para toda la carta.
    low = restaurant_candidates(stores, 20, include_pro=False)
    ids = {c.store_id for c in low}
    assert 315 not in ids and 9993 not in ids
    seitan = next(c for c in low if c.store_id == 274)
    assert seitan.store_wide_pct == 20 and seitan.product_pct == 0


def test_restaurant_candidates_distance_and_status_filters():
    stores = fixture_json("filters_promos.json")
    near = restaurant_candidates(stores, 60, include_pro=False, max_distance_km=3)
    assert [c.store_id for c in near] == [23402]

    stores[2]["status"] = "CLOSED"
    stores[0]["is_currently_available"] = False
    assert [c.store_id for c in restaurant_candidates(stores, 60, False)] == [632]
    assert restaurant_candidates(None, 60, False) == []
    assert restaurant_candidates([None, {"store_id": "x"}], 60, False) == []


def test_chain_restaurants():
    html = fixture_text("chain_fridays.html")
    assert chain_restaurants(html) == [(1790, "tgi-fridays"), (107225, "tgi-fridays"), (1791, "tgi-fridays")]
    # Sin datos de Next.js se usan los enlaces de la página.
    links_only = '<a href="/restaurantes/55-la-casa">x</a><a href="/restaurantes/55-la-casa">y</a>'
    assert chain_restaurants(links_only) == [(55, "la-casa")]
    assert chain_restaurants(None) == []

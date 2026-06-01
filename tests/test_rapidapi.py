import unittest

from amazon_finder.finder import Criteria
from amazon_finder.rapidapi import (
    RapidApiClient,
    product_from_result,
    find_products_rapidapi,
    _parse_price,
    _parse_int,
)


def _result(asin, sales_volume, num_offers, title="Item", price="$19.99"):
    return {
        "asin": asin,
        "product_title": title,
        "product_url": f"https://www.amazon.com/dp/{asin}",
        "product_photo": "",
        "product_price": price,
        "currency": "USD",
        "product_star_rating": "4.5",
        "product_num_ratings": "1,234",
        "product_num_offers": num_offers,
        "sales_volume": sales_volume,
    }


class FakeRapidClient:
    def __init__(self, results):
        self._results = results

    def iter_search_results(self, query=None, *, category_id=None, max_pages=1, sort_by=None):
        yield from self._results


class ParsingTests(unittest.TestCase):
    def test_parse_price(self):
        self.assertEqual(_parse_price("$19.99"), 19.99)
        self.assertEqual(_parse_price("£1,234.56"), 1234.56)
        self.assertEqual(_parse_price("24.99"), 24.99)
        self.assertIsNone(_parse_price(None))

    def test_parse_int(self):
        self.assertEqual(_parse_int("1,234"), 1234)
        self.assertEqual(_parse_int(12), 12)
        self.assertIsNone(_parse_int(None))
        self.assertIsNone(_parse_int(True))

    def test_product_from_result(self):
        p = product_from_result(_result("A1", "2K+ bought in past month", 8, "Cool"))
        self.assertEqual(p.asin, "A1")
        self.assertEqual(p.title, "Cool")
        self.assertEqual(p.recent_sales, 2000)
        self.assertEqual(p.offers_count, 8)
        self.assertEqual(p.price, 19.99)
        self.assertEqual(p.ratings_total, 1234)


class FindTests(unittest.TestCase):
    def test_filters_on_sales_and_offers(self):
        results = [
            _result("A1", "100+ bought in past month", 8),   # passes both
            _result("A2", "40+ bought in past month", 9),    # sales too low
            _result("A3", "1K+ bought in past month", 3),    # too few offers
            _result("A4", "", 20),                            # no sales signal
            _result("A5", "500+ bought in past month", None),  # offers unknown
        ]
        client = FakeRapidClient(results)
        matched = find_products_rapidapi(
            client, search_term="x",
            criteria=Criteria(min_sales=50, min_offers=6),
        )
        self.assertEqual([p.asin for p in matched], ["A1"])

    def test_check_offers_disabled(self):
        results = [_result("A5", "500+ bought in past month", None)]
        client = FakeRapidClient(results)
        matched = find_products_rapidapi(
            client, search_term="x",
            criteria=Criteria(min_sales=50, min_offers=6, check_offers=False),
        )
        self.assertEqual([p.asin for p in matched], ["A5"])

    def test_dedup(self):
        results = [
            _result("A1", "100+ bought in past month", 8),
            _result("A1", "100+ bought in past month", 8),
        ]
        client = FakeRapidClient(results)
        matched = find_products_rapidapi(client, search_term="x")
        self.assertEqual(len(matched), 1)


class ClientTests(unittest.TestCase):
    def test_requires_key(self):
        with self.assertRaises(Exception):
            RapidApiClient("")

    def test_domain_to_country(self):
        self.assertEqual(RapidApiClient("k", "amazon.co.uk").country, "UK")
        self.assertEqual(RapidApiClient("k", "amazon.de").country, "DE")
        self.assertEqual(RapidApiClient("k", "amazon.unknown").country, "US")


if __name__ == "__main__":
    unittest.main()

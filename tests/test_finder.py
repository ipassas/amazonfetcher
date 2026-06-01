import unittest

from amazon_finder.finder import Criteria, find_products, product_from_search_result


class FakeClient:
    """Stand-in for RainforestClient with canned responses (no network)."""

    def __init__(self, results, offers):
        self._results = results
        self._offers = offers
        self.offers_calls = []

    def iter_search_results(self, search_term=None, *, category_id=None,
                            max_pages=1, sort_by=None):
        yield from self._results

    def offers_count(self, asin):
        self.offers_calls.append(asin)
        return self._offers.get(asin)


def _result(asin, sales, title="Item"):
    return {
        "asin": asin,
        "title": title,
        "link": f"https://amazon.com/dp/{asin}",
        "price": {"value": 19.99, "currency": "$"},
        "recent_sales": sales,
    }


class FinderTests(unittest.TestCase):
    def test_filters_on_sales_and_offers(self):
        results = [
            _result("A1", "100+ bought in past month"),  # sales ok
            _result("A2", "40+ bought in past month"),   # sales too low
            _result("A3", "1K+ bought in past month"),   # sales ok
            _result("A4", ""),                            # no sales signal
        ]
        offers = {"A1": 8, "A3": 3}  # A1 enough sellers, A3 too few
        client = FakeClient(results, offers)

        matched = find_products(
            client, search_term="x",
            criteria=Criteria(min_sales=50, min_offers=6),
        )

        self.assertEqual([p.asin for p in matched], ["A1"])
        # Offers only fetched for products that passed the sales filter.
        self.assertCountEqual(client.offers_calls, ["A1", "A3"])

    def test_no_check_offers_skips_seller_lookup(self):
        results = [_result("A1", "100+ bought in past month")]
        client = FakeClient(results, {})
        matched = find_products(
            client, search_term="x",
            criteria=Criteria(min_sales=50, min_offers=6, check_offers=False),
        )
        self.assertEqual([p.asin for p in matched], ["A1"])
        self.assertEqual(client.offers_calls, [])

    def test_deduplicates_asins(self):
        results = [
            _result("A1", "100+ bought in past month"),
            _result("A1", "100+ bought in past month"),
        ]
        client = FakeClient(results, {"A1": 9})
        matched = find_products(client, search_term="x")
        self.assertEqual(len(matched), 1)

    def test_product_from_search_result_parses_fields(self):
        p = product_from_search_result(_result("Z9", "2K+ bought in past month", "Cool"))
        self.assertEqual(p.asin, "Z9")
        self.assertEqual(p.title, "Cool")
        self.assertEqual(p.recent_sales, 2000)
        self.assertEqual(p.price, 19.99)
        self.assertEqual(p.currency, "$")


if __name__ == "__main__":
    unittest.main()

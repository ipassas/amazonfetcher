import importlib
import os
import tempfile
import unittest

from amazon_finder import history
from amazon_finder.models import Product


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HISTORY_DB"] = os.path.join(self.tmp, "h.db")

    def tearDown(self):
        os.environ.pop("HISTORY_DB", None)

    def _params(self, search="earbuds"):
        return {
            "provider": "rapidapi", "search": search, "category": "",
            "domain": "amazon.com", "min_sales": 50, "min_offers": 6,
            "max_pages": 1, "check_offers": True,
        }

    def test_add_list_get(self):
        prods = [Product(asin="A1", title="Cable", recent_sales=100, offers_count=8)]
        sid = history.add_search(self._params(), prods)
        rows = history.list_searches()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["search"], "earbuds")
        self.assertEqual(rows[0]["result_count"], 1)
        full = history.get_search(sid)
        self.assertEqual(full["results"][0]["asin"], "A1")

    def test_dedup_same_params(self):
        p = [Product(asin="A1", title="x", recent_sales=100, offers_count=8)]
        id1 = history.add_search(self._params(), p)
        id2 = history.add_search(self._params(), p)  # within window -> deduped
        self.assertEqual(id1, id2)
        self.assertEqual(len(history.list_searches()), 1)

    def test_distinct_params_not_deduped(self):
        p = [Product(asin="A1", title="x", recent_sales=100, offers_count=8)]
        history.add_search(self._params("earbuds"), p)
        history.add_search(self._params("yoga mat"), p)
        self.assertEqual(len(history.list_searches()), 2)

    def test_missing(self):
        self.assertIsNone(history.get_search(999))


if __name__ == "__main__":
    unittest.main()

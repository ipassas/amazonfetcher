import unittest

from amazon_finder.sales import parse_recent_sales, meets_sales_threshold


class ParseRecentSalesTests(unittest.TestCase):
    def test_plain_plus(self):
        self.assertEqual(parse_recent_sales("50+ bought in past month"), 50)
        self.assertEqual(parse_recent_sales("100+ bought in past month"), 100)

    def test_thousands_suffix(self):
        self.assertEqual(parse_recent_sales("1K+ bought in past month"), 1000)
        self.assertEqual(parse_recent_sales("10K+ bought in past month"), 10000)
        self.assertEqual(parse_recent_sales("2k+ bought in past month"), 2000)

    def test_decimal_thousands(self):
        self.assertEqual(parse_recent_sales("1.5K+ bought in past month"), 1500)

    def test_millions_suffix(self):
        self.assertEqual(parse_recent_sales("1M+ bought in past month"), 1_000_000)

    def test_comma_grouping(self):
        self.assertEqual(parse_recent_sales("1,200+ bought in past month"), 1200)

    def test_numeric_input(self):
        self.assertEqual(parse_recent_sales(75), 75)
        self.assertEqual(parse_recent_sales(75.9), 75)

    def test_unparseable_returns_none(self):
        self.assertIsNone(parse_recent_sales(""))
        self.assertIsNone(parse_recent_sales(None))
        self.assertIsNone(parse_recent_sales("no sales info"))

    def test_zero_distinct_from_none(self):
        self.assertEqual(parse_recent_sales("0+ bought in past month"), 0)


class ThresholdTests(unittest.TestCase):
    def test_meets(self):
        self.assertTrue(meets_sales_threshold("50+ bought in past month", 50))
        self.assertTrue(meets_sales_threshold("1K+ bought in past month", 50))

    def test_below(self):
        self.assertFalse(meets_sales_threshold("40+ bought in past month", 50))

    def test_unknown_never_passes(self):
        self.assertFalse(meets_sales_threshold("", 50))
        self.assertFalse(meets_sales_threshold(None, 1))


if __name__ == "__main__":
    unittest.main()

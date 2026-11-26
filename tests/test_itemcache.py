import os
import tempfile
import unittest

from crawler import itemcache


class ItemCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        itemcache._db = None
        self._orig = itemcache.CACHE_DIR
        itemcache.CACHE_DIR = self.tmp

    def tearDown(self):
        itemcache._db = None
        itemcache.CACHE_DIR = self._orig

    def test_only_missing_items_fetched(self):
        calls = []

        def fetch(keys):
            calls.append(list(keys))
            return {k: k.upper() for k in keys if k != "none"}

        self.assertEqual(itemcache.batched("t", ["a", "b", "none"], fetch), {"a": "A", "b": "B", "none": None})
        self.assertEqual(itemcache.batched("t", ["b", "c", "none"], fetch), {"b": "B", "c": "C", "none": None})
        self.assertEqual(calls, [["a", "b", "none"], ["c"]])  # negatives are cached too
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "items.sqlite")))

    def test_encode_decode(self):
        got = itemcache.batched("s", ["x"], lambda ks: {"x": {"ids": {"2", "1"}}},
                                encode=lambda v: {"ids": sorted(v["ids"])}, decode=lambda v: {"ids": set(v["ids"])})
        self.assertEqual(got["x"]["ids"], {"1", "2"})
        again = itemcache.batched("s", ["x"], lambda ks: self.fail("should be cached"),
                                  encode=lambda v: {"ids": sorted(v["ids"])}, decode=lambda v: {"ids": set(v["ids"])})
        self.assertEqual(again["x"]["ids"], {"1", "2"})


if __name__ == "__main__":
    unittest.main()

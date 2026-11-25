import unittest

from crawler import kinship as k


class Names(unittest.TestCase):
    def test_ancestors(self):
        self.assertEqual(k.name(1, 0), "parent")
        self.assertEqual(k.name(2, 0), "grandparent")
        self.assertEqual(k.name(3, 0), "great-grandparent")
        self.assertEqual(k.name(5, 0), "3× great-grandparent")

    def test_collateral(self):
        self.assertEqual(k.name(1, 1), "sibling")
        self.assertEqual(k.name(2, 1), "aunt/uncle")
        self.assertEqual(k.name(3, 1), "grand-aunt/uncle")
        self.assertEqual(k.name(4, 1), "great-grand-aunt/uncle")
        self.assertEqual(k.name(1, 2), "niece/nephew")
        self.assertEqual(k.name(2, 2), "1st cousin")
        self.assertEqual(k.name(3, 2), "1st cousin once removed")
        self.assertEqual(k.name(5, 7), "4th cousin twice removed")
        self.assertEqual(k.name(12, 12), "11th cousin")
        self.assertEqual(k.name(3, 9), "2nd cousin 6 times removed")


class Relations(unittest.TestCase):
    # me <- P (phd), me <- U (undergrad); P <- G ; U <- G ; G <- GG ; GG <- X1 <- X2
    def setUp(self):
        self.all = {"me": ["P", "U"], "P": ["G"], "U": ["G2"], "G": ["GG"], "G2": ["GG"],
                    "X1": ["GG"], "X2": ["X1"], "Y": ["U"]}
        self.phd = {"me": ["P"], "P": ["G"], "G": ["GG"], "X1": ["GG"], "X2": ["X1"]}
        self.nodes = ["P", "U", "G", "G2", "GG", "X1", "X2", "Y"]

    def test_all_edges(self):
        r = k.relations("me", self.nodes, self.all)
        self.assertEqual(r["GG"]["label"], "great-grandparent")
        self.assertEqual(r["X2"]["label"], "1st cousin once removed")
        self.assertEqual(r["Y"]["label"], "sibling")
        self.assertEqual(r["X1"]["label"], "grand-aunt/uncle")

    def test_phd_primary_fallback(self):
        r = k.relations_phd_primary("me", self.nodes, self.all, self.phd)
        self.assertFalse(r["X2"]["fallback"])
        self.assertTrue(r["Y"]["fallback"])
        self.assertTrue(r["U"]["fallback"])
        self.assertEqual(r["U"]["label"], "parent")

    def test_alternates_only_lowest_common(self):
        par = {"me": ["A", "B"], "X": ["A", "B"], "A": ["R"], "B": ["R"]}
        r = k.relations("me", ["X"], par)
        self.assertEqual(r["X"]["label"], "sibling")
        self.assertEqual(r["X"]["alternates"], [])


if __name__ == "__main__":
    unittest.main()

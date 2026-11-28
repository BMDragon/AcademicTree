import unittest

from crawler import build


class KnownForDedupe(unittest.TestCase):
    def test_named_after_wins(self):
        recs = {"x": {
            "name": "Albert Einstein",
            "named_after": [{"label": "Einstein field equations",
                             "url": "https://en.wikipedia.org/wiki/Einstein_field_equations"},
                            {"label": "Bose–Einstein condensate",
                             "url": "https://en.wikipedia.org/wiki/Bose%E2%80%93Einstein_condensate"}],
            "known_for": [{"label": "Einstein Field Equations",
                           "url": "https://en.wikipedia.org/wiki/Einstein_Field_Equations"},
                          {"label": "Bose-Einstein condensate",
                           "url": "https://en.wikipedia.org/wiki/Bose-Einstein_condensate"},
                          {"label": "Photoelectric effect",
                           "url": "https://en.wikipedia.org/wiki/Photoelectric_effect"}]}}
        build.dedupe_known_for(recs)
        self.assertEqual([k["label"] for k in recs["x"]["known_for"]], ["Photoelectric effect"])
        self.assertEqual(len(recs["x"]["named_after"]), 2)


if __name__ == "__main__":
    unittest.main()


class Eponyms(unittest.TestCase):
    def test_is_eponym(self):
        from crawler import names
        self.assertTrue(names.is_eponym("Frobenius method", "Ferdinand Georg Frobenius"))
        self.assertTrue(names.is_eponym("Frobenius–Schur indicator", "Ferdinand Georg Frobenius"))
        self.assertTrue(names.is_eponym("Fermi's golden rule", "Enrico Fermi"))
        self.assertTrue(names.is_eponym("Schrödinger equation", "Erwin Schrödinger"))
        self.assertTrue(names.is_eponym("Helmholtz free energy", "Hermann von Helmholtz"))
        self.assertFalse(names.is_eponym("Representation theory", "Ferdinand Georg Frobenius"))
        self.assertFalse(names.is_eponym("first-born children", "Max Born"))
        self.assertTrue(names.is_eponym("einsteinium", "Albert Einstein"))
        self.assertTrue(names.is_eponym("curium", "Marie Curie"))
        self.assertTrue(names.is_eponym("fermion", "Enrico Fermi"))
        self.assertTrue(names.is_eponym("Gaussian elimination", "Carl Friedrich Gauss"))
        self.assertTrue(names.is_eponym("Boolean algebra", "George Boole"))
        self.assertTrue(names.is_eponym("Frobenioid", "Ferdinand Georg Frobenius"))
        self.assertTrue(names.is_eponym("curie", "Marie Curie"))
        self.assertTrue(names.is_eponym("newton", "Isaac Newton"))
        self.assertFalse(names.is_eponym("Burnside's lemma", "Ferdinand Georg Frobenius"))
        self.assertFalse(names.is_eponym("Rouché–Capelli theorem", "Ferdinand Georg Frobenius"))

    def test_eponyms_move_to_named_after(self):
        recs = {"x": {"name": "Ferdinand Georg Frobenius",
                      "named_after": [{"label": "Frobenius norm", "url": "https://www.wikidata.org/wiki/Q1", "wiki": False}],
                      "known_for": [{"label": "Frobenius method", "url": "https://en.wikipedia.org/wiki/Frobenius_method"},
                                    {"label": "Group theory", "url": "https://en.wikipedia.org/wiki/Group_theory"}]}}
        build.dedupe_known_for(recs)
        self.assertEqual([k["label"] for k in recs["x"]["known_for"]], ["Group theory"])
        self.assertIn("Frobenius method", [x["label"] for x in recs["x"]["named_after"]])

    def test_hidden_eponyms_move_to_known_for(self):
        recs = {"x": {"name": "Ferdinand Georg Frobenius", "named_after_total": 2,
                      "named_after": [{"label": "Burnside's lemma", "url": "https://en.wikipedia.org/wiki/Burnside%27s_lemma", "wiki": True},
                                      {"label": "Frobenius norm", "url": "https://www.wikidata.org/wiki/Q1", "wiki": False}],
                      "known_for": []}}
        build.dedupe_known_for(recs)
        self.assertEqual([x["label"] for x in recs["x"]["named_after"]], ["Frobenius norm"])
        self.assertEqual([k["label"] for k in recs["x"]["known_for"]], ["Burnside's lemma"])
        self.assertEqual(recs["x"]["named_after_total"], 1)


class QuizbowlNames(unittest.TestCase):
    def test_variants(self):
        from crawler import notables
        self.assertEqual(notables.name_variants("Barry C. Barish"), ["Barry C. Barish", "Barry Barish"])
        self.assertEqual(notables.name_variants("Charles Galton Darwin"), ["Charles Galton Darwin"])
        self.assertEqual(notables.name_variants("Feynman"), [])

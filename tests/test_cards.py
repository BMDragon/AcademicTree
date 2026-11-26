import unittest

from crawler import build


class KnownForDedupe(unittest.TestCase):
    def test_named_after_wins(self):
        recs = {"x": {
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


class QuizbowlNames(unittest.TestCase):
    def test_variants(self):
        from crawler import notables
        self.assertEqual(notables.name_variants("Barry C. Barish"), ["Barry C. Barish", "Barry Barish"])
        self.assertEqual(notables.name_variants("Charles Galton Darwin"), ["Charles Galton Darwin"])
        self.assertEqual(notables.name_variants("Feynman"), [])

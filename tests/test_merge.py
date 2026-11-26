import unittest

from crawler import build, names


class FakeCfg(dict):
    pass


def crawler():
    return build.Crawler({"max_generations": 10, "sources": {"mgp": True, "inspire": True}})


class Merge(unittest.TestCase):
    def test_crosswalk_and_coadvisor_merge(self):
        cr = crawler()
        cr.info.update({"wd:Q1": {"name": "Steffen Bass"}, "wd:Q2": {"name": "Walter Greiner"},
                        "mgp:9": {"name": "Walter  Greiner"}, "insp:5": {"name": "Steffen Ashraf Bass"},
                        "nm:Stoecker, Horst|insp:5": {"name": "Horst Stoecker"},
                        "wd:Q3": {"name": "Horst Stöcker"}})
        cr.add("wd:Q1", 0)
        cr.same("wd:Q1", "insp:5")          # Wikidata <-> INSPIRE crosswalk
        cr.same("wd:Q1", "mgp:1")
        cr.add_adv("wd:Q1", "wd:Q2", "phd")
        cr.add_adv("wd:Q1", "wd:Q3", "phd")
        cr.add_adv("mgp:1", "mgp:9", "phd")  # MGP knows Greiner under another id
        cr.add_adv("insp:5", "nm:Stoecker, Horst|insp:5", "research")
        groups, parents = build.assemble(cr, [("wd:Q1", "undergrad")])
        f = cr.uf.find
        self.assertEqual(f("mgp:9"), f("wd:Q2"))
        self.assertEqual(f("nm:Stoecker, Horst|insp:5"), f("wd:Q3"))
        self.assertEqual(len(parents[f("wd:Q1")]), 2)
        # PhD from Wikidata outranks INSPIRE's "other"
        self.assertEqual(parents[f("wd:Q1")][f("wd:Q3")][0], "phd")
        self.assertEqual(parents["me"], {f("wd:Q1"): ["undergrad", {"config"}]})

    def test_distinct_wikidata_items_not_merged(self):
        cr = crawler()
        cr.info.update({"wd:Q1": {"name": "Student"}, "wd:Q2": {"name": "John Smith"},
                        "wd:Q3": {"name": "Jane Smith"}, "wd:Q4": {"name": "J. Smith"}})
        cr.add("wd:Q1", 0)
        for a in ("wd:Q2", "wd:Q3", "wd:Q4"):
            cr.add_adv("wd:Q1", a, "phd")
        build.assemble(cr, [])
        self.assertNotEqual(cr.uf.find("wd:Q2"), cr.uf.find("wd:Q4"))

    def test_duplicate_wikidata_items_with_identical_names_merge(self):
        cr = crawler()
        cr.info.update({"wd:Q1": {"name": "Berta Karlik"}, "wd:Q2": {"name": "Stefan Meyer"},
                        "wd:Q3": {"name": "Stefan Meyer"}})
        cr.add("wd:Q1", 0)
        cr.add_adv("wd:Q1", "wd:Q2", "phd")
        cr.add_adv("wd:Q1", "wd:Q3", "phd")
        build.assemble(cr, [])
        self.assertEqual(cr.uf.find("wd:Q2"), cr.uf.find("wd:Q3"))

    def test_non_person_advisors_dropped(self):
        cr = crawler()
        cr.info.update({"wd:Q1": {"name": "Max Born"}, "wd:Q2": {"name": "König Wilhelm-Gymnasium zu Breslau"},
                        "wd:Q3": {"name": "Carl Runge"}, "mgp:7": {"name": "Alonzo Church"},
                        "mgp:8": {"name": "Universität Leipzig"}})
        cr.add("wd:Q1", 0)
        cr.nonhuman.add("wd:Q2")
        cr.add_adv("wd:Q1", "wd:Q2", "research")
        cr.add_adv("wd:Q1", "wd:Q3", "phd")
        cr.add_adv("wd:Q3", "mgp:7", "phd")
        cr.add_adv("wd:Q3", "mgp:8", "phd")
        groups, parents = build.assemble(cr, [])
        f = cr.uf.find
        self.assertEqual(set(parents[f("wd:Q1")]), {f("wd:Q3")})
        self.assertEqual(set(parents[f("wd:Q3")]), {f("mgp:7")})   # Alonzo Church is a person
        self.assertNotIn(f("wd:Q2"), groups)

    def test_names(self):
        self.assertTrue(names.same_person("Stoecker, Horst", "Horst Stöcker"))
        self.assertTrue(names.same_person("Barish, Barry C.", "Barry Clark Barish"))
        self.assertFalse(names.same_person("John Smith", "Jane Doe"))


class Cycles(unittest.TestCase):
    def test_break(self):
        par = {"a": {"b": 1}, "b": {"c": 1}, "c": {"a": 1}}
        dropped = build.break_cycles(par)
        self.assertEqual(len(dropped), 1)

    def test_select(self):
        par = {"me": {"P": 1}, "P": {"G": 1}, "N": {"X": 1}, "X": {"G": 1}, "Z": {"Q": 1}}
        anc, keep = build.select(par, {"N", "Z"})
        self.assertEqual(anc, {"P", "G"})
        self.assertEqual(keep, {"me", "P", "G", "X", "N"})


if __name__ == "__main__":
    unittest.main()

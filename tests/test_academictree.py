import unittest

from crawler import academictree_html as at

PAGE = """<html><head><title>Kate Scholberg - Physics Tree</title>
<link rel="canonical" href="https://academictree.org/physics/peopleinfo.php?pid=123"></head><body>
<h1>Kate Scholberg</h1>
<h3>Parents</h3><table>
<tr><td><a href="peopleinfo.php?pid=55">Barry C. Barish</a></td><td>grad student</td><td>1997</td><td>Caltech</td></tr>
<tr><td><a href="peopleinfo.php?pid=56">Someone Else</a></td><td>collaborator</td></tr>
</table>
<h3>Children</h3><table>
<tr><td><a href="peopleinfo.php?pid=77">A Student</a></td><td>undergrad</td><td>2015-2019</td><td>Duke</td></tr>
<tr><td><a href="peopleinfo.php?pid=78">A Postdoc</a></td><td>post-doc</td><td>2010</td></tr>
</table></body></html>"""


class Parse(unittest.TestCase):
    def test_strip_degrees(self):
        self.assertEqual(at.strip_degrees("Enrico Fermi, Ph.D."), "Enrico Fermi")
        self.assertEqual(at.strip_degrees("Jane Roe, M.D., Ph.D."), "Jane Roe")
        self.assertEqual(at.strip_degrees("Barish, Barry"), "Barish, Barry")

    def test_parse(self):
        r = at.parse(PAGE, "kate.html")
        self.assertEqual(r["pid"], "123")
        self.assertEqual(r["name"], "Kate Scholberg")
        self.assertEqual([(p["pid"], p["type"]) for p in r["parents"]], [("55", "phd")])
        self.assertEqual([(c["pid"], c["type"]) for c in r["children"]], [("77", "undergrad"), ("78", "postdoc")])


if __name__ == "__main__":
    unittest.main()

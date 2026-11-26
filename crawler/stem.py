"""Decide whether a Wikidata item is a STEM topic (for the "named after them" list).

An item counts as STEM when it is not in an excluded category (awards,
organizations, places, buildings, celestial bodies, vehicles, artworks, …) and
either
  * its class hierarchy (P31/P279*) reaches a STEM root class, or
  * it is a bare concept: no "instance of" at all, or itself a subclass of
    something (concepts such as "Planck scale" or "Newtonian fluid" are often
    modelled that way, while places and institutions almost never are).
Root QIDs were resolved from their English labels.
"""
import re

from . import wikidata

STEM_ROOTS = {
    "Q246672": "mathematical object", "Q24034552": "mathematical concept", "Q65943": "theorem",
    "Q11345": "equation", "Q976981": "formula", "Q214070": "physical law", "Q408891": "scientific law",
    "Q3239681": "scientific theory", "Q1293220": "physical phenomenon", "Q483247": "phenomenon",
    "Q107715": "physical quantity", "Q309314": "quantity", "Q47574": "unit of measurement",
    "Q932268": "system of units", "Q173227": "physical constant", "Q11344": "chemical element",
    "Q36534": "chemical reaction", "Q11173": "chemical compound", "Q8366": "algorithm",
    "Q815844": "method", "Q2695280": "technique", "Q319141": "conjecture", "Q41719": "hypothesis",
    "Q483372": "paradox", "Q147027": "thought experiment", "Q486902": "mathematical model",
    "Q193946": "scientific model", "Q12136": "disease", "Q179630": "syndrome",
    "Q4936952": "anatomical structure", "Q7187": "gene", "Q2996394": "biological process",
    "Q200726": "probability distribution", "Q1949963": "statistic", "Q9143": "programming language",
    "Q175263": "data structure", "Q11862829": "academic discipline", "Q211364": "principle",
    "Q11430": "state of matter", "Q1166625": "mathematical problem", "Q28113351": "inequality",
    "Q11348": "function", "Q11210": "coordinate system", "Q1454986": "physical system",
    "Q102205": "fluid", "Q3099911": "scientific instrument", "Q2041172": "measuring instrument",
    "Q60137545": "cosmological epoch",
}
EXCLUDE_ROOTS = {
    "Q618779": "award", "Q188823": "scholarship", "Q4164871": "position", "Q43229": "organization",
    "Q4830453": "business", "Q783794": "company", "Q2221906": "geographic location",
    "Q618123": "geographical feature", "Q35145263": "natural geographic object",
    "Q6999": "astronomical object", "Q3863": "asteroid", "Q55818": "impact crater",
    "Q811979": "built structure", "Q42889": "vehicle", "Q11446": "ship", "Q40218": "spacecraft",
    "Q838948": "work of art", "Q17537576": "creative work", "Q7725634": "literary work",
    "Q11424": "film", "Q2188189": "musical work", "Q1002697": "periodical", "Q3914": "school",
    "Q16917": "hospital", "Q33506": "museum", "Q79007": "street", "Q5": "human", "Q11410": "game",
    "Q11422": "toy", "Q10290214": "event", "Q16521": "taxon", "Q12089225": "mineral species",
    "Q7315176": "research program", "Q10929058": "product model", "Q44167": "engine",
    "Q259864": "microarchitecture", "Q7397": "software", "Q3966": "computer hardware",
}


def _reaching(qids, roots):
    out = set()
    for chunk in wikidata._chunks(sorted(qids), 60):
        rows = wikidata.sparql(
            "SELECT DISTINCT ?x WHERE { VALUES ?x { %s } VALUES ?r { %s } ?x (wdt:P31|wdt:P279)/wdt:P279* ?r . }"
            % (wikidata._values(chunk), wikidata._values(sorted(roots))))
        out.update(wikidata.qid(r["x"]) for r in rows)
    return out


def _bare_concepts(qids):
    """Items with no P31, or with a P279 (i.e. classes/concepts)."""
    out = set()
    for chunk in wikidata._chunks(sorted(qids), 150):
        rows = wikidata.sparql("""
SELECT ?x WHERE { VALUES ?x { %s }
  FILTER(NOT EXISTS { ?x wdt:P31 ?c } || EXISTS { ?x wdt:P279 ?s }) }""" % wikidata._values(chunk))
        out.update(wikidata.qid(r["x"]) for r in rows)
    return out


# Capitalised institution words (case-sensitive, so "Wheatstone bridge" or
# "Hall effect" are unaffected).
INSTITUTION_WORDS = re.compile(
    r"\b(School|Schule|Lyc[ée]e|College|University|Universit[äé]t|Institute|Institut|Academy|Society|"
    r"Foundation|Prize|Award|Medal|Lectureship|Lecture|Fellowship|Professorship|Museum|Hospital|"
    r"Street|Library|Archives|Programme|Program)\b")


def looks_institutional(label):
    return bool(INSTITUTION_WORDS.search(label or ""))


def stem_items(qids):
    qids = {q for q in qids if q.startswith("Q")}  # drop lexemes (L…) and the like
    if not qids:
        return set()
    excluded = _reaching(qids, EXCLUDE_ROOTS)
    cand = qids - excluded
    return (_reaching(cand, STEM_ROOTS) | _bare_concepts(cand)) if cand else set()

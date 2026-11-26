"""Wikidata SPARQL access: advisor links, ID crosswalks, prizes, enrichment."""
import re
import urllib.parse

from . import http

ENDPOINT = "https://query.wikidata.org/sparql"
BATCH = 150


def sparql(query):
    import json
    import time
    data = urllib.parse.urlencode({"query": query, "format": "json"})
    js = None
    for attempt in range(4):  # the endpoint times out now and then under load
        txt = http.get(ENDPOINT, data=data, headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/sparql-results+json"})
        if txt:
            try:
                js = json.loads(txt)
                break
            except ValueError:
                js = None
        time.sleep(20 * (attempt + 1))
    if js is None:
        raise RuntimeError("SPARQL query failed:\n" + query[:500])
    return [{k: v["value"] for k, v in b.items()} for b in js["results"]["bindings"]]


def qid(uri):
    return uri.rsplit("/", 1)[-1]


def _year(t):
    """Year from an xsd:dateTime; None for unknown values (blank-node URIs)."""
    import re
    m = re.match(r"^-?(\d{1,4})-", t or "")
    return int(m.group(1)) if m else None


def _chunks(xs, n=BATCH):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _values(qids):
    return " ".join("wd:" + q for q in qids)


def _strvalues(vals):
    out = []
    for v in vals:
        v = v.replace("\\", "\\\\").replace('"', '\\"')
        out.append('"%s"' % v)
    return " ".join(out)


def links(qids):
    """For each QID: label, external IDs and advisors (with edge types).

    Returns {qid: {"label", "mgp", "bai", "at", "orcid", "advisors": [(qid, type)]}}
    """
    out = {}
    for chunk in _chunks(sorted(set(qids))):
        rows = sparql("""
SELECT ?p ?pLabel ?mgp ?bai ?at ?orcid ?human WHERE {
  VALUES ?p { %s }
  OPTIONAL { ?p wdt:P549 ?mgp }
  OPTIONAL { ?p wdt:P2930 ?bai }
  OPTIONAL { ?p wdt:P2381 ?at }
  OPTIONAL { ?p wdt:P496 ?orcid }
  BIND(EXISTS { ?p wdt:P31 wd:Q5 } AS ?human)
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,de,fr,it,es,nl,ru,mul". }
}""" % _values(chunk))
        for r in rows:
            q = qid(r["p"])
            d = out.setdefault(q, {"label": r.get("pLabel", q), "mgp": set(), "bai": set(),
                                   "at": set(), "orcid": set(), "advisors": {},
                                   "human": r.get("human") == "true"})
            for k in ("mgp", "bai", "at", "orcid"):
                if r.get(k):
                    d[k].add(r[k])
        v = _values(chunk)
        for r in sparql("SELECT ?p ?b WHERE { VALUES ?p { %s } ?p wdt:P569 ?b . }" % v):
            y = _year(r.get("b"))
            q = qid(r["p"])
            if y is not None and q in out:
                if r["b"].startswith("-"):
                    y = -y
                cur = out[q].get("birth_year")
                out[q]["birth_year"] = y if cur is None else min(cur, y)
        for pattern, rel in (("?p wdt:P184 ?a", "phd"), ("?a wdt:P185 ?p", "phd"),
                             ("?p wdt:P1066 ?a", "research"), ("?a wdt:P802 ?p", "research")):
            for r in sparql("SELECT ?p ?a WHERE { VALUES ?p { %s } %s . }" % (v, pattern)):
                q, a = qid(r["p"]), qid(r["a"])
                if q in out and a != q and a.startswith("Q"):
                    adv = out[q]["advisors"]
                    if adv.get(a) != "phd":
                        adv[a] = rel
    for q in qids:
        out.setdefault(q, {"label": q, "mgp": set(), "bai": set(), "at": set(),
                           "orcid": set(), "advisors": {}, "human": False})
    return out


def lookup_by(prop, values):
    """Map external-id values (for property P549/P2930/P496/P2381) to QIDs."""
    res = {}
    for chunk in _chunks(sorted(set(values)), 200):
        rows = sparql("SELECT ?p ?v WHERE { VALUES ?v { %s } ?p wdt:%s ?v . }"
                      % (_strvalues(chunk), prop))
        for r in rows:
            res.setdefault(r["v"], qid(r["p"]))
    return res


def lookup_by_enwiki(titles):
    """Map English Wikipedia titles to QIDs via sitelinks."""
    import urllib.parse as up
    res = {}
    for chunk in _chunks(sorted(set(titles)), 100):
        urls = {"https://en.wikipedia.org/wiki/" + up.quote(t.replace(" ", "_"), safe="(),'!*:;@&=+$"): t
                for t in chunk}
        rows = sparql("SELECT ?art ?p WHERE { VALUES ?art { %s } ?art schema:about ?p . }"
                      % " ".join("<%s>" % u for u in urls))
        for r in rows:
            t = urls.get(r["art"])
            if t:
                res[t] = qid(r["p"])
    return res


def prize_winners(prize_qids):
    """[(person_qid, prize_qid, year or None)]"""
    rows = sparql("""
SELECT ?p ?aw ?time WHERE {
  VALUES ?aw { %s }
  ?p p:P166 ?st . ?st ps:P166 ?aw .
  OPTIONAL { ?st pq:P585 ?time }
  ?p wdt:P31 wd:Q5 .
}""" % _values(prize_qids))
    return [(qid(r["p"]), qid(r["aw"]), _year(r.get("time")))
            for r in rows]


def humans_by_label(labels):
    """Resolve English labels/aliases to human QIDs that have an enwiki article.

    Returns {label: [(qid, sitelinks)]} sorted by sitelinks desc."""
    out = {}
    for chunk in _chunks(sorted(set(labels)), 80):
        rows = sparql("""
SELECT DISTINCT ?l ?p ?n WHERE {
  VALUES ?l { %s }
  { ?p rdfs:label ?l } UNION { ?p skos:altLabel ?l }
  ?p wdt:P31 wd:Q5 ; wikibase:sitelinks ?n .
  ?art schema:about ?p ; schema:isPartOf <https://en.wikipedia.org/> .
}""" % " ".join('"%s"@en' % l.replace('"', '') for l in chunk))
        for r in rows:
            out.setdefault(r["l"], []).append((qid(r["p"]), int(r["n"])))
    for k in out:
        out[k].sort(key=lambda t: -t[1])
    return out


def english(label):
    """The label if it is a real English label (label service returns the QID otherwise)."""
    if not label or re.match(r"^Q\d+$", label):
        return None
    return label


def wiki_title(url):
    if not url:
        return None
    import urllib.parse as up
    t = up.unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")
    return t or None


def enrich(qids):
    """Biographical facts for display. Returns {qid: dict}."""
    out = {q: {"awards": [], "known_for": [], "named_after": [], "employers": [],
               "fields": [], "educated": []} for q in qids}
    for chunk in _chunks(sorted(set(qids)), 100):
        v = _values(chunk)
        for r in sparql("""
SELECT ?p ?en ?alt ?desc ?birth ?death ?bplaceLabel ?img ?wiki ?citLabel WHERE {
  VALUES ?p { %s }
  OPTIONAL { ?p rdfs:label ?en FILTER(LANG(?en)="en") }
  OPTIONAL { ?p rdfs:label ?alt FILTER(LANG(?alt) IN ("mul","de","fr","es","it","nl","sv","pl")) }
  OPTIONAL { ?p schema:description ?desc FILTER(LANG(?desc)="en") }
  OPTIONAL { ?p wdt:P569 ?birth }
  OPTIONAL { ?p wdt:P570 ?death }
  OPTIONAL { ?p wdt:P19 ?bplace }
  OPTIONAL { ?p wdt:P27 ?cit }
  OPTIONAL { ?p wdt:P18 ?img }
  OPTIONAL { ?wiki schema:about ?p ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % v):
            d = out[qid(r["p"])]
            if r.get("en"):
                d.setdefault("label_en", r["en"])
            if r.get("alt"):
                d.setdefault("label_alt", []).append(r["alt"])
            for k_src, k_dst in (("desc", "description"), ("birth", "birth"), ("death", "death"),
                                 ("bplaceLabel", "birthplace"), ("img", "image"), ("wiki", "wikipedia"),
                                 ("citLabel", "citizenship")):
                val = r.get(k_src)
                if k_src in ("bplaceLabel", "citLabel"):
                    val = english(val)
                if k_src in ("birth", "death") and val and val.startswith("http"):
                    val = None  # "unknown value"
                if val and not d.get(k_dst):
                    d[k_dst] = val
        for r in sparql("""
SELECT ?p ?aw ?awLabel ?time WHERE {
  VALUES ?p { %s }
  ?p p:P166 ?st . ?st ps:P166 ?aw . OPTIONAL { ?st pq:P585 ?time }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}""" % v):
            if not english(r.get("awLabel")):
                continue
            out[qid(r["p"])]["awards"].append({
                "qid": qid(r["aw"]), "label": r.get("awLabel"),
                "year": _year(r.get("time"))})
        for prop, key in (("P108", "employers"), ("P101", "fields"), ("P69", "educated")):
            for r in sparql("""
SELECT ?p ?xLabel WHERE { VALUES ?p { %s } ?p wdt:%s ?x .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }""" % (v, prop)):
                lst = out[qid(r["p"])][key]
                if english(r.get("xLabel")) and r["xLabel"] not in lst:
                    lst.append(r["xLabel"])
        for r in sparql("""
SELECT ?p ?x ?xLabel ?wiki WHERE { VALUES ?p { %s } ?p wdt:P800 ?x .
  OPTIONAL { ?wiki schema:about ?x ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }""" % v):
            # only works with an English Wikipedia article (labels of the rest
            # are often untranslated); the article title is the label
            lbl = wiki_title(r.get("wiki"))
            if lbl:
                out[qid(r["p"])]["known_for"].append({"label": lbl, "url": r["wiki"]})
        for r in sparql("""
SELECT ?p ?x ?xLabel ?xDesc ?wiki WHERE { VALUES ?p { %s } ?x wdt:P138 ?p .
  OPTIONAL { ?x schema:description ?xDesc FILTER(LANG(?xDesc)="en") }
  OPTIONAL { ?wiki schema:about ?x ; schema:isPartOf <https://en.wikipedia.org/> }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". } }""" % v):
            lbl = english(r.get("xLabel")) or wiki_title(r.get("wiki"))
            if not lbl:
                continue
            out[qid(r["p"])]["named_after"].append(
                {"label": lbl, "desc": r.get("xDesc"), "qid": qid(r["x"]),
                 "url": r.get("wiki") or r["x"], "wiki": bool(r.get("wiki"))})
    return out

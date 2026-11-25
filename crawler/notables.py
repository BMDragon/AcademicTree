"""Notable people: prize laureates (Wikidata) and quizbowl-canonical scientists (QB Reader)."""
import re
import urllib.parse

from . import http, wikidata

QB_FREQ = "https://www.qbreader.org/api/frequency-list"
# Occupations that make a QB answerline "a scientist" (subclass closure is used).
SCI_OCCUPATIONS = ["Q901", "Q170790", "Q39631", "Q81096", "Q82594", "Q11063", "Q593644",
                   "Q169470", "Q864503", "Q2374149", "Q1622272", "Q205375", "Q3055126"]


def prizes(prize_cfg):
    """{qid: [{"prize": prize_qid, "year": y}]}"""
    out = {}
    for q, pz, yr in wikidata.prize_winners(list(prize_cfg)):
        lst = out.setdefault(q, [])
        if not any(x["prize"] == pz and x["year"] == yr for x in lst):
            lst.append({"prize": pz, "year": yr})
    return out


def _looks_like_name(a):
    if re.search(r"[0-9<>(){}\[\]/]| or | and |'s\b", a):
        return False
    t = a.split()
    return 2 <= len(t) <= 5


PARTICLES = {"van", "von", "der", "de", "da", "di", "du", "la", "le", "del", "den", "ter"}


def _variants(a):
    """Title-cased label guesses: 'johannes van der waals' -> both
    'Johannes Van Der Waals' and 'Johannes van der Waals'."""
    words = [w.upper() if re.match(r"^[a-z]\.$", w) else w.capitalize() for w in a.split()]
    return {" ".join(words),
            " ".join(w.lower() if w.lower() in PARTICLES else w for w in words)}


def quizbowl(cfg, log=print):
    """{qid: count} for scientists answered >= min_count times in QB science questions."""
    url = QB_FREQ + "?" + urllib.parse.urlencode(
        {"category": cfg["category"], "level": "all", "limit": cfg["frequency_limit"]})
    js = http.get_json(url)
    if not js:
        log("  ! QB Reader frequency list unavailable")
        return {}
    entries = [e for e in js["frequencyList"] if _looks_like_name(e["answer_normalized"])]
    label_count = {}
    for e in entries:
        for v in _variants(e["answer_normalized"]):
            label_count.setdefault(v, {})[e["answer_normalized"]] = e["count"]
    log("  QB: %d name-like answerlines -> resolving %d labels on Wikidata"
        % (len(entries), len(label_count)))
    res = wikidata.humans_by_label(label_count)
    counts, seen = {}, {}
    for lbl, hits in res.items():
        q = hits[0][0]  # most-linked human with that label
        for ans, c in label_count[lbl].items():
            if ans not in seen.setdefault(q, set()):
                seen[q].add(ans)
                counts[q] = counts.get(q, 0) + c
    cand = [q for q, c in counts.items() if c >= cfg["min_count"]]
    sci = set()
    for i in range(0, len(cand), 150):
        chunk = cand[i:i + 150]
        rows = wikidata.sparql("""
SELECT DISTINCT ?p WHERE { VALUES ?p { %s } VALUES ?occ { %s }
  ?p wdt:P106/wdt:P279* ?occ . }""" % (" ".join("wd:" + q for q in chunk),
                                     " ".join("wd:" + o for o in SCI_OCCUPATIONS)))
        sci.update(wikidata.qid(r["p"]) for r in rows)
    return {q: counts[q] for q in cand if q in sci}

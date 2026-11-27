"""Notable people: prize laureates (Wikidata) and quizbowl-canonical scientists (QB Reader)."""
import re
import urllib.parse

from . import http, itemcache, wikidata

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


QB_QUERY = "https://www.qbreader.org/api/query"


def quizbowl_answers(cfg, log=print):
    """{qid: answerline count} for every scientist who is a QB science answerline at least once."""
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
    cand = sorted(counts)
    sci = itemcache.batched("qb.isscientist.v1", cand, _scientist_fetch)
    return {q: counts[q] for q in cand if sci.get(q)}


def _scientist_fetch(qids):
    out = {}
    for i in range(0, len(qids), 150):
        chunk = qids[i:i + 150]
        rows = wikidata.sparql("""
SELECT DISTINCT ?p WHERE { VALUES ?p { %s } VALUES ?occ { %s }
  ?p wdt:P106/wdt:P279* ?occ . }""" % (" ".join("wd:" + q for q in chunk),
                                     " ".join("wd:" + o for o in SCI_OCCUPATIONS)))
        out.update({wikidata.qid(r["p"]): True for r in rows})
    return {q: out.get(q, False) for q in qids}


def name_variants(name):
    """Full name, plus first+last without middle names/initials. Surname-only
    searches are not used (they match eponyms and collide across people)."""
    import re
    name = re.sub(r"\s*\([^)]*\)", "", name or "").strip()
    out = [name] if len(name.split()) >= 2 else []
    t = name.split()
    # drop middle *initials* only ("Barry C. Barish" -> "Barry Barish"); dropping
    # spelled-out middle names would turn "Charles Galton Darwin" into "Charles Darwin"
    if len(t) > 2 and all(re.fullmatch(r"[A-Z]\.?", m) for m in t[1:-1]):
        out.append(t[0] + " " + t[-1])
    return out


def mentions(name, category="Science", ambiguous=frozenset(), search_type="question"):
    """Number of QB questions (tossups + bonuses) whose text (search_type
    "question") or answerline ("answer") contains the name; category None =
    all subjects. Shortened variants in `ambiguous` are skipped."""
    best = 0
    for i, v in enumerate(name_variants(name)):
        if i > 0 and v in ambiguous:
            continue
        params = {"queryString": v, "searchType": search_type, "exactPhrase": "true", "maxReturnLength": 1}
        if category:
            params["categories"] = category
        js = http.get_json(QB_QUERY + "?" + urllib.parse.urlencode(params))
        if js:
            best = max(best, js.get("tossups", {}).get("count", 0) + js.get("bonuses", {}).get("count", 0))
    return best


def ambiguous_short_names(names):
    """Shortened 'First Last' variants that more than one notable person (enwiki
    article) carries as a label or alias, e.g. 'Robert Wilson'."""
    shorts = {v for n in names for v in name_variants(n)[1:]}
    if not shorts:
        return set()
    hits = wikidata.humans_by_label(shorts)
    return {s for s in shorts if len(hits.get(s, [])) != 1}


def mentions_many(names, category="Science", log=print, search_type="question"):
    """{key: count} for {key: name} (see mentions())."""
    from concurrent.futures import ThreadPoolExecutor
    keys = sorted(names)
    amb = frozenset(ambiguous_short_names(names.values()))
    # QB Reader allows ~20 requests/s; config paces us at ~12/s, with enough
    # threads in flight to keep that pace given ~0.4 s latency.
    with ThreadPoolExecutor(max_workers=8) as pool:
        vals = list(pool.map(lambda k: mentions(names[k], category, amb, search_type), keys))
    return dict(zip(keys, vals))

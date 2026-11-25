"""INSPIRE-HEP author records (advisors with degree type)."""
import re
import unicodedata
import urllib.parse

from . import http

API = "https://inspirehep.net/api/authors/"
DEGREE_MAP = {"phd": "phd", "bachelor": "undergrad", "master": "research",
              "habilitation": "postdoc", "other": "research", "laurea": "undergrad",
              "diploma": "research"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z ]+", " ", s).split()


def surname_of(inspire_name):
    """INSPIRE names are 'Last, First'."""
    return norm(inspire_name.split(",")[0])


def _parse(rec):
    m = rec.get("metadata") or {}
    nm = m.get("name") or {}
    ids = {i.get("schema"): i.get("value") for i in m.get("ids", [])}
    pos = []
    for p in m.get("positions", []):
        if p.get("institution"):
            pos.append({"institution": p["institution"], "rank": p.get("rank"),
                        "start": p.get("start_date"), "end": p.get("end_date"),
                        "current": p.get("current", False)})
    advisors = []
    for a in m.get("advisors", []):
        ref = (a.get("record") or {}).get("$ref", "")
        recid = ref.rsplit("/", 1)[-1] if ref else None
        advisors.append({"name": a.get("name"), "recid": recid,
                         "type": DEGREE_MAP.get(a.get("degree_type") or "other", "research")})
    return {"recid": str(m.get("control_number")),
            "name": nm.get("preferred_name") or _flip(nm.get("value", "")),
            "raw_name": nm.get("value", ""),
            "bai": ids.get("INSPIRE BAI"), "orcid": ids.get("ORCID"),
            "wikipedia": ids.get("WIKIPEDIA"),
            "positions": pos, "advisors": advisors}


def _flip(n):
    if "," in n:
        last, first = n.split(",", 1)
        return (first.strip() + " " + last.strip()).strip()
    return n


def fetch(recid):
    js = http.get_json(API + str(recid))
    if not js:
        return None
    return _parse(js)


def search(q, size=5):
    js = http.get_json(API + "?" + urllib.parse.urlencode({"q": q, "size": size}))
    if not js:
        return []
    return [_parse(h) for h in js.get("hits", {}).get("hits", [])]


def by_bai(bai):
    res = search('ids.value:"%s"' % bai, 1)
    return res[0] if res else None


def _name_ok(adv_name, rec):
    """Surname must match; first initials must agree when both are known."""
    if "," in (adv_name or ""):
        last, first = adv_name.split(",", 1)
    else:
        parts = (adv_name or "").split()
        last, first = (parts[-1] if parts else ""), " ".join(parts[:-1])
    have = norm(rec["raw_name"] + " " + rec["name"])
    if not norm(last) or not set(norm(last)) <= set(have):
        return False
    fi = norm(first)
    rn = rec["raw_name"].split(",", 1)
    rfirst = norm(rn[1]) if len(rn) > 1 else norm(rec["name"])[:-1]
    return not fi or not rfirst or fi[0][0] == rfirst[0][0]


def resolve_advisors(advs):
    """Map each advisor entry to its INSPIRE record (or None).

    INSPIRE sometimes attaches an advisor's $ref to the wrong record (e.g. two
    advisors' refs swapped), so records are matched to entries by name."""
    recs = [fetch(a["recid"]) for a in advs if a.get("recid")]
    recs = [r for r in recs if r]
    out = []
    for a in advs:
        hit = next((r for r in recs if _name_ok(a["name"], r)), None)
        if hit is None and a.get("name"):
            for r in search(a["name"], 5):
                if _name_ok(a["name"], r):
                    hit = r
                    break
        out.append(hit)
    return out

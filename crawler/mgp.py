"""Mathematics Genealogy Project scraper (id.php pages)."""
import html
import re

from . import http

BASE = "https://www.mathgenealogy.org/id.php?id="


def url(mid):
    return BASE + str(mid)


def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def fetch(mid):
    """Return {"name", "degrees": [{"degree","school","year"}], "thesis", "advisors": [id]}"""
    txt = http.get(url(mid))
    if not txt or "You have specified an ID that does not exist" in txt:
        return None
    m = re.search(r"<h2[^>]*>(.*?)</h2>", txt, re.S)
    if not m:
        return None
    name = _clean(m.group(1))
    degrees = []
    for dm in re.finditer(
            r'<span style="margin-right: 0.5em">(.*?)<span[^>]*>(.*?)</span>\s*([0-9]{4})?\s*</span>',
            txt, re.S):
        degrees.append({"degree": _clean(dm.group(1)), "school": _clean(dm.group(2)),
                        "year": int(dm.group(3)) if dm.group(3) else None})
    tm = re.search(r'id="thesisTitle">(.*?)</span>', txt, re.S)
    advisors = []
    for am in re.finditer(r"Advisor(?: \d+)?:\s*<a href=\"id\.php\?id=(\d+)\">", txt):
        if am.group(1) not in advisors:
            advisors.append(am.group(1))
    return {"name": name, "degrees": degrees,
            "thesis": _clean(tm.group(1)) if tm else None, "advisors": advisors}

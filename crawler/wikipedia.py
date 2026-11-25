"""English Wikipedia, batched: intro extract, thumbnail, infobox 'known_for'.

Uses the action API with many titles per request (extracts: 20, page images
and wikitext: 50) to stay far below Wikimedia's rate limits.
"""
import re
import urllib.parse

from . import http

API = "https://en.wikipedia.org/w/api.php"


def title_from_url(url):
    return urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1]).replace("_", " ")


def _query(params):
    params = dict(params, action="query", format="json", formatversion=2, redirects=1)
    js = http.get_json(API + "?" + urllib.parse.urlencode(params))
    if not js or "query" not in js:
        return {}, []
    q = js["query"]
    # map requested title -> final title (normalization + redirects)
    alias = {}
    for k in ("normalized", "redirects"):
        for x in q.get(k, []):
            alias[x["from"]] = x["to"]
    return alias, q.get("pages", [])


def _resolve(title, alias):
    seen = 0
    while title in alias and seen < 5:
        title = alias[title]
        seen += 1
    return title


def _batched(titles, n, params, take):
    out = {}
    titles = list(dict.fromkeys(titles))
    for i in range(0, len(titles), n):
        chunk = titles[i:i + n]
        alias, pages = _query(dict(params, titles="|".join(chunk)))
        bytitle = {p.get("title"): p for p in pages}
        for t in chunk:
            p = bytitle.get(_resolve(t, alias))
            if p:
                v = take(p)
                if v:
                    out[t] = v
    return out


def extracts(titles):
    return _batched(titles, 20, {"prop": "extracts", "exintro": 1, "explaintext": 1, "exlimit": 20},
                    lambda p: p.get("extract"))


def thumbnails(titles):
    return _batched(titles, 50, {"prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 200,
                                 "pilimit": 50},
                    lambda p: (p.get("thumbnail") or {}).get("source"))


def _infobox_field(wikitext, field):
    m = re.search(r"\|\s*%s\s*=(.*?)(?=\n\s*\|\s*[A-Za-z_ ]+\s*=|\n\}\})" % field, wikitext, re.S | re.I)
    return m.group(1) if m else ""


def parse_known_for(wikitext):
    field = _infobox_field(wikitext, "known[_ ]for")
    field = re.sub(r"<ref[^>]*/>|<ref.*?</ref>|<!--.*?-->", "", field, flags=re.S)
    out, seen = [], set()
    for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]", field):
        target = m.group(1).strip()
        label = re.sub(r"<[^>]+>", "", (m.group(2) or target)).strip()
        if re.search(r"[{}=\"<>]|''", label) or not label:
            label = target
        if target.lower().startswith(("file:", "image:", "category:")) or label in seen:
            continue
        seen.add(label)
        out.append({"label": label,
                    "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(target.replace(" ", "_"))})
    return out


def known_for(titles):
    def take(p):
        revs = p.get("revisions") or []
        if not revs:
            return None
        wt = revs[0].get("slots", {}).get("main", {}).get("content") or revs[0].get("content") or ""
        head = wt[:20000]  # infobox is at the top
        return parse_known_for(head) or None
    return _batched(titles, 50, {"prop": "revisions", "rvprop": "content", "rvslots": "main"}, take)

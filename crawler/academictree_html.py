"""Parser for academictree.org "peopleinfo.php" pages saved from a browser.

academictree.org sits behind a Cloudflare challenge, so pages can't be fetched
by script. Save a person's page (Ctrl+S, "Web page, HTML only") into
data/academictree_saved/ and rerun the build. The parser is deliberately
tolerant: it looks for the Parents / Children sections and reads each table
row's person link + relationship text.
"""
import glob
import html
import os
import re

TYPE_MAP = [
    (r"grad(uate)? student|ph\.?d|doctoral", "phd"),
    (r"post-?doc", "postdoc"),
    (r"research assistant|research scientist|lab tech|research", "research"),
    (r"undergrad|bachelor|honors|senior thesis", "undergrad"),
]


def edge_type(text):
    t = (text or "").lower()
    for pat, typ in TYPE_MAP:
        if re.search(pat, t):
            return typ
    return None  # collaborators etc. are not advising edges


def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


PID_RE = re.compile(r"peopleinfo\.php\?pid=(\d+)")


def parse(txt, filename=""):
    pid = None
    for pat in (r'<link[^>]+canonical[^>]+pid=(\d+)', r'og:url[^>]+pid=(\d+)',
                r"saved from url=[^\n]*pid=(\d+)", r"pid=(\d+)"):
        m = re.search(pat, txt)
        if m:
            pid = m.group(1)
            break
    fm = re.search(r"pid[=_-]?(\d+)", os.path.basename(filename))
    if fm:
        pid = fm.group(1)
    tm = re.search(r"<title>(.*?)</title>", txt, re.S | re.I)
    name = _clean(tm.group(1)) if tm else ""
    name = re.split(r"\s+[-|]\s+|\s*Family Tree", name)[0].strip()
    hm = re.search(r"<h1[^>]*>(.*?)</h1>", txt, re.S | re.I)
    if hm and _clean(hm.group(1)):
        name = _clean(hm.group(1))

    parents, children = [], []
    # Split on section headings that mention Parents / Children.
    sec = re.split(r"(?i)(>\s*Parents\s*<|>\s*Children\s*<|>\s*Collaborators\s*<)", txt)
    current = None
    for chunk in sec:
        low = chunk.lower()
        if re.match(r">\s*parents\s*<", low):
            current = parents
            continue
        if re.match(r">\s*children\s*<", low):
            current = children
            continue
        if re.match(r">\s*collaborators\s*<", low):
            current = None
            continue
        if current is None:
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", chunk, re.S | re.I):
            lm = re.search(r'<a[^>]+href="[^"]*peopleinfo\.php\?pid=(\d+)[^"]*"[^>]*>(.*?)</a>', row, re.S)
            if not lm or lm.group(1) == pid:
                continue
            cells = [_clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S | re.I)]
            rest = " ".join(cells)
            typ = edge_type(rest)
            if not typ:
                continue
            ym = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", rest)
            current.append({"pid": lm.group(1), "name": _clean(lm.group(2)), "type": typ,
                            "year": int(ym.group(1)) if ym else None, "text": rest[:200]})
    return {"pid": pid, "name": name, "parents": parents, "children": children}


def load_all(folder):
    out = []
    for f in sorted(glob.glob(os.path.join(folder, "*.htm*"))):
        with open(f, encoding="utf-8", errors="replace") as fh:
            rec = parse(fh.read(), f)
        if rec["pid"]:
            rec["file"] = os.path.basename(f)
            out.append(rec)
    return out

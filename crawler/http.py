"""Cached, rate-limited HTTP for the crawler (stdlib only).

Every response body is stored under data/cache/<host>/<sha1>, so reruns are
free and the crawl can be interrupted and resumed.
"""
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(ROOT, "data", "cache")
UA = "AcademicTree-local/0.1 (personal, non-commercial genealogy viewer; python-urllib)"

_rate = {}
_last = {}
_locks = {}
_glock = threading.Lock()
stats = {"hit": 0, "miss": 0, "err": 0}


def set_rate_limits(limits):
    _rate.update(limits)


def _host_lock(host):
    with _glock:
        if host not in _locks:
            _locks[host] = threading.Lock()
        return _locks[host]


def _wait(host):
    lock = _host_lock(host)
    with lock:
        gap = _rate.get(host, 0.5)
        now = time.time()
        t = _last.get(host, 0) + gap
        if t > now:
            time.sleep(t - now)
        _last[host] = time.time()


def _cache_path(host, key):
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()
    d = os.path.join(CACHE_DIR, host, h[:2])
    return os.path.join(d, h)


def get(url, data=None, headers=None, retries=4, cache=True):
    """Return response text (str) or None on 404 / persistent failure."""
    host = urllib.parse.urlparse(url).netloc
    key = url + ("\n" + data if data else "")
    path = _cache_path(host, key)
    if cache and os.path.exists(path):
        stats["hit"] += 1
        with open(path, encoding="utf-8") as f:
            txt = f.read()
        return None if txt == "\x00404" else txt
    stats["miss"] += 1
    hdrs = {"User-Agent": UA, "Accept-Encoding": "identity"}
    if headers:
        hdrs.update(headers)
    body = data.encode("utf-8") if data is not None else None
    for attempt in range(retries):
        _wait(host)
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs)
            with urllib.request.urlopen(req, timeout=90) as r:
                raw = r.read()
            txt = raw.decode("utf-8", errors="replace")
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                txt = "\x00404"
                break
            if e.code in (429, 500, 502, 503, 504):
                ra = e.headers.get("Retry-After")
                time.sleep(float(ra) if ra and ra.isdigit() else 5 * (attempt + 1))
                continue
            stats["err"] += 1
            return None
        except Exception:
            time.sleep(3 * (attempt + 1))
    else:
        stats["err"] += 1
        return None
    if cache:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp%d" % threading.get_ident()
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(txt)
        os.replace(tmp, path)
    return None if txt == "\x00404" else txt


def get_json(url, **kw):
    txt = get(url, **kw)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except ValueError:
        return None

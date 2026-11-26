"""Per-item cache for batched lookups.

The HTTP cache (http.py) is keyed by the whole request, so a batched query
for 150 people misses as soon as the batch composition changes (e.g. one new
person shifts every later batch). This layer caches each item's result
separately (SQLite, data/cache/items.sqlite): only items never seen before
are fetched, in fresh batches.
"""
import json
import os
import sqlite3
import threading

from .http import CACHE_DIR

_lock = threading.Lock()
_db = None


def _conn():
    global _db
    if _db is None:
        os.makedirs(CACHE_DIR, exist_ok=True)
        _db = sqlite3.connect(os.path.join(CACHE_DIR, "items.sqlite"), check_same_thread=False)
        _db.execute("CREATE TABLE IF NOT EXISTS item (ns TEXT, k TEXT, v TEXT, PRIMARY KEY (ns, k))")
        _db.commit()
    return _db


def batched(ns, keys, fetch, encode=None, decode=None):
    """Return {key: value} for keys, calling fetch(missing_keys) -> {key: value}
    only for keys not cached under namespace `ns`. Keys absent from fetch's
    result are cached as None (so negative results are not re-fetched)."""
    keys = list(dict.fromkeys(keys))
    out = {}
    with _lock:
        db = _conn()
        for i in range(0, len(keys), 500):
            chunk = keys[i:i + 500]
            q = "SELECT k, v FROM item WHERE ns=? AND k IN (%s)" % ",".join("?" * len(chunk))
            for k, v in db.execute(q, [ns] + chunk):
                val = json.loads(v)
                out[k] = decode(val) if (decode and val is not None) else val
    missing = [k for k in keys if k not in out]
    if missing:
        got = fetch(missing) or {}
        rows = []
        for k in missing:
            val = got.get(k)
            out[k] = val
            enc = encode(val) if (encode and val is not None) else val
            rows.append((ns, k, json.dumps(enc, ensure_ascii=False)))
        with _lock:
            db = _conn()
            db.executemany("INSERT OR REPLACE INTO item VALUES (?, ?, ?)", rows)
            db.commit()
    return out

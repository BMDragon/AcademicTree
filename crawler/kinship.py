"""Academic kinship naming.

The graph is a DAG of advising edges child -> parent. For a person X and the
root ("me"), find the common ancestor A minimizing generations; with
m = generations from me up to A and n = generations from X up to A the
relation is named as in human genealogy.
"""
from collections import deque

ORD = {1: "1st", 2: "2nd", 3: "3rd"}
TIMES = {1: "once", 2: "twice", 3: "thrice"}


def ordinal(k):
    if k in ORD:
        return ORD[k]
    if 10 <= k % 100 <= 20:
        return "%dth" % k
    return "%d%s" % (k, {1: "st", 2: "nd", 3: "rd"}.get(k % 10, "th"))


def _greats(k, base):
    """k=0 -> base, 1 -> great-base, 2 -> 2x great-base ..."""
    if k <= 0:
        return base
    if k == 1:
        return "great-" + base
    return "%d× great-%s" % (k, base)


def name(m, n):
    """Relation of X to me, with m = my distance to the common ancestor and
    n = X's distance to it."""
    if m == 0 and n == 0:
        return "self"
    if n == 0:  # X is my ancestor
        if m == 1:
            return "parent"
        if m == 2:
            return "grandparent"
        return _greats(m - 2, "grandparent")
    if m == 0:  # X is my descendant
        if n == 1:
            return "child"
        if n == 2:
            return "grandchild"
        return _greats(n - 2, "grandchild")
    if m == 1 and n == 1:
        return "sibling"
    if m == 1:  # X descends from my parent: niece/nephew line
        if n == 2:
            return "niece/nephew"
        return _greats(n - 3, "grand-niece/nephew")
    if n == 1:  # X is a sibling of my ancestor
        if m == 2:
            return "aunt/uncle"
        return _greats(m - 3, "grand-aunt/uncle")
    deg, rem = min(m, n) - 1, abs(m - n)
    s = "%s cousin" % ordinal(deg)
    if rem:
        s += " " + TIMES.get(rem, "%d times" % rem) + " removed"
    return s


def up_distances(start, parents):
    """BFS upward: {ancestor: generations} including start at 0."""
    dist = {start: 0}
    q = deque([start])
    while q:
        x = q.popleft()
        for p in parents.get(x, ()):
            if p not in dist:
                dist[p] = dist[x] + 1
                q.append(p)
    return dist


def relations(me, nodes, parents, max_alternates=3):
    """For each node: {"label", "m", "n", "via", "alternates": [...]}.

    parents: {child: [parent,...]} restricted to the edge set of this mode.
    """
    mine = up_distances(me, parents)
    out = {}
    for x in nodes:
        dx = up_distances(x, parents)
        common = {a for a in dx if a in mine}
        # Only lowest common ancestors give distinct relations; an ancestor
        # of another common ancestor just restates the same kinship further up.
        higher = {p for c in common for p in parents.get(c, ()) if p in common}
        cands = [(mine[a] + dx[a], min(mine[a], dx[a]), mine[a], dx[a], a)
                 for a in common - higher]
        if not cands:
            out[x] = None
            continue
        cands.sort()
        best = cands[0]
        seen, alts = {name(best[2], best[3])}, []
        for c in cands[1:]:
            lbl = name(c[2], c[3])
            if lbl not in seen:
                seen.add(lbl)
                alts.append({"label": lbl, "m": c[2], "n": c[3], "via": c[4]})
            if len(alts) >= max_alternates:
                break
        out[x] = {"label": name(best[2], best[3]), "m": best[2], "n": best[3],
                  "via": best[4], "alternates": alts}
    return out


def relations_phd_primary(me, nodes, parents_all, parents_phd):
    """PhD-only lineage where it connects; fall back to all edges otherwise."""
    phd = relations(me, nodes, parents_phd)
    allr = relations(me, nodes, parents_all)
    out = {}
    for x in nodes:
        if phd.get(x):
            out[x] = dict(phd[x], fallback=False)
        elif allr.get(x):
            out[x] = dict(allr[x], fallback=True)
        else:
            out[x] = None
    return out

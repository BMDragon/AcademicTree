"""Build web/data/graph.json.

    python3 -m crawler.build            # full build (cached HTTP; reruns are fast)
    python3 -m crawler.build --no-qb    # skip quizbowl lookup

Pipeline: seeds + notable people -> crawl advisors upward across Wikidata,
INSPIRE-HEP, Math Genealogy and saved academictree pages -> merge identities
(union-find over source IDs) -> keep my ancestors plus every path from one of
them down to a notable person -> enrich -> kinship -> JSON.
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from . import academictree_html, http, inspire, kinship, layouts, mgp, names, notables, stem, wikidata, wikipedia

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TYPE_RANK = {"phd": 0, "postdoc": 1, "undergrad": 2, "research": 3}
SRC_RANK = {"wd": 0, "insp": 1, "mgp": 2, "at": 3, "nm": 4, "bai": 5, "me": -1}


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # deterministic representative: best source kind, then smallest id
            if (SRC_RANK[rb.split(":")[0]], rb) < (SRC_RANK[ra.split(":")[0]], ra):
                ra, rb = rb, ra
            self.p[rb] = ra
        return ra


class Crawler:
    def __init__(self, cfg):
        self.cfg = cfg
        self.uf = UF()
        self.info = {}      # ref -> dict(name=..., plus source specific fields)
        self.adv = {}       # ref -> {advisor_ref: type}
        self.depth = {}     # ref -> generations above the nearest root
        self.expanded = set()
        self.pending = set()
        self.saved_at = {}
        self.bai_done = {}
        self.orcid_done = {}
        self.nonhuman = set()  # Wikidata items that are not people (schools etc.)
        self.name_tried = set()  # groups already tried for Wikidata name matching

    # ----- bookkeeping -------------------------------------------------
    def add(self, ref, depth):
        if ref not in self.depth or depth < self.depth[ref]:
            self.depth[ref] = depth
        self.uf.find(ref)
        if ref not in self.expanded:
            self.pending.add(ref)

    def same(self, a, b):
        d = min(self.depth.get(a, 99), self.depth.get(b, 99))
        self.add(a, d)
        self.add(b, d)
        self.uf.union(a, b)

    def add_adv(self, child, parent, typ):
        cur = self.adv.setdefault(child, {})
        if parent not in cur or TYPE_RANK[typ] < TYPE_RANK[cur[parent]]:
            cur[parent] = typ
        self.add(parent, self.depth.get(child, 0) + 1)

    # ----- expansion per source ---------------------------------------
    def expand_wd(self, refs):
        qids = [r[3:] for r in refs]
        data = wikidata.links(qids)
        for q, d in data.items():
            r = "wd:" + q
            self.info.setdefault(r, {})["name"] = d["label"]
            if not d["human"]:
                self.nonhuman.add(r)
                continue
            cutoff = self.cfg.get("student_of_min_birth_year", 1400)
            by = d.get("birth_year")
            for a, typ in d["advisors"].items():
                # Wikidata "student of" (P1066/P802) is loose; before ~1400 it
                # mostly encodes chains of religious transmission, not advising.
                if typ == "research" and (by is None or by < cutoff):
                    continue
                self.add_adv(r, "wd:" + a, typ)
            if self.cfg["sources"]["mgp"]:
                for m in d["mgp"]:
                    self.same(r, "mgp:" + m)
            for at in d["at"]:
                self.same(r, "at:" + at)
            if self.cfg["sources"]["inspire"]:
                # "bai:" refs are resolved by INSPIRE id search, which also
                # accepts ORCIDs; use ORCID when Wikidata lacks the INSPIRE BAI.
                for b in d["bai"] or d["orcid"]:
                    self.same(r, "bai:" + b)

    def expand_bai(self, ref):
        rec = inspire.by_bai(ref[4:])
        return ref, rec

    def expand_insp(self, ref):
        rec = inspire.fetch(ref[5:])
        if not rec:
            return ref, None, []
        advs = inspire.resolve_advisors(rec["advisors"]) if rec["advisors"] else []
        return ref, rec, list(zip(rec["advisors"], advs))

    def expand_mgp(self, ref):
        return ref, mgp.fetch(ref[4:])

    def run(self):
        maxd = self.cfg["max_generations"]
        rnd = 0
        pool = ThreadPoolExecutor(max_workers=8)
        while self.pending:
            rnd += 1
            batch = {r for r in self.pending if self.depth.get(r, 0) <= maxd} - self.expanded
            self.pending.clear()
            if not batch:
                break
            self.expanded |= batch
            kinds = {}
            for r in batch:
                kinds.setdefault(r.split(":", 1)[0], []).append(r)
            log("round %d: %s  (http %s)" % (rnd, {k: len(v) for k, v in sorted(kinds.items())}, http.stats))
            new_mgp, new_bai, new_orcid, new_at = set(), set(), set(), set()
            new_wiki = {}

            if kinds.get("wd"):
                self.expand_wd(kinds["wd"])

            for ref, rec in pool.map(self.expand_bai, kinds.get("bai", [])):
                if rec:
                    self.same(ref, "insp:" + rec["recid"])

            for ref, rec, advs in pool.map(self.expand_insp, kinds.get("insp", [])):
                if not rec:
                    continue
                self.info.setdefault(ref, {}).update(name=rec["name"], positions=rec["positions"])
                if rec["bai"]:
                    new_bai.add(rec["bai"])
                    self.bai_done[rec["bai"]] = ref
                if rec.get("wikipedia"):
                    new_wiki[rec["wikipedia"].replace("_", " ")] = ref
                if rec["orcid"]:
                    new_orcid.add(rec["orcid"])
                    self.orcid_done[rec["orcid"]] = ref
                for entry, arec in advs:
                    if arec:
                        aref = "insp:" + arec["recid"]
                    else:
                        aref = "nm:%s|%s" % (entry["name"], ref)
                        nm = entry["name"]
                        if "," in nm:
                            last, first = nm.split(",", 1)
                            nm = first.strip() + " " + last.strip()
                        self.info[aref] = {"name": nm}
                        self.expanded.add(aref)
                    self.add_adv(ref, aref, entry["type"])

            for ref, rec in pool.map(self.expand_mgp, kinds.get("mgp", [])):
                if not rec:
                    continue
                self.info.setdefault(ref, {}).update(name=rec["name"], degrees=rec["degrees"],
                                                     thesis=rec["thesis"])
                new_mgp.add(ref[4:])
                for a in rec["advisors"]:
                    self.add_adv(ref, "mgp:" + a, "phd")

            for ref in kinds.get("at", []):
                new_at.add(ref[3:])
                page = self.saved_at.get(ref[3:])
                if page:
                    self.info.setdefault(ref, {})["name"] = page["name"]
                    for p in page["parents"]:
                        self.info.setdefault("at:" + p["pid"], {}).setdefault("name", p["name"])
                        self.add_adv(ref, "at:" + p["pid"], p["type"])

            # crosswalk: external ids -> Wikidata
            for prop, vals, pre in (("P549", new_mgp, "mgp:"), ("P2381", new_at, "at:")):
                if vals:
                    for v, q in wikidata.lookup_by(prop, vals).items():
                        self.same(pre + v, "wd:" + q)
            if new_bai:
                for v, q in wikidata.lookup_by("P2930", new_bai).items():
                    self.same(self.bai_done[v], "wd:" + q)
            if new_wiki:
                for t, q in wikidata.lookup_by_enwiki(list(new_wiki)).items():
                    self.same(new_wiki[t], "wd:" + q)
            if new_orcid:
                for v, q in wikidata.lookup_by("P496", new_orcid).items():
                    self.same(self.orcid_done[v], "wd:" + q)
            if self.cfg["sources"].get("wikidata_name_match", True):
                self.resolve_unlinked()
        pool.shutdown()

    def resolve_unlinked(self):
        """Link people known only from academictree/INSPIRE/MGP to Wikidata.

        Candidates are Wikidata humans whose English label equals the person's
        name (or first+last without middle initials); a candidate is accepted
        only if one of its Wikidata advisors matches, by name, one of the
        person's advisors or students already in the crawl, and only if exactly
        one candidate is confirmed. Example: academictree's Bruno Pontecorvo ->
        Wikidata Q453557 (confirmed by advisor Enrico Fermi)."""
        uf = self.uf
        groups = {}
        for r in list(uf.p):
            if not r.startswith("bai:"):
                groups.setdefault(uf.find(r), set()).add(r)
        nbr = {}
        for c, advs in self.adv.items():
            for a in advs:
                nbr.setdefault(uf.find(c), set()).add(uf.find(a))
                nbr.setdefault(uf.find(a), set()).add(uf.find(c))
        todo = {}
        for g, refs in groups.items():
            if g in self.name_tried or any(r.startswith("wd:") for r in refs) or g not in nbr:
                continue
            self.name_tried.add(g)
            nm = best_name(refs, self.info)
            if ":" in nm or len(nm.split()) < 2:
                continue
            todo[g] = [nm] + notables.name_variants(nm)[1:]
        if not todo:
            return
        hits = wikidata.humans_by_label({v for vs in todo.values() for v in vs})
        cands = {g: {q for v in vs for q, _ in hits.get(v, [])} for g, vs in todo.items()}
        allc = sorted({q for qs in cands.values() for q in qs})
        if not allc:
            return
        cl = wikidata.links(allc)
        advq = sorted({a for q in allc for a in cl[q]["advisors"]})
        advname = {a: d["label"] for a, d in wikidata.links(advq).items()} if advq else {}
        linked = []
        for g, qs in cands.items():
            mine = {best_name(groups.get(x, {x}), self.info) for x in nbr.get(g, ())}
            ok = [q for q in qs
                  if any(names.same_person(advname.get(a, ""), m) for a in cl[q]["advisors"] for m in mine)]
            if len(ok) == 1:
                self.same(g, "wd:" + ok[0])
                linked.append("%s -> %s" % (best_name(groups[g], self.info), ok[0]))
        if linked:
            log("  linked %d people to Wikidata by name + shared advisor: %s"
                % (len(linked), "; ".join(linked[:30])))


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
INSTITUTION = re.compile(
    r"\b(Gymnasium|School|Schule|University|Universit[äé]t|Universit[ée]|College|Academy|Akademie|"
    r"Institute|Institut|Lyceum|Lyc[ée]e|Hochschule|Seminary|Seminar)\b")


def best_name(refs, info):
    for kind in ("wd", "insp", "mgp", "at", "nm"):
        for r in sorted(refs):
            if r.startswith(kind + ":"):
                n = (info.get(r) or {}).get("name")
                if n and not (kind == "wd" and n == r[3:]):
                    return n
    return sorted(refs)[0]


def merge_by_neighbour_names(cr):
    """Union groups X, Y (not two distinct Wikidata items) whose names match and
    that have a matching-name advisor or student. Returns True if anything merged."""
    uf = cr.uf
    for c in cr.adv:  # students known only as children on saved pages
        uf.find(c)
    groups = {}
    for r in list(uf.p):
        groups.setdefault(uf.find(r), set()).add(r)
    name = {g: best_name(refs, cr.info) for g, refs in groups.items()}
    nbr = {}
    for c, advs in cr.adv.items():
        gc = uf.find(c)
        for a in advs:
            ga = uf.find(a)
            nbr.setdefault(gc, set()).add(ga)
            nbr.setdefault(ga, set()).add(gc)
    by_key = {}
    for g in groups:
        if g.startswith(("bai:",)) or g == "me":
            continue
        k = names.key(name[g])
        if k:
            by_key.setdefault(k[0], []).append(g)
    merged = False
    for gs in by_key.values():
        if len(gs) < 2 or len(gs) > 200:
            continue
        for i, a in enumerate(gs):
            for b in gs[i + 1:]:
                ra, rb = uf.find(a), uf.find(b)
                if ra == rb or not names.same_person(name[a], name[b]):
                    continue
                if any(x.startswith("wd:") for x in groups[a]) and any(x.startswith("wd:") for x in groups[b]):
                    continue
                # neighbours other than a/b themselves (a father advising a
                # same-named son must not count as a shared neighbour)
                na = {name.get(uf.find(x), "") for x in nbr.get(a, ()) if uf.find(x) not in (ra, rb)}
                nb = {name.get(uf.find(x), "") for x in nbr.get(b, ()) if uf.find(x) not in (ra, rb)}
                if any(names.same_person(x, y) for x in na for y in nb):
                    uf.union(a, b)
                    merged = True
    return merged


def assemble(cr, me_edges):
    """Return (groups, parents) where parents[child] = {parent: (type, set(sources))}."""
    uf = cr.uf
    # merge co-advisors of the same student that are clearly one person, and
    # (for sources without shared IDs, e.g. saved academictree pages) people
    # whose names match and who share an advisor or student by name
    changed = True
    while changed:
        changed = merge_by_neighbour_names(cr)
        by_child = {}
        for c, advs in cr.adv.items():
            for a in advs:
                by_child.setdefault(uf.find(c), set()).add(uf.find(a))
        groups = {}
        for r in uf.p:
            groups.setdefault(uf.find(r), set()).add(r)
        for c, advs in by_child.items():
            advs = sorted(advs)
            for i, a in enumerate(advs):
                for b in advs[i + 1:]:
                    if uf.find(a) == uf.find(b):
                        continue
                    if names.same_person(best_name(groups[a], cr.info), best_name(groups[b], cr.info)):
                        # never merge two distinct Wikidata items
                        wa = {x for x in groups[a] if x.startswith("wd:")}
                        wb = {x for x in groups[b] if x.startswith("wd:")}
                        # Two Wikidata items are only merged when full names
                        # match exactly (Wikidata has duplicate items).
                        if wa and wb and names.tokens(best_name(groups[a], cr.info)) != \
                                names.tokens(best_name(groups[b], cr.info)):
                            continue
                        uf.union(a, b)
                        changed = True
    groups = {}
    for r in uf.p:
        if r.startswith("bai:"):
            continue
        groups.setdefault(uf.find(r), set()).add(r)
    # Drop advisors that are not people: Wikidata items that are not humans, or
    # (for people known only from other sources) institution-like names.
    bad = set()
    for g, refs in groups.items():
        wds = {r for r in refs if r.startswith("wd:")}
        if wds:
            if wds <= cr.nonhuman:
                bad.add(g)
        elif INSTITUTION.search(best_name(refs, cr.info)):
            bad.add(g)
    if bad:
        log("dropping %d non-person nodes: %s" % (len(bad), sorted(best_name(groups[g], cr.info) for g in bad)[:10]))
    for g in bad:
        del groups[g]
    parents = {}
    for c, advs in cr.adv.items():
        gc = uf.find(c)
        if gc in bad:
            continue
        for a, typ in advs.items():
            ga = uf.find(a)
            if ga == gc or ga in bad:
                continue
            cur = parents.setdefault(gc, {}).get(ga)
            src = c.split(":")[0]
            if cur is None:
                parents[gc][ga] = [typ, {src}]
            else:
                if TYPE_RANK[typ] < TYPE_RANK[cur[0]]:
                    cur[0] = typ
                cur[1].add(src)
    parents["me"] = {uf.find(ref): [typ, {"config"}] for ref, typ in me_edges}
    groups["me"] = {"me"}
    return groups, parents


def break_cycles(parents):
    """Drop back edges so the advising graph is a DAG."""
    color, dropped = {}, []
    sys.setrecursionlimit(100000)

    def dfs(x):
        color[x] = 1
        for p in list(parents.get(x, {})):
            c = color.get(p, 0)
            if c == 1:
                dropped.append((x, p))
                del parents[x][p]
            elif c == 0:
                dfs(p)
        color[x] = 2

    for x in list(parents):
        if color.get(x, 0) == 0:
            dfs(x)
    return dropped


def ancestors(x, parents):
    seen, stack = set(), [x]
    while stack:
        y = stack.pop()
        for p in parents.get(y, ()):
            if p not in seen:
                seen.add(p)
                stack.append(p)
    return seen


def select(parents, notable_groups):
    anc = ancestors("me", parents)
    base = anc | {"me"}
    connected = {}

    def conn(x):
        """Is x in my ancestry, or descended from someone who is?"""
        if x not in connected:
            connected[x] = False  # graph is a DAG; placeholder guards bad data
            connected[x] = x in base or any(conn(p) for p in parents.get(x, ()))
        return connected[x]

    keep = set(base)
    for n in notable_groups:
        if n in base or not conn(n):
            continue
        # walk up from the notable through connected nodes only
        stack = [n]
        while stack:
            y = stack.pop()
            if y in keep:
                continue
            keep.add(y)
            stack.extend(p for p in parents.get(y, ()) if conn(p) and p not in base)
    return anc, keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-qb", action="store_true")
    ap.add_argument("--no-enrich", action="store_true")
    ap.add_argument("--no-layout", action="store_true", help="skip precomputing the page layout")
    args = ap.parse_args()
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    http.set_rate_limits(cfg["rate_limit_seconds"])
    cr = Crawler(cfg)

    # saved academictree pages
    saved_dir = os.path.join(ROOT, "data", "academictree_saved")
    if cfg["sources"]["academictree_saved"]:
        for page in academictree_html.load_all(saved_dir):
            cr.saved_at[page["pid"]] = page
            for ch in page["children"]:
                cr.info.setdefault("at:" + ch["pid"], {}).setdefault("name", ch["name"])
                cr.adv.setdefault("at:" + ch["pid"], {})["at:" + page["pid"]] = ch["type"]
        log("saved academictree pages: %d" % len(cr.saved_at))

    me_edges = []
    for s in cfg["me"]["advisors"]:
        refs = []
        if s.get("wikidata"):
            refs.append("wd:" + s["wikidata"])
        if s.get("inspire"):
            refs.append("insp:" + s["inspire"])
        if s.get("mgp"):
            refs.append("mgp:" + s["mgp"])
        if s.get("academictree"):
            refs.append("at:" + s["academictree"])
        for r in refs:
            cr.add(r, 1)
            cr.uf.union(refs[0], r)
        cr.info.setdefault(refs[0], {})["name"] = s["name"]
        me_edges.append((refs[0], s["type"]))
    # saved academictree pages for people already referenced by pid
    for pid in cr.saved_at:
        cr.add("at:" + pid, 1)

    log("notables: prize laureates")
    prizes = notables.prizes(cfg["prizes"])
    log("  %d laureates" % len(prizes))
    qb_ans, qb_men, qb_canon = {}, {}, set()
    qcfg = cfg["quizbowl"]
    if not args.no_qb:
        log("notables: quizbowl (QB Reader, %s)" % qcfg["category"])
        qb_ans = notables.quizbowl_answers(qcfg, log=log)
        labels = {q: d["label"] for q, d in wikidata.links(list(qb_ans)).items()}
        log("  counting question-text mentions for %d QB scientists" % len(labels))
        qb_men = notables.mentions_many(labels, qcfg["category"])
        qb_canon = {q for q in qb_ans if qb_ans[q] >= qcfg["min_count"]
                    or qb_men.get(q, 0) > qcfg["mentions_more_than"]}
        log("  %d quizbowl-canonical scientists (>= %d answerlines or > %d question mentions)"
            % (len(qb_canon), qcfg["min_count"], qcfg["mentions_more_than"]))
    for q in set(prizes) | qb_canon:
        cr.add("wd:" + q, 0)

    log("crawling advisor lineages")
    cr.run()

    groups, parents = assemble(cr, me_edges)
    dropped = break_cycles(parents)
    if dropped:
        log("dropped %d cycle edges" % len(dropped))
    find = cr.uf.find
    notable_groups = {find("wd:" + q) for q in set(prizes) | qb_canon}  # any of a person's items
    anc, keep = select(parents, notable_groups)
    log("ancestors: %d   kept nodes: %d" % (len(anc), len(keep)))

    sub = {c: {p: v for p, v in ps.items() if p in keep} for c, ps in parents.items() if c in keep}
    par_all = {c: list(ps) for c, ps in sub.items()}
    par_phd = {c: [p for p, v in ps.items() if v[0] == "phd"] for c, ps in sub.items()}
    nodes = sorted(keep - {"me"})
    rel_all = kinship.relations("me", nodes, par_all)
    rel_phd = kinship.relations_phd_primary("me", nodes, par_all, par_phd)

    # ---- node records -------------------------------------------------
    recs = {}
    for g in keep:
        refs = groups.get(g, {g})
        r = {"id": g, "name": best_name(refs, cr.info) if g != "me" else cfg["me"]["name"]}
        # A person can carry several Wikidata items (Wikidata has duplicates,
        # e.g. "Hugh David Politzer" and an author item "David Politzer").
        # Pick the main one deterministically: prize winners and QB notables
        # first, then the lowest QID (older items are the curated ones).
        qids = sorted((x[3:] for x in refs if x.startswith("wd:")), key=lambda q: int(q[1:]))
        if qids:
            r["qid"] = sorted(qids, key=lambda q: (q not in prizes, q not in qb_ans, int(q[1:])))[0]
        for ref in sorted(refs):
            if ":" not in ref:
                continue
            kind, val = ref.split(":", 1)
            if kind == "wd":
                continue
            elif kind == "insp":
                r.setdefault("inspire", val)
                inf = cr.info.get(ref, {})
                if inf.get("positions"):
                    r.setdefault("positions", inf["positions"])
            elif kind == "mgp":
                r.setdefault("mgp", val)
                inf = cr.info.get(ref, {})
                if inf.get("degrees"):
                    r.setdefault("degrees", inf["degrees"])
                    r.setdefault("thesis", inf.get("thesis"))
            elif kind == "at":
                r.setdefault("academictree", val)
        r["prizes"], seen_pz = [], set()
        for q in qids:  # prizes / QB data from any of the person's items
            for pz in prizes.get(q, []):
                if (pz["prize"], pz["year"]) in seen_pz:
                    continue
                seen_pz.add((pz["prize"], pz["year"]))
                pc = cfg["prizes"][pz["prize"]]
                r["prizes"].append({"key": pc["key"], "field": pc["field"], "label": pc["label"],
                                    "year": pz["year"]})
            if q in qb_ans:
                r["qb"] = max(r.get("qb", 0), qb_ans[q])
            if q in qb_men:
                r["qb_mentions"] = max(r.get("qb_mentions", 0), qb_men[q])
        r["prizes"].sort(key=lambda x: (x["year"] or 9999))
        r["ancestor"] = g in anc
        r["notable"] = g in notable_groups
        r["relation"] = rel_all.get(g)
        r["relation_phd"] = rel_phd.get(g)
        recs[g] = r

    # human-readable "via" names
    for r in recs.values():
        for k in ("relation", "relation_phd"):
            rel = r.get(k)
            if rel:
                rel["via_name"] = recs[rel["via"]]["name"] if rel["via"] in recs else None
                for alt in rel.get("alternates", []):
                    alt["via_name"] = recs[alt["via"]]["name"] if alt["via"] in recs else None

    if not args.no_enrich:
        enrich(recs, cfg)
        dedupe_known_for(recs)
    if not args.no_qb:
        # question-text mentions for everyone else in the tree (badges)
        todo = {g: r["name"] for g, r in recs.items() if g != "me" and "qb_mentions" not in r}
        log("counting QB question mentions for %d more people in the tree" % len(todo))
        for g, m in notables.mentions_many(todo, qcfg["category"]).items():
            recs[g]["qb_mentions"] = m
    for r in recs.values():
        r["qb_canon"] = (r.get("qb", 0) >= qcfg["min_count"]
                         or r.get("qb_mentions", 0) > qcfg["mentions_more_than"])
        if r["qb_canon"]:
            r["notable"] = True

    edges = []
    for c, ps in sub.items():
        for p, (typ, srcs) in ps.items():
            edges.append({"source": p, "target": c, "type": typ, "sources": sorted(srcs)})

    report_missing(recs, sub, anc)
    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "me": "me",
           "nodes": sorted(recs.values(), key=lambda r: r["id"]), "edges": edges,
           "stats": {"nodes": len(recs), "edges": len(edges), "ancestors": len(anc),
                     "laureates": {k: sum(1 for r in recs.values() if any(p["key"] == k for p in r["prizes"]))
                                   for k in ("nobel", "fields", "turing", "wolf")},
                     "quizbowl": sum(1 for r in recs.values() if r.get("qb_canon"))}}
    sanity(out)
    write_output(out)
    log("wrote web/data/graph.json + details.json  %s" % json.dumps(out["stats"]))
    if not args.no_layout:
        layouts.precompute(log=log)
    log("http %s" % http.stats)


def _latin(s):
    import unicodedata
    return all(not ch.isalpha() or unicodedata.name(ch, "").startswith("LATIN") for ch in s or "")


def english_name(current, d):
    """English display name: Wikidata English label, else the English Wikipedia
    title (minus any '(physicist)' qualifier), else the current name."""
    import re
    if d.get("label_en") and _latin(d["label_en"]):
        return d["label_en"]
    if d.get("wikipedia"):
        t = re.sub(r"\s*\([^)]*\)$", "", wikipedia.title_from_url(d["wikipedia"]))
        if t:
            return t
    if _latin(current):
        return current
    for alt in d.get("label_alt", []):  # e.g. the German label
        if _latin(alt):
            return alt
    return current


def enrich(recs, cfg):
    qids = [r["qid"] for r in recs.values() if r.get("qid")]
    log("enriching %d Wikidata people" % len(qids))
    wd = wikidata.enrich(qids)
    byq = {r["qid"]: r for r in recs.values() if r.get("qid")}
    # "Named after them": keep STEM topics only (equations, effects, units,
    # elements, theorems...), not awards, schools, asteroids or streets.
    named = {x["qid"] for d in wd.values() for x in d["named_after"]}
    log("classifying %d named-after items (STEM filter)" % len(named))
    stem_ok = stem.stem_items(named)
    for d in wd.values():
        d["named_after"] = [x for x in d["named_after"]
                            if x["qid"] in stem_ok and not stem.looks_institutional(x["label"])]
    for q, d in wd.items():
        r = byq[q]
        r["name"] = english_name(r["name"], d)
        for k in ("description", "birth", "death", "birthplace", "citizenship", "image", "wikipedia",
                  "employers", "fields", "educated"):
            if d.get(k):
                r[k] = d[k]
        r["known_for"] = d["known_for"]
        na = sorted(d["named_after"], key=lambda x: (not x["wiki"], x["label"] or ""))
        r["named_after_total"] = len(na)  # STEM topics only
        r["named_after"] = na[:40]

    todo = [r for r in recs.values() if r.get("wikipedia")]
    titles = {r["id"]: wikipedia.title_from_url(r["wikipedia"]) for r in todo}
    tl = sorted(set(titles.values()))  # stable batches -> cache hits across runs
    log("fetching Wikipedia data for %d articles (batched)" % len(tl))
    th = wikipedia.thumbnails(tl)
    kf = wikipedia.known_for(tl)
    for r in todo:
        t = titles[r["id"]]
        if th.get(t):
            r["thumbnail"] = th[t]
        have = {k["label"].lower() for k in r.get("known_for", []) if k.get("label")}
        for k in (kf.get(t) or []):
            if k["label"].lower() not in have and not re.match(r"(?i)^(full list|list of|see list|more)\b", k["label"]):
                r.setdefault("known_for", []).append(k)


def _topic_key(label, url=None):
    t = label or ""
    if url and "/wiki/" in url:
        import urllib.parse
        t = urllib.parse.unquote(url.rsplit("/wiki/", 1)[-1])
    t = re.sub(r"[_\s]+", " ", t.lower())
    t = re.sub(r"[\u2010-\u2015-]", "-", t)
    return re.sub(r"\s*\([^)]*\)$", "", t).strip()


def dedupe_known_for(recs):
    """Anything listed under "named after them" is removed from "known for"."""
    for r in recs.values():
        named = set()
        for x in r.get("named_after", []):
            named.add(_topic_key(x["label"], x.get("url")))
            named.add(_topic_key(x["label"]))
        if r.get("known_for"):
            r["known_for"] = [k for k in r["known_for"]
                              if _topic_key(k["label"], k.get("url")) not in named
                              and _topic_key(k["label"]) not in named]


def report_missing(recs, sub, anc):
    lines = []
    for g in sorted(anc):
        r = recs[g]
        if sub.get(g):
            continue
        born = (r.get("birth") or "")[:4]
        if born and born.isdigit() and int(born) < 1900:
            continue
        if r.get("degrees") and any((d.get("year") or 0) < 1920 for d in r["degrees"]):
            continue
        rel = (r.get("relation") or {}).get("label", "")
        at = ("https://academictree.org/physics/peopleinfo.php?pid=" + r["academictree"]) \
            if r.get("academictree") else "(search academictree.org for this name)"
        lines.append("%-35s %-28s %s" % (r["name"], rel, at))
    path = os.path.join(ROOT, "data", "missing_links.txt")
    with open(path, "w") as f:
        f.write("# Ancestors with no known advisor (modern era). Save their academictree page into\n"
                "# data/academictree_saved/ and rerun `python3 -m crawler.build`.\n")
        f.write("\n".join(lines) + "\n")
    log("missing-links report: %d people -> %s" % (len(lines), os.path.relpath(path, ROOT)))


# Fields needed to lay out and label the tree; everything else is only shown
# in hover cards and goes to details.json, which the page loads after the
# first draw.
CORE_FIELDS = {"id", "name", "birth", "death", "prizes", "qb", "qb_mentions", "qb_canon",
               "ancestor", "notable", "relation", "relation_phd"}


def write_output(out):
    core, details = [], {}
    for n in out["nodes"]:
        c = {k: v for k, v in n.items() if k in CORE_FIELDS}
        if not n.get("birth") and not n.get("death"):
            yrs = [d.get("year") for d in n.get("degrees", []) if d.get("year")]
            if yrs:
                c["deg_year"] = yrs[0]
        core.append(c)
        rest = {k: v for k, v in n.items() if k not in CORE_FIELDS and k != "id"}
        if rest:
            details[n["id"]] = rest
    d = os.path.join(ROOT, "web", "data")
    with open(os.path.join(d, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(dict(out, nodes=core), f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(d, "details.json"), "w", encoding="utf-8") as f:
        json.dump({"generated": out["generated"], "details": details}, f, ensure_ascii=False, separators=(",", ":"))


def sanity(out):
    ids = [n["id"] for n in out["nodes"]]
    assert len(ids) == len(set(ids)), "duplicate node ids"
    for key in ("qid", "mgp", "inspire"):
        vals = [n[key] for n in out["nodes"] if n.get(key)]
        dup = {v for v in vals if vals.count(v) > 1}
        if dup:
            log("WARNING duplicate %s across nodes: %s" % (key, sorted(dup)[:10]))
    noderel = sum(1 for n in out["nodes"] if n["id"] != "me" and not n.get("relation"))
    if noderel:
        log("WARNING %d nodes have no relation to me" % noderel)


if __name__ == "__main__":
    main()

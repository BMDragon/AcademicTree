/* Academic Tree viewer: d3-dag Sugiyama layout with sifting crossing reduction (me at the bottom), d3 pan/zoom, hover cards. */
(async function () {
  "use strict";
  const ICON = 15, ICON_GAP = 2, PADX = 10, NODE_H = 30;
  const FIELD_COLOR = {
    Physics: "var(--f-physics)", Chemistry: "var(--f-chemistry)", Medicine: "var(--f-medicine)",
    Mathematics: "var(--f-mathematics)", Computing: "var(--f-computing)",
  };
  const PRIZE_NAME = { nobel: "Nobel", fields: "Fields", turing: "Turing", wolf: "Wolf" };

  const data = await fetch("data/graph.json").then(r => r.json());
  const byId = new Map(data.nodes.map(n => [n.id, n]));
  const parents = new Map(), children = new Map();
  for (const e of data.edges) {
    // e.source = advisor, e.target = student
    if (!parents.has(e.target)) parents.set(e.target, []);
    parents.get(e.target).push(e);
    if (!children.has(e.source)) children.set(e.source, []);
    children.get(e.source).push(e);
  }

  document.getElementById("stats").textContent =
    `${data.stats.nodes} people · ${data.stats.edges} links · Nobel ${data.stats.laureates.nobel} · ` +
    `Fields ${data.stats.laureates.fields} · Turing ${data.stats.laureates.turing} · ` +
    `Wolf ${data.stats.laureates.wolf} · QB ${data.stats.quizbowl} · built ${data.generated}`;

  // ---------- measure + layout --------------------------------------------
  const measurer = document.createElement("canvas").getContext("2d");
  measurer.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif";
  function badges(n) {
    const b = n.prizes.map(p => ({ key: p.key, field: p.field, title: `${p.label}${p.year ? " " + p.year : ""}` }));
    if (n.qb_canon) b.push({ key: "qb", title: `Quizbowl canon: ${qbText(n)}` });
    return b;
  }
  function qbText(n) {
    const parts = [];
    if (n.qb) parts.push(`${n.qb} science answerline${n.qb === 1 ? "" : "s"}`);
    if (n.qb_mentions) parts.push(`named in ${n.qb_mentions} science question${n.qb_mentions === 1 ? "" : "s"}`);
    return parts.join(" · ");
  }
  function years(n) {
    const b = (n.birth || "").slice(0, 4), d = (n.death || "").slice(0, 4);
    if (!b && !d) {
      const deg = (n.degrees || []).find(x => x.year);
      return deg ? `PhD ${deg.year}` : "";
    }
    return `${b || "?"}–${d}`;
  }
  for (const n of data.nodes) {
    n._badges = badges(n);
    n._years = years(n);
    const textW = Math.max(measurer.measureText(n.name).width, measurer.measureText(n._years).width * 0.85);
    const iconsW = n._badges.length ? n._badges.length * (ICON + ICON_GAP) + 4 : 0;
    n._w = Math.ceil(textW + iconsW + PADX * 2);
    n._h = n._years ? NODE_H + 6 : NODE_H;
  }

  // ---------- views -------------------------------------------------------
  // A view is a set of node ids; each is laid out once and cached.
  function upClosure(id, phdOnly) {
    const seen = new Set([id]), st = [id];
    while (st.length) for (const e of parents.get(st.pop()) || []) {
      if (phdOnly && e.type !== "phd") continue;
      if (!seen.has(e.source)) { seen.add(e.source); st.push(e.source); }
    }
    return seen;
  }
  function connectionIds(id) {
    // Everyone on an upward path from X or from me to a *lowest* common ancestor.
    const n = byId.get(id), rel = n && n[relKey];
    const phd = relKey === "relation_phd" && rel && !rel.fallback;
    const ux = upClosure(id, phd), um = upClosure("me", phd);
    const common = new Set([...ux].filter(x => um.has(x)));
    const higher = new Set();
    for (const c of common) for (const e of parents.get(c) || []) if (common.has(e.source)) higher.add(e.source);
    const lca = [...common].filter(c => !higher.has(c));
    const keep = new Set();
    // nodes x with  x in up(X)∪up(me)  and some lca in up(x)
    for (const start of [ux, um]) for (const x of start) {
      if (lca.some(l => l === x || upClosure(x, phd).has(l))) keep.add(x);
    }
    keep.add(id); keep.add("me");
    return keep;
  }
  const VIEWS = {
    all: { label: "Everything", ids: () => new Set(data.nodes.map(n => n.id)) },
    lineage: { label: "My ancestors only", ids: () => new Set(data.nodes.filter(n => n.ancestor || n.id === "me").map(n => n.id)) },
  };
  const layouts = new Map();
  // Sifting crossing minimisation (custom d3-dag "decross" operator).
  // Starts from median + greedy-switch two-layer sweeps, then repeatedly moves
  // each node (highest degree first) to the position in its layer that
  // minimises crossings with both neighbouring layers, until no improvement.
  // On this data it removes ~17-33% of the crossings dagre leaves.
  function siftingDecross(D) {
    const init = D.decrossTwoLayer()
      .order(D.twolayerGreedy().base(D.twolayerAgg().aggregator(D.aggMedian))).passes(10);
    return function (layers) {
      init(layers);
      const pos = new Map(), up = new Map(), down = new Map();
      const reindex = L => L.forEach((n, i) => pos.set(n, i));
      for (const L of layers) { reindex(L); for (const n of L) { up.set(n, [...n.parents()]); down.set(n, [...n.children()]); } }
      const cross = (nu, nv) => { let c = 0; for (const a of nu) { const pa = pos.get(a); for (const b of nv) if (pa > pos.get(b)) c++; } return c; };
      const cuv = (u, v) => cross(up.get(u), up.get(v)) + cross(down.get(u), down.get(v));
      const total = () => { let c = 0; for (const L of layers) for (let i = 0; i < L.length; i++) for (let j = i + 1; j < L.length; j++) c += cross(down.get(L[i]), down.get(L[j])); return c; };
      let best = total();
      for (let round = 0; round < 20; round++) {
        const order = round % 2 ? [...layers.keys()].reverse() : [...layers.keys()];
        for (const li of order) {
          const L = layers[li];
          if (L.length < 3) continue;
          const byDeg = [...L].sort((a, b) => (up.get(b).length + down.get(b).length) - (up.get(a).length + down.get(a).length));
          for (const v of byDeg) {
            const rest = L.filter(x => x !== v), curPos = L.indexOf(v);
            let cur = 0, bestDelta = 0, bestPos = 0, curDelta = 0;
            for (let i = 0; i < rest.length; i++) {
              cur += cuv(rest[i], v) - cuv(v, rest[i]);
              if (i + 1 === curPos) curDelta = cur;
              if (cur < bestDelta) { bestDelta = cur; bestPos = i + 1; }
            }
            if (bestDelta < curDelta) {
              rest.splice(bestPos, 0, v);
              for (let i = 0; i < L.length; i++) L[i] = rest[i];
              reindex(L);
            }
          }
        }
        const t = total();
        if (t >= best) break;
        best = t;
      }
    };
  }

  function layout(key, ids) {
    if (layouts.has(key)) return layouts.get(key);
    const D = window.d3;  // d3-dag merges into the d3 global
    const M = 40;         // margin
    const edgeOf = new Map();
    const links = [];
    for (const e of data.edges) if (ids.has(e.source) && ids.has(e.target)) {
      links.push([e.source, e.target]);            // advisor above student
      edgeOf.set(e.source + ">" + e.target, e);
    }
    const graph = D.graphConnect()(links);
    const sugi = D.sugiyama()
      .nodeSize(nd => { const n = byId.get(nd.data); return [n._w, n._h]; })
      .gap([20, 46])
      .layering(D.layeringSimplex())
      .decross(siftingDecross(D))
      .coord(D.coordGreedy());
    const { width, height } = sugi(graph);
    const pos = new Map(), eds = [];
    for (const nd of graph.nodes()) {
      const n = byId.get(nd.data);
      pos.set(nd.data, { x: nd.x + M, y: nd.y + M, width: n._w, height: n._h });
    }
    // Route each line so it only bends in the empty band between rows: it
    // leaves the advisor's box at the bottom, passes every intermediate row
    // vertically (beside the boxes there, never behind them) and enters the
    // student's box at the top.
    const HALF = 20;  // half the tallest box + 2px
    for (const l of graph.links()) {
      const e = edgeOf.get(l.source.data + ">" + l.target.data);
      const raw = l.points.map(([x, y]) => ({ x: x + M, y: y + M }));
      const pts = [{ x: raw[0].x, y: raw[0].y + HALF }];
      for (let i = 1; i < raw.length - 1; i++) pts.push({ x: raw[i].x, y: raw[i].y - HALF }, { x: raw[i].x, y: raw[i].y + HALF });
      const last = raw[raw.length - 1];
      pts.push({ x: last.x, y: last.y - HALF });
      eds.push({ e, points: pts });
    }
    // Put "me" alone on a row below everyone, centred under my advisors
    // (otherwise childless notables can sit level with or below me).
    let maxY = -Infinity;
    for (const [id, p] of pos) if (id !== "me") maxY = Math.max(maxY, p.y + p.height / 2);
    const me = pos.get("me");
    const mine = eds.filter(d => d.e.target === "me");
    if (mine.length) me.x = mine.reduce((s, d) => s + pos.get(d.e.source).x, 0) / mine.length;
    me.y = maxY + 90;
    for (const d of mine) {
      const a = pos.get(d.e.source);
      d.points = [{ x: a.x, y: a.y + a.height / 2 }, { x: a.x, y: maxY + 20 },
                  { x: me.x, y: me.y - 60 }, { x: me.x, y: me.y - me.height / 2 }];
    }
    const G = { width: width + 2 * M, height: Math.max(height + 2 * M, me.y + 60) };
    // dagre-like adapter consumed by draw()
    const out = {
      graph: () => G, nodes: () => [...pos.keys()], node: id => pos.get(id),
      edges: () => eds, edge: d => d,
    };
    layouts.set(key, out);
    return out;
  }


  // ---------- draw ----------------------------------------------------------
  const svg = d3.select("#canvas"), vp = d3.select("#viewport");
  // monotone in y: passes exactly through the routing points (no overshoot into boxes)
  const line = d3.line().x(p => p.x).y(p => p.y).curve(d3.curveMonotoneY);
  let edgeSel = d3.select("#edges").selectAll("path"), nodeSel = d3.select("#nodes").selectAll("g.node");
  let G = null, currentView = "all", visible = new Set();

  function draw(g) {
    G = g.graph();
    visible = new Set(g.nodes());
    const eds = g.edges().map(ed => ({ e: g.edge(ed).e, pts: g.edge(ed).points }));
    edgeSel = d3.select("#edges").selectAll("path").data(eds, d => d.e.source + ">" + d.e.target)
      .join(enter => {
        const p = enter.append("path").attr("class", d => `edge ${d.e.type}`);
        p.append("title").text(d => `${byId.get(d.e.source).name} → ${byId.get(d.e.target).name} (${d.e.type}; ${d.e.sources.join(", ")})`);
        return p;
      })
      .attr("d", d => line(d.pts));
    const ns = g.nodes().map(id => byId.get(id));
    nodeSel = d3.select("#nodes").selectAll("g.node").data(ns, n => n.id)
      .join(enter => {
        const gN = enter.append("g")
          .attr("class", n => ["node", n.id === "me" ? "me" : "", n.ancestor ? "ancestor" : "", n.notable ? "notable" : ""].join(" "));
        gN.append("rect").attr("width", n => n._w).attr("height", n => n._h).attr("rx", 6);
        gN.append("text").attr("x", PADX).attr("y", n => n._years ? 11 : n._h / 2).text(n => n.name);
        gN.filter(n => n._years).append("text").attr("class", "sub").attr("x", PADX).attr("y", 25).text(n => n._years);
        gN.each(function (n) {
          const el = d3.select(this);
          n._badges.forEach((b, i) => {
            const x = n._w - PADX - (n._badges.length - i) * (ICON + ICON_GAP) + ICON_GAP;
            const bg = el.append("g").attr("transform", `translate(${x},${(n._h - ICON) / 2})`);
            if (b.field && b.key !== "fields" && b.key !== "turing") {
              bg.append("circle").attr("class", "award-ring").attr("cx", ICON / 2).attr("cy", ICON / 2 + 2)
                .attr("r", ICON / 2 - 0.5).style("stroke", FIELD_COLOR[b.field]);
            }
            bg.append("image").attr("href", `img/awards/${b.key}.svg`).attr("width", ICON).attr("height", ICON);
            bg.append("title").text(b.title);
          });
        });
        gN.on("mouseenter", (ev, n) => { pinned = false; show(n, ev); })
          .on("mouseleave", scheduleHide)
          .on("click", (ev, n) => { pinned = true; show(n, ev); ev.stopPropagation(); });
        return gN;
      })
      .attr("transform", n => { const p = g.node(n.id); n._x = p.x; n._y = p.y; return `translate(${p.x - n._w / 2},${p.y - n._h / 2})`; });
  }

  const viewSel = document.getElementById("view");
  function setView(key, ids, label) {
    if (key.startsWith("conn:")) {
      let opt = viewSel.querySelector('option[data-conn]');
      if (!opt) { opt = document.createElement("option"); opt.dataset.conn = "1"; viewSel.appendChild(opt); }
      opt.value = key; opt.textContent = label;
    }
    viewSel.value = key;
    currentView = key;
    document.body.classList.add("busy");
    setTimeout(() => {
      draw(layout(key, ids));
      document.body.classList.remove("busy");
      unhighlight();
      if (key === "all") frameFamily(3); else fit(false);
    }, 20);
  }
  viewSel.onchange = () => {
    const k = viewSel.value;
    if (VIEWS[k]) setView(k, VIEWS[k].ids());
    else if (k.startsWith("conn:")) showConnection(k.slice(5));
  };
  function showConnection(id) {
    card.hidden = true; pinned = false;
    setView("conn:" + id + ":" + relKey, connectionIds(id), "Connection: " + byId.get(id).name);
  }

  // ---------- zoom ----------------------------------------------------------
  const zoom = d3.zoom().scaleExtent([0.03, 3]).on("zoom", ev => vp.attr("transform", ev.transform));
  svg.call(zoom).on("dblclick.zoom", null);
  function fit(animate = true) {
    const W = svg.node().clientWidth, H = svg.node().clientHeight - 50;
    const k = Math.min(W / G.width, H / G.height, 1.2);
    const t = d3.zoomIdentity.translate((W - G.width * k) / 2, 50 + (H - G.height * k) / 2).scale(k);
    (animate ? svg.transition().duration(500) : svg).call(zoom.transform, t);
  }
  function focusNode(id, k = 1) {
    const n = byId.get(id); if (!n) return;
    const W = svg.node().clientWidth, H = svg.node().clientHeight;
    svg.transition().duration(600).call(zoom.transform,
      d3.zoomIdentity.translate(W / 2 - n._x * k, H / 2 - n._y * k).scale(k));
    const sel = nodeSel.filter(d => d.id === id).classed("pulse", false);
    if (sel.node()) { void sel.node().getBBox(); sel.classed("pulse", true); }
  }
  // Frame me plus my ancestors up to `gens` generations (great-grandparents by default).
  function frameFamily(gens) {
    const fam = data.nodes.filter(n => visible.has(n.id) && (n.id === "me" || (n.relation && n.relation.n === 0 && n.relation.m <= gens)));
    const xs = fam.flatMap(n => [n._x - n._w / 2, n._x + n._w / 2]), ys = fam.flatMap(n => [n._y - n._h / 2, n._y + n._h / 2]);
    const x0 = Math.min(...xs) - 40, x1 = Math.max(...xs) + 40, y0 = Math.min(...ys) - 40, y1 = Math.max(...ys) + 40;
    const W = svg.node().clientWidth, H = svg.node().clientHeight - 50;
    const k = Math.max(0.12, Math.min(1, W / (x1 - x0), H / (y1 - y0)));
    svg.call(zoom.transform, d3.zoomIdentity.translate(W / 2 - k * (x0 + x1) / 2, 50 + H / 2 - k * (y0 + y1) / 2).scale(k));
  }
  document.getElementById("fit").onclick = () => fit();
  document.getElementById("home").onclick = () => {
    if (currentView === "all") frameFamily(3); else focusNode("me", 1);
  };

  // ---------- search --------------------------------------------------------
  const dl = document.getElementById("names");
  const byName = new Map();
  for (const n of [...data.nodes].sort((a, b) => a.name.localeCompare(b.name))) {
    const label = n._years ? `${n.name} (${n._years})` : n.name;
    byName.set(label, n.id); byName.set(n.name, byName.get(n.name) || n.id);
    const o = document.createElement("option"); o.value = label; dl.appendChild(o);
  }
  document.getElementById("search").addEventListener("change", ev => {
    const id = byName.get(ev.target.value);
    if (!id) return;
    if (!visible.has(id)) { setView("all", VIEWS.all.ids()); setTimeout(() => focusNode(id, 1), 400); }
    else focusNode(id, 1);
  });

  // ---------- relation mode -------------------------------------------------
  const relSel = document.getElementById("relmode");
  let relKey = "relation";
  try { relKey = localStorage.getItem("relmode") || "relation"; } catch (e) { /* storage blocked */ }
  relSel.value = relKey;
  relSel.onchange = () => { relKey = relSel.value; try { localStorage.setItem("relmode", relKey); } catch (e) { } };

  // ---------- path highlight ------------------------------------------------
  function upPath(from, to, phdOnly) {
    // BFS from `from` upward until `to`; returns list of edges
    const prev = new Map([[from, null]]), q = [from];
    while (q.length) {
      const x = q.shift();
      if (x === to) break;
      for (const e of parents.get(x) || []) {
        if (phdOnly && e.type !== "phd") continue;
        if (!prev.has(e.source)) { prev.set(e.source, e); q.push(e.source); }
      }
    }
    if (!prev.has(to)) return null;
    const out = []; let cur = to;
    while (prev.get(cur)) { const e = prev.get(cur); out.push(e); cur = e.target; }
    return out;
  }
  function highlight(n) {
    const rel = n[relKey];
    const es = new Set(), ns = new Set([n.id, "me"]);
    if (rel && rel.via) {
      const phd = relKey === "relation_phd" && !rel.fallback;
      for (const path of [upPath(n.id, rel.via, phd), upPath("me", rel.via, phd)]) {
        for (const e of path || []) { es.add(e); ns.add(e.source); ns.add(e.target); }
      }
    }
    svg.classed("focus", true);
    edgeSel.classed("hl", d => es.has(d.e));
    nodeSel.classed("hl", d => ns.has(d.id));
  }
  function unhighlight() {
    svg.classed("focus", false);
    edgeSel.classed("hl", false);
    nodeSel.classed("hl", false);
  }

  // ---------- hover card ----------------------------------------------------
  const card = document.getElementById("card");
  let hideTimer = null, pinned = false;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const link = (url, label) => `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)}</a>`;
  function fmtDate(s) {
    if (!s) return "";
    const d = s.slice(0, 10);
    return d.endsWith("-01-01") ? d.slice(0, 4) : d;
  }
  function relationHTML(n) {
    if (n.id === "me") return `<div class="rel"><b>This is you.</b></div>`;
    const r = n[relKey];
    if (!r) return `<div class="rel">No computed relation.</div>`;
    let h = `<div class="rel">Your <b>academic ${esc(r.label)}</b>`;
    if (r.n > 0 && r.m > 0 && r.via_name) h += `<div class="alt">Common ancestor: ${esc(r.via_name)} (${r.m} gen. above you, ${r.n} above them)</div>`;
    if (r.fallback) h += `<div class="alt">No pure-PhD lineage connects you; relation uses other advising links.</div>`;
    if (r.alternates && r.alternates.length) {
      h += `<div class="alt">Also: ${r.alternates.map(a => `${esc(a.label)} via ${esc(a.via_name || "?")}`).join("; ")}</div>`;
    }
    return h + "</div>";
  }
  function list(title, items, cls = "") {
    if (!items || !items.length) return "";
    return `<h3>${title}</h3><ul class="${cls}">${items.join("")}</ul>`;
  }
  function chips(title, items, more) {
    if (!items || !items.length) return "";
    return `<h3>${title}</h3><div class="chips">${items.join("")}</div>${more ? `<div class="more">${more}</div>` : ""}`;
  }
  function cardHTML(n) {
    const photo = n.thumbnail || (n.image ? `https://commons.wikimedia.org/wiki/Special:FilePath/${encodeURIComponent(decodeURIComponent(n.image.split("/").pop()))}?width=160` : null);
    const life = [n.birth ? `b. ${fmtDate(n.birth)}${n.birthplace ? ", " + esc(n.birthplace) : ""}` : "",
                  n.death ? `d. ${fmtDate(n.death)}` : ""].filter(Boolean).join(" · ");
    let h = `<header>${photo ? `<img class="photo" src="${esc(photo)}" alt="">` : ""}<div>
      <h2>${esc(n.name)}</h2>
      ${life ? `<div class="life">${life}</div>` : ""}
      ${n.citizenship ? `<div class="life">${esc(n.citizenship)}</div>` : ""}
      ${n.description ? `<div class="desc">${esc(n.description)}</div>` : ""}
    </div></header>`;
    h += relationHTML(n);
    if (n.id !== "me") h += `<button type="button" class="connect" data-connect="${esc(n.id)}">Show only the connection to me</button>`;
    const aw = n.prizes.map(p => `<li><img src="img/awards/${p.key}.svg" alt="">${esc(p.label)}${p.year ? " (" + p.year + ")" : ""}</li>`);
    if (n.qb_canon) aw.push(`<li><img src="img/awards/qb.svg" alt="">Quizbowl canon: ${esc(qbText(n))}</li>`);
    h += list("Major prizes", aw, "awards");
    // Anything also in "Named after them" is shown only there.
    const keyOf = (label, url) => {
      let t = label || "";
      try { if (url && url.includes("/wiki/")) t = decodeURIComponent(url.split("/wiki/").pop()); } catch (e) { /* keep label */ }
      return t.toLowerCase().replace(/[_\s]+/g, " ").replace(/[\u2010-\u2015-]/g, "-").replace(/\s*\([^)]*\)$/, "").trim();
    };
    const named = new Set();
    for (const x of n.named_after || []) { named.add(keyOf(x.label, x.url)); named.add(keyOf(x.label)); }
    const kf = (n.known_for || []).filter(k => !named.has(keyOf(k.label, k.url)) && !named.has(keyOf(k.label)));
    h += chips("Known for", kf.slice(0, 18).map(k => link(k.url, k.label)));
    const na = n.named_after || [];
    h += chips("Named after them", na.map(x => x.wiki ? link(x.url, x.label) : `<span title="${esc(x.desc || "")}">${link(x.url, x.label)}</span>`),
      n.named_after_total > na.length ? `+${n.named_after_total - na.length} more on Wikidata` : "");
    const deg = (n.degrees || []).map(d => `<li>${esc(d.degree)}, ${esc(d.school)}${d.year ? " " + d.year : ""}</li>`);
    if (deg.length && n.thesis) deg.push(`<li><i class="tex">${esc(n.thesis)}</i></li>`);
    h += list("Degrees", deg);
    const adv = (parents.get(n.id) || []).map(e => `<li>${esc(byId.get(e.source).name)} <span class="more">(${e.type})</span></li>`);
    h += list("Advisors in this tree", adv);
    const stu = (children.get(n.id) || []).map(e => `<li>${esc(byId.get(e.target).name)} <span class="more">(${e.type})</span></li>`);
    h += list("Students in this tree", stu);
    if (n.employers && n.employers.length) h += chips("Institutions", n.employers.slice(0, 10).map(x => `<span>${esc(x)}</span>`));
    else if (n.positions && n.positions.length) h += chips("Institutions", [...new Set(n.positions.map(p => p.institution))].slice(0, 10).map(x => `<span>${esc(x)}</span>`));
    if (n.fields && n.fields.length) h += chips("Fields", n.fields.slice(0, 8).map(x => `<span>${esc(x)}</span>`));
    const src = [];
    if (n.wikipedia) src.push(link(n.wikipedia, "Wikipedia"));
    if (n.qid) src.push(link(`https://www.wikidata.org/wiki/${n.qid}`, "Wikidata"));
    if (n.mgp) src.push(link(`https://www.mathgenealogy.org/id.php?id=${n.mgp}`, "Math Genealogy"));
    if (n.inspire) src.push(link(`https://inspirehep.net/authors/${n.inspire}`, "INSPIRE"));
    if (n.academictree) src.push(link(`https://academictree.org/physics/peopleinfo.php?pid=${n.academictree}`, "Academic Tree"));
    if (src.length) h += `<div class="sources">${src.join("")}</div>`;
    return h;
  }
  function place(ev) {
    const W = window.innerWidth, H = window.innerHeight, cw = card.offsetWidth, ch = card.offsetHeight;
    let x = ev.clientX + 18, y = ev.clientY - 40;
    if (x + cw > W - 12) x = ev.clientX - cw - 18;
    if (x < 12) x = 12;
    if (y + ch > H - 12) y = H - ch - 12;
    if (y < 56) y = 56;
    card.style.left = x + "px"; card.style.top = y + "px";
  }
  function show(n, ev) {
    clearTimeout(hideTimer);
    card.innerHTML = cardHTML(n);
    // Thesis titles (Math Genealogy) carry inline LaTeX like $\mathbb{R}^3$.
    if (window.renderMathInElement) {
      for (const el of card.querySelectorAll(".tex")) renderMathInElement(el, {
        delimiters: [{ left: "$$", right: "$$", display: false }, { left: "$", right: "$", display: false },
                     { left: "\\(", right: "\\)", display: false }],
        throwOnError: false,
      });
    }
    card.hidden = false;
    place(ev);
    highlight(n);
  }
  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { if (!pinned) { card.hidden = true; unhighlight(); } }, 250);
  }
  card.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  card.addEventListener("mouseleave", scheduleHide);
  svg.on("click", () => { pinned = false; card.hidden = true; unhighlight(); });
  card.addEventListener("click", ev => {
    const b = ev.target.closest("[data-connect]");
    if (b) showConnection(b.dataset.connect);
  });
  document.addEventListener("keydown", ev => { if (ev.key === "Escape") { pinned = false; card.hidden = true; unhighlight(); } });

  // ---------- initial render ------------------------------------------------
  await new Promise(r => setTimeout(r, 30));
  draw(layout("all", VIEWS.all.ids()));
  document.getElementById("loading").remove();
  frameFamily(3);
})();

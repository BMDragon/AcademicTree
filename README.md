# AcademicTree

A local website showing my academic family tree: me at the bottom, then my
advisors and their academic ancestors, branching out to every Nobel (Physics,
Chemistry, Medicine), Fields, Turing and Wolf (Physics, Chemistry, Medicine,
Mathematics) laureate and quizbowl-canonical scientist whose advisor lineage
joins mine.

## Use

```bash
python3 -m crawler.build     # crawl + build web/data/graph.json (HTTP is cached in data/cache/)
./serve.sh                   # http://localhost:8000 (forward port 8000 in VS Code)
python3 -m unittest discover tests
```

Hover a name for bio, prizes, "known for", things named after them and your
kinship relation (e.g. "3× great-grandparent", "4th cousin twice removed").
Click to pin the card. The card's **Show only the connection to me** button
redraws just the paths between that person and you. The toolbar's *View* menu
switches between everything, your ancestors only, and the current connection;
*Relation via* switches kinship between *all advising links* and *PhD lineage
first* (falls back to all links when no pure-PhD path exists).

Wikidata "student of" links are ignored for people born before 1400
(`student_of_min_birth_year`): before then they mostly encode chains of
religious transmission rather than academic advising.

Edges: PhD solid · undergrad dotted · postdoc dashed · research/other dash-dot.

## Data sources

| Source | What | Edge type |
|---|---|---|
| Wikidata | doctoral advisor/student (P184/P185), student of (P1066/P802), prizes, bios, named-after (P138), ID crosswalk | phd / research |
| INSPIRE-HEP | author advisors with degree type | phd / undergrad (bachelor) / research (master, other) |
| Math Genealogy Project | doctoral advisors | phd |
| academictree.org | pages **you save** into `data/academictree_saved/` | typed (grad student, post-doc, research assistant, undergrad) |
| QB Reader | science answerline frequency (≥ `quizbowl.min_count`) | – |
| Wikipedia | summary, photo, infobox "known for" | – |

academictree.org is behind a Cloudflare check, so it can't be crawled. After
each build, `data/missing_links.txt` lists modern-era ancestors with no known
advisor. Open their academictree page in your browser, save it (Ctrl+S, HTML
only) into `data/academictree_saved/`, and rebuild. Saved pages are parsed for
Parents/Children with relationship types.

Each person is one node: identities are merged across sources through Wikidata
ID crosswalks (MGP P549, INSPIRE BAI P2930, ORCID P496, Academic Tree P2381)
and by name among co-advisors of the same student.

Seeds, prize list, QB threshold and rate limits live in `config.json`.

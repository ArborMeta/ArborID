"""Build review.html from results.json: photos grouped by species and predicted category,
with a dropdown under each photo to record the correct category."""
import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABELS = [("flower", "Flower"), ("fruit_seed", "Fruit / seed"), ("leaf", "Leaf"), ("bark", "Bark"),
          ("whole_tree", "Whole tree"), ("mixed_unclear", "Mixed / unclear"), ("other", "Other (specimen sheet, label…)")]
NAME = dict(LABELS)

data = json.loads((HERE / "results.json").read_text(encoding="utf-8"))
species, photos = data["species"], data["photos"]
by_sp = {}
for p in photos:
    by_sp.setdefault(p["sci"], []).append(p)

totals = {k: sum(1 for p in photos if p["label"] == k) for k, _ in LABELS}
e = html.escape

parts = []
for sp in species:
    ph = by_sp.get(sp["sci"], [])
    if not ph:
        continue
    counts = " · ".join(f"{NAME[k]} {sum(1 for p in ph if p['label'] == k)}" for k, _ in LABELS
                        if any(p["label"] == k for p in ph))
    groups = []
    for k, title in LABELS:
        items = [p for p in ph if p["label"] == k]
        if not items:
            continue
        cards = []
        for p in sorted(items, key=lambda p: -p["scores"].get(k, 0)):
            conf = p["scores"].get(k) if k in p["scores"] else max(p["scores"].values())
            opts = "".join(f'<option value="{v}"{" selected" if v == k else ""}>{e(t)}</option>' for v, t in LABELS)
            cards.append(f'''<figure class="card" data-id="{e(p["id"])}" data-pred="{k}" data-sci="{e(p["sci"])}">
  <a href="{e(p["large"])}" target="_blank" title="Open larger image (needs internet)"><img src="{e(p["file"])}" loading="lazy" alt=""></a>
  <figcaption><span class="conf">{conf:.0%}</span> <span class="credit">{e(p["credit"])}</span></figcaption>
  <select aria-label="Correct category">{opts}</select>
</figure>''')
        groups.append(f'<div class="group" data-label="{k}"><h4>{e(title)} <small>({len(items)})</small></h4><div class="grid">{"".join(cards)}</div></div>')
    parts.append(f'''<section class="species" id="{e(sp["sci"].replace(" ", "_"))}">
  <h3><i>{e(sp["sci"])}</i> <span>{e(sp["common"])}</span> <small>{e(sp["family"])} · {sp["photos_on_ala"]:,} native-range photos on ALA</small></h3>
  <p class="counts">{counts}</p>{"".join(groups)}</section>''')

summary = "".join(f'<button class="chip" data-filter="{k}">{e(t)} <b>{totals[k]}</b></button>' for k, t in LABELS if totals[k])
toc = " ".join(f'<a href="#{e(s["sci"].replace(" ", "_"))}"><i>{e(s["sci"])}</i></a>' for s in species if s["sci"] in by_sp)

page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Photo sorting trial – AusTree Atlas</title>
<style>
:root {{ --bg:#0f172a; --panel:#111c33; --text:#e2e8f0; --muted:#94a3b8; --accent:#79a565; --warn:#f59e0b; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui, Segoe UI, sans-serif; }}
header {{ position:sticky; top:0; z-index:5; background:#0b1222ee; backdrop-filter:blur(6px); padding:12px 20px; border-bottom:1px solid #1e293b; }}
h1 {{ font-size:18px; margin:0 0 4px }} h1 small {{ color:var(--muted); font-weight:400 }}
.bar {{ display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:6px }}
.chip {{ background:#1e293b; color:var(--text); border:1px solid #334155; border-radius:999px; padding:3px 10px; cursor:pointer; font-size:12px }}
.chip.on {{ background:var(--accent); border-color:var(--accent); color:#0b1222 }}
#status {{ margin-left:auto; color:var(--muted); font-size:12px }}
#export {{ background:var(--warn); color:#111; border:0; border-radius:6px; padding:5px 10px; font-weight:600; cursor:pointer }}
main {{ padding:16px 20px 60px; max-width:1500px; margin:0 auto }}
.intro {{ color:var(--muted); max-width:900px }}
.toc {{ font-size:12px; color:var(--muted); line-height:1.9 }} .toc a {{ color:#9ec18e; margin-right:8px }}
.species {{ background:var(--panel); border:1px solid #1e293b; border-radius:12px; padding:14px; margin:18px 0 }}
.species h3 {{ margin:0; font-size:16px }} .species h3 span {{ font-weight:400 }} .species h3 small {{ color:var(--muted); font-weight:400; margin-left:6px }}
.counts {{ color:var(--muted); font-size:12px; margin:4px 0 8px }}
.group h4 {{ margin:10px 0 6px; font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:#c2d9b6 }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:8px }}
.card {{ margin:0; background:#0b1222; border:2px solid transparent; border-radius:8px; overflow:hidden }}
.card.changed {{ border-color:var(--warn) }}
.card img {{ width:100%; aspect-ratio:1; object-fit:cover; display:block }}
figcaption {{ font-size:10px; color:var(--muted); padding:3px 5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis }}
.conf {{ color:var(--text); font-weight:600 }}
select {{ width:100%; background:#1e293b; color:var(--text); border:0; border-top:1px solid #334155; padding:4px; font-size:12px }}
.hidden {{ display:none !important }}
</style></head><body>
<header>
  <h1>Photo sorting trial <small>— {len(by_sp)} species · {len(photos):,} ALA photos · CLIP ViT-H/14-378 (DFN-5B) on RTX 4090 · zero-shot</small></h1>
  <div class="bar">{summary}<button class="chip on" data-filter="">Show all</button>
    <span id="status"></span><button id="export">Save corrections (CSV)</button></div>
</header>
<main>
  <p class="intro">Each photo shows the model's category and confidence. <b>If a photo is in the wrong group, pick the right category in the dropdown under it</b>; it turns orange. Your choices are kept in this browser if you close the page. When you're done, click <b>Save corrections</b> and send me the CSV, or just tell me what you noticed. Click a photo to open a larger version (needs internet).</p>
  <p class="toc">{toc}</p>
  {"".join(parts)}
</main>
<script>
const KEY = 'photo-sort-trial-corrections';
let saved = {{}};
try {{ saved = JSON.parse(localStorage.getItem(KEY) || '{{}}'); }} catch (e) {{}}
const cards = [...document.querySelectorAll('.card')];
function refresh() {{
  const changed = cards.filter(c => c.querySelector('select').value !== c.dataset.pred).length;
  const reviewedNote = changed ? `${{changed}} corrected · model right on the rest = ${{(100 * (cards.length - changed) / cards.length).toFixed(0)}}% if you checked every photo` : 'No corrections yet';
  document.getElementById('status').textContent = reviewedNote;
}}
cards.forEach(c => {{
  const sel = c.querySelector('select');
  if (saved[c.dataset.id]) sel.value = saved[c.dataset.id];
  c.classList.toggle('changed', sel.value !== c.dataset.pred);
  sel.addEventListener('change', () => {{
    c.classList.toggle('changed', sel.value !== c.dataset.pred);
    if (sel.value !== c.dataset.pred) saved[c.dataset.id] = sel.value; else delete saved[c.dataset.id];
    try {{ localStorage.setItem(KEY, JSON.stringify(saved)); }} catch (e) {{}}
    refresh();
  }});
}});
refresh();
document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => {{
  const f = b.dataset.filter;
  document.querySelectorAll('[data-filter]').forEach(x => x.classList.toggle('on', x === b));
  document.querySelectorAll('.group').forEach(g => g.classList.toggle('hidden', !!f && g.dataset.label !== f));
  document.querySelectorAll('.species').forEach(s => s.classList.toggle('hidden', !!f && !s.querySelector(`.group[data-label="${{f}}"]`)));
}}));
document.getElementById('export').addEventListener('click', () => {{
  const rows = [['image_id', 'species', 'predicted', 'corrected']];
  cards.forEach(c => {{ const v = c.querySelector('select').value; if (v !== c.dataset.pred) rows.push([c.dataset.id, c.dataset.sci, c.dataset.pred, v]); }});
  const blob = new Blob([rows.map(r => r.join(',')).join('\\n')], {{ type: 'text/csv' }});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'photo-sort-corrections.csv'; a.click();
}});
</script></body></html>'''

(HERE / "review.html").write_text(page, encoding="utf-8")
print("wrote review.html")

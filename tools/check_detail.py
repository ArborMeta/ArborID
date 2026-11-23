"""Open the species detail view for a few species and report what each section loaded."""
import json
import time
from pathlib import Path
import webview

root = Path(__file__).resolve().parent.parent
SPECIES = ["Eucalyptus pauciflora", "Ficus macrophylla", "Banksia acanthopoda"]

REPORT = """JSON.stringify({
  author: document.getElementById('detail-author').textContent,
  badges: [...document.querySelectorAll('#detail-badges > *')].map(b => b.textContent.trim()),
  names: document.querySelectorAll('#detail-names span').length,
  wiki: document.getElementById('detail-wiki').textContent.trim().slice(0, 90),
  mapCount: document.getElementById('detail-map-count').textContent,
  tilesLoaded: [...document.querySelectorAll('#detail-map img.leaflet-tile')].filter(i => i.complete && i.naturalWidth > 0).length,
  wmsTiles: [...document.querySelectorAll('#detail-map img.leaflet-tile')].filter(i => i.src.includes('wms') && i.naturalWidth > 0).length,
  states: [...document.querySelectorAll('#detail-states .font-bold')].map(x => x.textContent).join(' '),
  monthBars: document.querySelectorAll('#detail-months [title]').length,
  bark: document.querySelectorAll('#detail-bark img').length || document.getElementById('detail-bark').textContent.trim().slice(0, 60),
  barkTitles: [...document.querySelectorAll('#detail-bark button')].map(b => b.title).slice(0, 3),
  gallery: document.querySelectorAll('#detail-gallery img').length,
  galleryLoaded: [...document.querySelectorAll('#detail-gallery img')].filter(i => i.complete && i.naturalWidth > 0).length,
  taxonomy: document.getElementById('detail-taxonomy').textContent.replace(/\\s+/g, ' ').trim().slice(0, 140)
})"""


def run(w):
    try:
        time.sleep(4)
        for sci in SPECIES:
            w.evaluate_js(f"openSpeciesDetail({json.dumps(sci)})")
            time.sleep(10)
            print(sci, json.dumps(json.loads(w.evaluate_js(REPORT)), indent=1, ensure_ascii=False), flush=True)
        w.evaluate_js("document.querySelector('#detail-gallery button')?.click()")
        time.sleep(3)
        print("lightbox:", w.evaluate_js("document.getElementById('lightbox-attr').textContent + ' | w=' + document.getElementById('lightbox-img').naturalWidth"), flush=True)
        w.evaluate_js("closeLightbox(); closeSpeciesDetail();")
        print("closed:", w.evaluate_js("document.getElementById('detail-modal').classList.contains('hidden')"), flush=True)
    except Exception as e:
        print("ERROR", e, flush=True)
    finally:
        w.destroy()


w = webview.create_window("check", url=(root / "app" / "index.html").as_uri(), width=1400, height=950)
webview.start(run, w)

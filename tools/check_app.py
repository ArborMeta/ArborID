"""Smoke-test the app in a real WebView window: data, search, filters, photos."""
import time
from pathlib import Path
import webview

root = Path(__file__).resolve().parent.parent


def js(w, code):
    try:
        return w.evaluate_js(code)
    except Exception as e:
        return f"JS ERROR: {e}"


def run(w):
    try:
        time.sleep(4)
        print(js(w, """JSON.stringify({total:ALL_SPECIES.length, shown:document.getElementById('species-count-badge').textContent,
          families:document.getElementById('filter-family').options.length-1, genera:document.getElementById('filter-genus').options.length-1,
          page1Imgs:document.querySelectorAll('#species-grid img').length,
          page1Loaded:[...document.querySelectorAll('#species-grid img')].filter(i=>i.complete&&i.naturalWidth>0).length})"""), flush=True)

        js(w, "document.getElementById('search-input').value='scribbly';handleSearchInput();")
        time.sleep(1)
        print("search 'scribbly':", js(w, "[...document.querySelectorAll('#species-grid h3')].map(h=>h.textContent.trim()).join(', ')"), flush=True)

        js(w, "resetTaxonomicKey();document.getElementById('filter-state').value='TAS';document.getElementById('filter-genus').value='Eucalyptus';applyFilters();")
        time.sleep(1)
        print("TAS eucalypts:", js(w, "document.getElementById('species-count-badge').textContent"), flush=True)

        js(w, "resetTaxonomicKey();document.getElementById('filter-genus').value='Banksia';applyFilters();")
        time.sleep(4)
        print("Banksia page:", js(w, """JSON.stringify({count:document.getElementById('species-count-badge').textContent,
          imgs:document.querySelectorAll('#species-grid img').length,
          loaded:[...document.querySelectorAll('#species-grid img')].filter(i=>i.complete&&i.naturalWidth>0).length,
          plates:document.querySelectorAll('#species-grid svg').length})"""), flush=True)

        js(w, "const im=[...document.querySelectorAll('#species-grid img')].find(i=>i.naturalWidth>0 && i.src.includes('/ala/')); if(im) im.click();")
        time.sleep(4)
        print("lightbox:", js(w, "document.getElementById('lightbox-title').textContent+' | '+document.getElementById('lightbox-attr').textContent+' | width='+document.getElementById('lightbox-img').naturalWidth"), flush=True)
        js(w, "closeLightbox()")

        js(w, "resetTaxonomicKey();document.getElementById('page-size-select').value='9999';changePageSize();")
        time.sleep(3)
        print("All view cards:", js(w, "document.querySelectorAll('#species-grid > div').length"), flush=True)
    finally:
        w.destroy()


w = webview.create_window("check", url=(root / "app" / "index.html").as_uri(), width=1400, height=900)
webview.start(run, w)

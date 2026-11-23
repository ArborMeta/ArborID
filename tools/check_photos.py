import time, json
from pathlib import Path
import webview
root = Path(__file__).resolve().parent.parent
def run(w):
    time.sleep(3)
    js_count = """JSON.stringify({bundled:Object.keys(window.BUNDLED_PHOTOS||{}).length,
      loaded:[...document.querySelectorAll('#species-grid img')].filter(i=>i.complete&&i.naturalWidth>0).length,
      imgs:document.querySelectorAll('#species-grid img').length,
      plates:document.querySelectorAll('#species-grid svg').length})"""
    print("page1", w.evaluate_js(js_count))
    w.evaluate_js("document.getElementById('page-size-select').value='9999';changePageSize();")
    time.sleep(8)
    print("all  ", w.evaluate_js(js_count))
    w.destroy()
w = webview.create_window("t", url=(root/"app"/"index.html").as_uri())
webview.start(run, w)

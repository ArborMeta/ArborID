"""Screenshot ONLY the test window (by its title) showing a species detail view."""
import ctypes, sys, time
from ctypes import wintypes
from pathlib import Path
import webview
from PIL import ImageGrab
ctypes.windll.user32.SetProcessDPIAware()
root = Path(__file__).resolve().parent.parent
sci, out = sys.argv[1], Path(sys.argv[2])
TITLE = "ArborID screenshot test"
def window_rect():
    h = ctypes.windll.user32.FindWindowW(None, TITLE)
    r = wintypes.RECT(); ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)
def run(w):
    try:
        time.sleep(4)
        w.evaluate_js(f"openSpeciesDetail({sci!r})"); time.sleep(20)
        print("bark imgs loaded:", w.evaluate_js("[...document.querySelectorAll('#detail-bark img')].filter(i=>i.naturalWidth>0).length + ' of ' + document.querySelectorAll('#detail-bark img').length"))
        print("map zoom:", w.evaluate_js("document.querySelector('#detail-map .leaflet-proxy') ? 'ok' : 'none'"))
        w.evaluate_js("document.getElementById('detail-map').scrollIntoView({block:'center'})"); time.sleep(3)
        ImageGrab.grab(bbox=window_rect(), all_screens=True).save(out)
    finally:
        w.destroy()
w = webview.create_window(TITLE, url=(root/"app"/"index.html").as_uri(), width=1400, height=950, x=0, y=0, on_top=True)
webview.start(run, w)

"""Screenshot ONLY the test window running Identify on the given photo(s).

  python tools/screenshot_identify.py out.png photo1.jpg [photo2.jpg ...]
"""
import base64
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

import webview
from PIL import ImageGrab

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from main import Api  # noqa: E402

ctypes.windll.user32.SetProcessDPIAware()
out, photos = Path(sys.argv[1]), sys.argv[2:]
TITLE = "AusTree Atlas identify test"


def window_rect():
    h = ctypes.windll.user32.FindWindowW(None, TITLE)
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(h, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def run(w):
    try:
        time.sleep(4)
        print("button visible:", w.evaluate_js("!document.getElementById('identify-btn').classList.contains('hidden')"))
        w.evaluate_js("openIdentify()")
        for p in photos:
            url = "data:image/jpeg;base64," + base64.b64encode(Path(p).read_bytes()).decode()
            w.evaluate_js(f"""(async () => {{
                const blob = await (await fetch({json.dumps(url)})).blob();
                const dt = new DataTransfer(); dt.items.add(new File([blob], {json.dumps(Path(p).name)}, {{type: 'image/jpeg'}}));
                document.getElementById('id-drop').dispatchEvent(new DragEvent('drop', {{dataTransfer: dt, bubbles: true}}));
            }})()""")
            time.sleep(3)
        w.evaluate_js("runIdentify()")
        time.sleep(8)
        print("results:", w.evaluate_js("document.getElementById('id-results').innerText.slice(0, 600)"))
        ImageGrab.grab(bbox=window_rect(), all_screens=True).save(out)
    finally:
        w.destroy()


w = webview.create_window(TITLE, url=(root / "app" / "index.html").as_uri(), width=1400, height=1000, x=0, y=0,
                          on_top=True, js_api=Api())
webview.start(run, w)

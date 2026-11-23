"""Run the app's own JS generator in a hidden WebView and save the species list."""
import json, sys
from pathlib import Path
import webview
root = Path(__file__).resolve().parent.parent
out = root / "tools" / "species.json"
def grab(w):
    data = w.evaluate_js("JSON.stringify(generateFull520SpeciesDataset().map(s=>({sci:s.sci,common:s.common,genus:s.genus})))")
    out.write_text(data, encoding="utf-8"); w.destroy()
w = webview.create_window("dump", url=(root/"app"/"index.html").as_uri(), hidden=True)
webview.start(grab, w)

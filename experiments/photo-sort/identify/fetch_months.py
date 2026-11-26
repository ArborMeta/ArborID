"""Season data for Identify.

1. Each atlas species' native wild ALA records by month (same filter as the grid)
   -> identify/months.jsonl  {"sci":..., "months": [12 counts, Jan..Dec]}
2. The month each located val/test photo was taken (for tuning/testing)
   -> identify/photo_months.json  {image_id: month 1-12}
  python identify/fetch_months.py      (resumable)
"""
import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from trial import load_js, native_fqs, APP  # noqa: E402
from fetch_grid import EXTRA_FQ  # noqa: E402

UA = {"User-Agent": "ArborID/1.0 (personal botanical desktop app)"}
SEARCH = "https://biocache-ws.ala.org.au/ws/occurrences/search?"


def get_json(params):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(SEARCH + urllib.parse.urlencode(params), headers=UA),
                                        timeout=120) as r:
                return json.load(r)
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None


def species_months(sp, ranges):
    params = [("q", f'lsid:"{sp["guid"]}"'), ("facets", "month"), ("flimit", 20), ("pageSize", 0)]
    params += [("fq", f) for f in native_fqs(sp, ranges) + EXTRA_FQ]
    d = get_json(params)
    if d is None:
        return {"sci": sp["sci"], "error": True}
    m = [0] * 12
    for f in d.get("facetResults", []):
        for fr in f["fieldResult"]:
            code = (fr.get("i18nCode") or "").rsplit(".", 1)[-1]   # label is "January"; code is "month.1"
            if code.isdigit() and 1 <= int(code) <= 12:
                m[int(code) - 1] = fr["count"]
    return {"sci": sp["sci"], "months": m}


def photo_month(image_id):
    d = get_json([("q", f'image_url:"{image_id}"'), ("pageSize", 1)])
    occ = (d or {}).get("occurrences") or []
    m = occ[0].get("month") if occ else None
    try:
        m = int(m)
    except (TypeError, ValueError):
        m = None
    return image_id, m if m and 1 <= m <= 12 else None


def main():
    ala = load_js(APP / "data" / "ala_species.js", "ALA_SPECIES")
    ranges = load_js(APP / "data" / "native_ranges.js", "NATIVE_RANGES")
    out = HERE / "months.jsonl"
    done = {json.loads(l)["sci"] for l in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    todo = [s for s in ala if s["sci"] not in done]
    print(f"{len(todo)} species", flush=True)
    with out.open("a", encoding="utf-8") as f, ThreadPoolExecutor(4) as ex:
        for n, r in enumerate(ex.map(lambda s: species_months(s, ranges), todo), 1):
            if "months" in r:
                f.write(json.dumps(r) + "\n")
                f.flush()
            if n % 500 == 0:
                print(f"species {n}/{len(todo)}", flush=True)

    coords = json.loads((HERE / "coords.json").read_text())
    pm_file = HERE / "photo_months.json"
    pm = json.loads(pm_file.read_text()) if pm_file.exists() else {}
    ids = [i for i, c in coords.items() if c and i not in pm]
    print(f"{len(ids)} photos", flush=True)
    with ThreadPoolExecutor(4) as ex:
        for n, (i, m) in enumerate(ex.map(photo_month, ids), 1):
            pm[i] = m
            if n % 500 == 0:
                pm_file.write_text(json.dumps(pm))
                print(f"photos {n}/{len(ids)}", flush=True)
    pm_file.write_text(json.dumps(pm))
    print("done", sum(v is not None for v in pm.values()), "photos with a month", flush=True)


if __name__ == "__main__":
    main()

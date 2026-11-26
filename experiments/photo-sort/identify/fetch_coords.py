"""Look up the record location (lat/lon) for a sample of val and test photos (field photos only).

Used to tune and measure the location step.   python identify/fetch_coords.py
Writes identify/coords.json: {image_id: [lat, lon]}   (resumable)
"""
import json
import random
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from train import split_of

HERE = Path(__file__).resolve().parent
OUT = HERE / "coords.json"
UA = {"User-Agent": "ArborID/1.0 (personal botanical desktop app)"}
PER_SPLIT = 4000


def lookup(image_id):
    params = {"q": f'image_url:"{image_id}"', "pageSize": 1}
    url = "https://biocache-ws.ala.org.au/ws/occurrences/search?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                occ = json.load(r).get("occurrences") or []
            if occ and occ[0].get("decimalLatitude") is not None and occ[0].get("decimalLongitude") is not None:
                return image_id, [occ[0]["decimalLatitude"], occ[0]["decimalLongitude"]]
            return image_id, None
        except Exception:
            time.sleep(2 * (attempt + 1))
    return image_id, None


def main():
    idx = json.loads((HERE / "emb" / "index.json").read_text(encoding="utf-8"))
    by_split = {"val": [], "test": []}
    for p in idx["photos"]:
        if not p["herb"]:
            s = split_of(p["sci"], p["by"])
            if s in by_split:
                by_split[s].append(p["id"])
    rnd = random.Random(7)
    ids = []
    for s, lst in by_split.items():
        ids += rnd.sample(lst, min(PER_SPLIT, len(lst)))
    coords = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [i for i in ids if i not in coords]
    print(f"{len(todo)} to look up", flush=True)
    with ThreadPoolExecutor(6) as ex:
        for n, (i, c) in enumerate(ex.map(lookup, todo), 1):
            coords[i] = c
            if n % 500 == 0:
                OUT.write_text(json.dumps(coords))
                print(n, flush=True)
    OUT.write_text(json.dumps(coords))
    print("done", sum(v is not None for v in coords.values()), "with coordinates", flush=True)


if __name__ == "__main__":
    main()

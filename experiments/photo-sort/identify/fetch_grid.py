"""Fetch each atlas species' native wild records as counts on ALA's 0.1-degree grid (point-0.1).

Same native filter as the species-page map, plus no living-collection records.
Writes identify/grid.jsonl: {"sci":..., "cells": {"-31.2,117.4": n, ...}}  (resumable)
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

OUT = HERE / "grid.jsonl"
UA = {"User-Agent": "AusTreeAtlas/1.0 (personal botanical desktop app)"}
EXTRA_FQ = ["-basisOfRecord:LIVING_SPECIMEN",
            '-dataResourceName:"Records of the Australian National Botanic Gardens Seedbank"']


def fetch(sp, ranges):
    params = [("q", f'lsid:"{sp["guid"]}"'), ("facets", "point-0.1"), ("flimit", -1), ("pageSize", 0)]
    params += [("fq", f) for f in native_fqs(sp, ranges) + EXTRA_FQ]
    url = "https://biocache-ws.ala.org.au/ws/occurrences/search?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                d = json.load(r)
            cells = {}
            for f in d.get("facetResults", []):
                for fr in f["fieldResult"]:
                    cells[fr["label"]] = fr["count"]
            return {"sci": sp["sci"], "cells": cells}
        except Exception as e:
            err = e
            time.sleep(3 * (attempt + 1))
    return {"sci": sp["sci"], "error": str(err)}


def main():
    ala = load_js(APP / "data" / "ala_species.js", "ALA_SPECIES")
    ranges = load_js(APP / "data" / "native_ranges.js", "NATIVE_RANGES")
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if "cells" in r:
                done.add(r["sci"])
    todo = [s for s in ala if s["sci"] not in done]
    print(f"{len(todo)} species to fetch", flush=True)
    with OUT.open("a", encoding="utf-8") as f, ThreadPoolExecutor(6) as ex:
        for n, res in enumerate(ex.map(lambda s: fetch(s, ranges), todo), 1):
            if "cells" in res:
                f.write(json.dumps(res) + "\n")
                f.flush()
            else:
                print("failed", res, flush=True)
            if n % 200 == 0:
                print(f"{n}/{len(todo)}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()

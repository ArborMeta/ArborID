"""Download the ALA thumbnails listed in full_results.jsonl into images_train/ (resumable).

These are the training photos for the Identify model.   python identify/download_train.py
"""
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SORT = HERE.parent
OUT = SORT / "images_train"
UA = {"User-Agent": "ArborID/1.0 (personal botanical desktop app)"}
WORKERS = 24


def fetch(image_id):
    dest = OUT / f"{image_id}.jpg"
    if dest.exists():
        return "skip"
    i = image_id
    for url in (f"https://images-assets.ala.org.au/store/{i[-1]}/{i[-2]}/{i[-3]}/{i[-4]}/{i}/thumbnail",
                f"https://images.ala.org.au/image/{i}/thumbnail"):
        for attempt in range(3):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                    data = r.read()
                if len(data) < 500:
                    raise ValueError("too small")
                tmp = dest.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
                return "ok"
            except Exception:
                time.sleep(1 + attempt)
    return "fail"


def main():
    OUT.mkdir(exist_ok=True)
    ids = []
    for line in (SORT / "full_results.jsonl").read_text(encoding="utf-8").splitlines():
        ids += [p["id"] for p in json.loads(line)["photos"]]
    print(f"{len(ids)} photos", flush=True)
    counts = {"ok": 0, "skip": 0, "fail": 0}
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        for n, res in enumerate(ex.map(fetch, ids), 1):
            counts[res] += 1
            if n % 2000 == 0:
                rate = (counts["ok"] + 1) / (time.time() - t0)
                left = (len(ids) - n) / max(rate, 0.1) / 60
                print(f"{n}/{len(ids)} {counts}  {rate:.0f}/s  ~{left:.0f} min left", flush=True)
    print("done", counts, flush=True)


if __name__ == "__main__":
    main()

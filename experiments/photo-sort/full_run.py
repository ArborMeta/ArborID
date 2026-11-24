"""Sort ALA gallery photos for every species in the app into
Flowers / Fruit / Leaves / Bark / Whole tree, using OpenCLIP ViT-H-14-378 (DFN-5B) on the GPU.

- Up to 60 openly licensed photos per species from native-range ALA records
  (all photos of a record, max 4 per record).
- Thumbnails are downloaded into memory, classified and discarded; only results are kept.
- Results go to full_results.jsonl (one line per species), so the run can resume.

Usage:  .venv\\Scripts\\python full_run.py
"""
import hashlib
import io
import json
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from trial import CATEGORIES, OTHER_PROMPTS, load_js, native_fqs, APP, UA  # same prompts as the trial

HERE = Path(__file__).resolve().parent
OUT = HERE / "full_results.jsonl"
PER_SPECIES, PER_RECORD, SEARCH_ROWS = 60, 4, 100
PRIMARY_MIN, SECONDARY_MIN = 0.45, 0.30
DL_WORKERS = 12
LABELS = list(CATEGORIES) + ["other"]


def get(url, timeout=60, tries=4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def candidate_photos(sp, ranges):
    params = [("q", f'lsid:"{sp["guid"]}"'), ("fq", "multimedia:Image"), ("pageSize", SEARCH_ROWS)]
    params += [("fq", f) for f in native_fqs(sp, ranges)]
    d = json.loads(get("https://biocache-ws.ala.org.au/ws/occurrences/search?" + urllib.parse.urlencode(params), 120))
    photos, seen = [], set()
    for o in d.get("occurrences", []):
        lic = o.get("license") or ""
        if not re.search(r"CC|public|PD", lic, re.I):
            continue
        who = ((o.get("recordedBy") or o.get("collectors") or [None])[0]) or o.get("dataResourceName") or "Unknown"
        for img in (o.get("images") or [o.get("image")])[:PER_RECORD]:
            if img and img not in seen:
                seen.add(img)
                photos.append({"id": img, "by": who, "lic": lic, "src": o.get("dataResourceName") or "ALA"})
        if len(photos) >= PER_SPECIES:
            break
    return photos[:PER_SPECIES], d.get("totalRecords", 0)


def main():
    import torch
    import open_clip
    from PIL import Image

    ala = load_js(APP / "data" / "ala_species.js", "ALA_SPECIES")
    ranges = load_js(APP / "data" / "native_ranges.js", "NATIVE_RANGES")
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            done.add(json.loads(line)["sci"])
    todo = [sp for sp in ala if sp["sci"] not in done and sp.get("guid")]
    print(f"{len(ala)} species, {len(done)} already done, {len(todo)} to go", flush=True)

    device = "cuda"
    model, _, preprocess = open_clip.create_model_and_transforms("ViT-H-14-378-quickgelu", pretrained="dfn5b", device=device)
    tok = open_clip.get_tokenizer("ViT-H-14-378-quickgelu")
    model.eval()
    with torch.no_grad():
        feats = []
        for lab in LABELS:
            f = model.encode_text(tok(CATEGORIES.get(lab, OTHER_PROMPTS)).to(device)).float()
            f = f / f.norm(dim=-1, keepdim=True)
            m = f.mean(0)
            feats.append(m / m.norm())
        T = torch.stack(feats)

    pool = ThreadPoolExecutor(DL_WORKERS)
    lock = threading.Lock()
    t0, n_photos = time.time(), 0

    def fetch_img(p):
        i = p["id"]
        # Direct file address skips ALA's redirect; fall back to the redirecting URL.
        for url in (f"https://images-assets.ala.org.au/store/{i[-1]}/{i[-2]}/{i[-3]}/{i[-4]}/{i}/thumbnail",
                    f"https://images.ala.org.au/image/{i}/thumbnail"):
            try:
                raw = get(url, 60, 2)
                return p, preprocess(Image.open(io.BytesIO(raw)).convert("RGB"))
            except Exception:
                continue
        return p, None

    # Pipeline: search and queue photo downloads for the next AHEAD species, so the
    # shared download pool (DL_WORKERS at a time) never sits idle between species.
    AHEAD = 8
    search_pool = ThreadPoolExecutor(4)

    def prepare(sp):
        cands, total = candidate_photos(sp, ranges)
        return [pool.submit(fetch_img, p) for p in cands], total

    futures = [search_pool.submit(prepare, sp) for sp in todo[:AHEAD]]
    for i, sp in enumerate(todo):
        if i + AHEAD < len(todo):
            futures.append(search_pool.submit(prepare, todo[i + AHEAD]))
        try:
            img_futures, total = futures[i].result()
        except Exception as e:
            print(f"  search failed {sp['sci']}: {e}", flush=True)
            continue
        loaded = [(p, t) for p, t in (f.result() for f in img_futures) if t is not None]
        results = []
        if loaded:
            with torch.no_grad(), torch.autocast(device_type=device):
                for b in range(0, len(loaded), 64):
                    chunk = loaded[b:b + 64]
                    f = model.encode_image(torch.stack([t for _, t in chunk]).to(device)).float()
                    f = f / f.norm(dim=-1, keepdim=True)
                    probs = (100.0 * f @ T.T).softmax(-1).cpu()
                    for (p, _), pr in zip(chunk, probs):
                        scores = dict(zip(LABELS, (float(x) for x in pr)))
                        ranked = sorted(CATEGORIES, key=lambda k: -scores[k])
                        cats = []
                        if scores[ranked[0]] >= PRIMARY_MIN and scores[ranked[0]] > scores["other"]:
                            cats.append(ranked[0])
                            if scores[ranked[1]] >= SECONDARY_MIN:
                                cats.append(ranked[1])
                        results.append({**p, "cats": cats, "score": round(scores[ranked[0]], 3)})
        n_photos += len(loaded)
        with lock, OUT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"sci": sp["sci"], "ala_photo_records": total, "photos": results},
                               ensure_ascii=False) + "\n")
        if (i + 1) % 25 == 0 or i + 1 == len(todo):
            el = time.time() - t0
            rate = (i + 1) / el
            print(f"[{i + 1}/{len(todo)}] {n_photos:,} photos · {el / 60:.0f} min elapsed · "
                  f"~{(len(todo) - i - 1) / rate / 60:.0f} min left", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()

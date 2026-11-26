"""Trial: sort ALA gallery photos for 50 species into plant-part categories with CLIP.

Stages (each cached, so re-runs are quick):
  1. pick 50 species with many native-range photos, spread across genera
  2. download up to 30 openly licensed thumbnails per species
  3. zero-shot classify each photo with OpenCLIP
  4. write results.json and review.html

Nothing here touches the v1.0 app.
"""
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent.parent / "app"
IMG = HERE / "images"
CACHE = HERE / "cache"
UA = {"User-Agent": "ArborID/1.0 (personal botanical desktop app; photo-sort trial)"}
N_SPECIES, PER_SPECIES, MAX_PER_GENUS = 50, 30, 3
STATE_NAMES = {"NSW": "New South Wales", "VIC": "Victoria", "QLD": "Queensland", "WA": "Western Australia",
               "SA": "South Australia", "TAS": "Tasmania", "NT": "Northern Territory",
               "ACT": "Australian Capital Territory"}

# Several phrasings per category; CLIP scores are averaged over them.
CATEGORIES = {
    "flower": ["a close-up photo of the flowers of a plant", "a photo of blossoms on a tree",
               "a photo of a flower head", "a photo of a eucalyptus flower with stamens",
               "a photo of a wattle flower", "a photo of a banksia flower spike", "a photo of flower buds"],
    "fruit_seed": ["a close-up photo of ripe fruit hanging on a branch", "a close-up photo of open seed pods",
                   "a close-up photo of woody gumnuts", "a close-up photo of a woody seed cone",
                   "a close-up photo of berries", "a close-up photo of figs", "a photo of seeds in a hand"],
    "leaf": ["a close-up photo of leaves", "a photo of the foliage of a tree", "a photo of a leafy branch",
             "a photo of a single leaf", "a photo of green leaves", "a photo of a small plant growing in the bush",
             "a photo of a seedling", "a photo of a leafy shrub", "a photo of a young plant among leaf litter"],
    "bark": ["a close-up photo of tree bark", "a photo of the trunk of a tree showing its bark",
             "a photo of peeling bark", "a photo of rough fibrous bark", "a photo of smooth tree bark"],
    "whole_tree": ["a photo of a whole tree", "a photo of a tree in a landscape", "a photo of a tall tree",
                   "a photo of a shrub", "a photo of a tree canopy from a distance", "a photo of a forest"],
}
OTHER_PROMPTS = ["a photo of a herbarium specimen sheet", "a scanned image of a pressed plant",
                 "a map", "a diagram", "a photo of a waterfall", "a photo of a creek", "a photo of the ground",
                 "a photo of a label with text", "a photo of a person", "a photo of an animal"]
MIN_CONFIDENCE = 0.45   # below this the photo goes to "mixed/unclear"


def get_json(url):
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if key.exists():
        return json.loads(key.read_text(encoding="utf-8"))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90) as r:
                data = r.read()
            key.write_bytes(data)
            return json.loads(data)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))


def load_js(path, var):
    s = path.read_text(encoding="utf-8")
    i = s.index(f"window.{var}")
    s = s[s.index("=", i) + 1:]
    return json.loads(s[:s.rindex(";")])


def native_fqs(sp, ranges):
    base = 'country:"Australia" AND -degreeOfEstablishment:"cultivated" AND -establishmentMeans:"introduced"'
    rng = ranges.get(sp["sci"])
    states = [STATE_NAMES[c] for c in (rng["states"] if rng else []) if c in STATE_NAMES]
    if rng and states:
        return [base, "spatiallyValid:true AND stateProvince:(" + " OR ".join(f'"{n}"' for n in states) + ")"]
    return [base, "spatiallyValid:true"]


def image_search(sp, ranges, page_size):
    params = [("q", f'lsid:"{sp["guid"]}"'), ("fq", "multimedia:Image"), ("pageSize", page_size)]
    params += [("fq", f) for f in native_fqs(sp, ranges)]
    return get_json("https://biocache-ws.ala.org.au/ws/occurrences/search?" + urllib.parse.urlencode(params))


# ---------------------------------------------------------------- 1. pick species
def pick_species():
    out = HERE / "species.json"
    if out.exists():
        return json.loads(out.read_text(encoding="utf-8"))
    ala = load_js(APP / "data" / "ala_species.js", "ALA_SPECIES")
    ranges = load_js(APP / "data" / "native_ranges.js", "NATIVE_RANGES")
    by_genus = {}
    for sp in sorted(ala, key=lambda s: -s["occ"]):
        if sp["sci"] in ranges and ranges[sp["sci"]]["states"]:
            by_genus.setdefault(sp["genus"], []).append(sp)
    candidates = [sp for g in by_genus.values() for sp in g[:5]]
    print(f"checking photo counts for {len(candidates)} candidates...", flush=True)

    def count(sp):
        try:
            return sp, image_search(sp, ranges, 0).get("totalRecords", 0)
        except Exception:
            return sp, 0
    with ThreadPoolExecutor(4) as pool:
        counted = sorted(pool.map(count, candidates), key=lambda x: -x[1])

    chosen, per_genus = [], {}
    for sp, n in counted:
        if n < 150 or per_genus.get(sp["genus"], 0) >= MAX_PER_GENUS:
            continue
        per_genus[sp["genus"]] = per_genus.get(sp["genus"], 0) + 1
        chosen.append({"sci": sp["sci"], "common": sp["common"], "family": sp["family"],
                       "genus": sp["genus"], "guid": sp["guid"], "photos_on_ala": n})
        if len(chosen) == N_SPECIES:
            break
    out.write_text(json.dumps(chosen, indent=1, ensure_ascii=False), encoding="utf-8")
    return chosen


# ---------------------------------------------------------------- 2. download photos
def download_photos(species):
    ranges = load_js(APP / "data" / "native_ranges.js", "NATIVE_RANGES")
    jobs = []
    for sp in species:
        d = image_search(sp, ranges, 80)
        n = 0
        for o in d.get("occurrences", []):
            if not o.get("image") or not re.search(r"CC|public|PD", o.get("license") or "", re.I):
                continue
            jobs.append({"sci": sp["sci"], "id": o["image"], "url": o.get("smallImageUrl") or o.get("imageUrl"),
                         "large": o.get("largeImageUrl") or o.get("imageUrl"),
                         "credit": f"© {((o.get('recordedBy') or o.get('collectors') or ['Unknown'])[0])} · {o.get('license')}",
                         "source": o.get("dataResourceName") or "ALA", "basis": o.get("basisOfRecord", "")})
            n += 1
            if n == PER_SPECIES:
                break

    def fetch(j):
        dest = IMG / f"{j['id']}.jpg"
        if not dest.exists():
            try:
                with urllib.request.urlopen(urllib.request.Request(j["url"], headers=UA), timeout=60) as r:
                    dest.write_bytes(r.read())
            except Exception:
                return None
        j["file"] = f"images/{dest.name}"
        return j
    with ThreadPoolExecutor(4) as pool:
        got = [j for j in pool.map(fetch, jobs) if j]
    print(f"downloaded {len(got)} photos", flush=True)
    return got


# ---------------------------------------------------------------- 3. classify
def classify(photos, arch="ViT-B-32", weights="laion2b_s34b_b79k"):
    import torch
    import open_clip
    from PIL import Image
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"model {arch} ({weights}) on {device}", flush=True)
    model, _, preprocess = open_clip.create_model_and_transforms(arch, pretrained=weights, device=device)
    tok = open_clip.get_tokenizer(arch)
    model.eval()
    labels = list(CATEGORIES) + ["other"]
    with torch.no_grad():
        text_feats = []
        for lab in labels:
            prompts = CATEGORIES.get(lab, OTHER_PROMPTS)
            f = model.encode_text(tok(prompts).to(device)).float()
            f = f / f.norm(dim=-1, keepdim=True)
            m = f.mean(0)
            text_feats.append(m / m.norm())
        T = torch.stack(text_feats)
        t0 = time.time()
        for i in range(0, len(photos), 32):
            batch = photos[i:i + 32]
            ims = torch.stack([preprocess(Image.open(HERE / p["file"]).convert("RGB")) for p in batch]).to(device)
            with torch.autocast(device_type=device, enabled=device == "cuda"):
                f = model.encode_image(ims).float()
            f = f / f.norm(dim=-1, keepdim=True)
            probs = (100.0 * f @ T.T).softmax(-1).cpu()
            for p, pr in zip(batch, probs):
                scores = {lab: round(float(v), 3) for lab, v in zip(labels, pr)}
                best = max(scores, key=scores.get)
                p["scores"] = scores
                p["label"] = best if best != "other" and scores[best] >= MIN_CONFIDENCE else "mixed_unclear"
                if best == "other" and scores[best] >= MIN_CONFIDENCE:
                    p["label"] = "other"
        print(f"classified {len(photos)} photos in {time.time() - t0:.0f}s", flush=True)
    return photos


def main():
    import sys
    arch, weights, out = (sys.argv[1:4] + [None] * 3)[:3]
    arch, weights, out = arch or "ViT-B-32", weights or "laion2b_s34b_b79k", out or "results.json"
    for d in (IMG, CACHE):
        d.mkdir(exist_ok=True)
    species = pick_species()
    print(f"{len(species)} species chosen", flush=True)
    photos = classify(download_photos(species), arch, weights)
    (HERE / out).write_text(json.dumps({"species": species, "photos": photos}, indent=1,
                                                  ensure_ascii=False), encoding="utf-8")
    counts = {}
    for p in photos:
        counts[p["label"]] = counts.get(p["label"], 0) + 1
    print("labels:", dict(sorted(counts.items(), key=lambda x: -x[1])), flush=True)


if __name__ == "__main__":
    main()

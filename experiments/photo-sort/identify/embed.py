"""Compute image embeddings for all training photos, plus species text embeddings.

  python identify/embed.py bioclip      (ViT-B/16)
  python identify/embed.py bioclip-2    (ViT-L/14)

Writes identify/emb/<model>_img.npy (float16, L2-normalised, rows match index.json; missing images
are zero rows), identify/emb/<model>_txt.npy (one row per atlas species, order of species.json in
identify/emb/), and identify/emb/index.json.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image

HERE = Path(__file__).resolve().parent
SORT = HERE.parent
sys.path.insert(0, str(SORT))
from trial import load_js, APP  # noqa: E402

EMB = HERE / "emb"
IMAGES = SORT / "images_train"
BATCH = int(__import__("os").environ.get("GPU_BATCH", "256"))


def build_index():
    rows = []
    for line in (SORT / "full_results.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for p in r["photos"]:
            herb = "herbarium" in p["src"].lower() or "avh" in p["src"].lower()
            rows.append({"id": p["id"], "sci": r["sci"], "by": p["by"], "herb": herb, "cats": p["cats"]})
    ala = load_js(APP / "data" / "ala_species.js", "ALA_SPECIES")
    species = [{"sci": s["sci"], "common": s.get("common") or "", "family": s["family"], "genus": s["genus"]}
               for s in ala]
    (EMB / "index.json").write_text(json.dumps({"photos": rows, "species": species}), encoding="utf-8")
    return rows, species


def main():
    name = sys.argv[1]
    EMB.mkdir(exist_ok=True)
    rows, species = build_index()
    from ftmodel import create
    model, preprocess, tok = create(name)
    model = model.cuda().eval().half()

    # text: taxonomic + common-name prompts, averaged
    txt = []
    with torch.no_grad():
        for i in range(0, len(species), 256):
            chunk = species[i:i + 256]
            prompts = []
            for s in chunk:
                prompts += [f"a photo of {s['family']} {s['sci']}.",
                            f"a photo of {s['sci']}" + (f" with common name {s['common']}." if s["common"] else "."),
                            f"a photo of a plant, {s['sci']}."]
            e = model.encode_text(tok(prompts).cuda()).float()
            e = torch.nn.functional.normalize(e, dim=-1).view(len(chunk), 3, -1).mean(1)
            txt.append(torch.nn.functional.normalize(e, dim=-1).cpu().numpy())
    np.save(EMB / f"{name}_txt.npy", np.concatenate(txt).astype(np.float16))

    def load(r):
        try:
            return preprocess(Image.open(IMAGES / f"{r['id']}.jpg").convert("RGB"))
        except Exception:
            return None

    out = None
    t0 = time.time()
    missing = 0
    with ThreadPoolExecutor(12) as ex:
        batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
        nxt = ex.map(lambda b: [load(r) for r in b], batches)
        for bi, tensors in enumerate(nxt):
            ok = [j for j, t in enumerate(tensors) if t is not None]
            missing += len(tensors) - len(ok)
            from ftmodel import gpu_rest
            tb = time.time()
            with torch.no_grad():
                x = torch.stack([tensors[j] for j in ok]).cuda().half()
                e = torch.nn.functional.normalize(model.encode_image(x).float(), dim=-1).cpu().numpy()
            gpu_rest(tb)
            if out is None:
                out = np.zeros((len(rows), e.shape[1]), dtype=np.float16)
            for k, j in enumerate(ok):
                out[bi * BATCH + j] = e[k]
            if bi % 50 == 0:
                print(f"{(bi + 1) * BATCH}/{len(rows)}  {time.time() - t0:.0f}s", flush=True)
    np.save(EMB / f"{name}_img.npy", out)
    print(f"done in {time.time() - t0:.0f}s, missing {missing}", flush=True)


if __name__ == "__main__":
    main()

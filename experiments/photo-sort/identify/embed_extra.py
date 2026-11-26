"""Embed the extra rare-species photos (fetch_extra.py) and drop near-duplicates.

A photo is dropped if it is nearly identical (cosine > DUP) to any ALA photo of the same species
(train, val or test -- iNaturalist Australia photos are often already in ALA) or to another extra photo.
  python identify/embed_extra.py bioclip-2
Writes identify/emb/<name>_extra.npy and identify/emb/extra_index.json (kept photos only).
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import open_clip
import torch
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from train import load  # noqa: E402

IMAGES = HERE.parent / "images_extra"
DUP = 0.95


def main():
    name = sys.argv[1]
    idx, X, T, y, ok, split = load(name)
    sp_index = {s["sci"]: i for i, s in enumerate(idx["species"])}
    rows = []
    for line in (HERE / "extra.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for p in r["photos"]:
            if (IMAGES / f"{p['id']}.jpg").exists():
                rows.append({**p, "sci": r["sci"]})
    # Drop photos by a photographer who also has a val/test photo of that species (e.g. another shot of
    # the same plant): otherwise they leak the answer into the test and inflate the scores.
    import re
    from train import split_of
    norm = lambda s: re.sub(r"[^a-z]", "", str(s).lower())  # noqa: E731
    held = {(p["sci"], norm(p["by"])) for p in idx["photos"]
            if not p["herb"] and split_of(p["sci"], p["by"]) in ("val", "test")}
    n_before = len(rows)
    rows = [p for p in rows if (p["sci"], norm(p["by"])) not in held]
    print(f"dropped {n_before - len(rows)} photos by photographers with held-out photos of the species")
    # A fine-tuned model reuses the base model's duplicate check (its own features no longer flag copies
    # reliably, and the fine-tune was trained on exactly the base model's kept list).
    base_keep = None
    if name.endswith("-ft"):
        base_keep = {p["id"] for p in json.loads((HERE / "emb" / f"extra_index_{name[:-3]}.json").read_text(encoding="utf-8"))}
        rows = [p for p in rows if p["id"] in base_keep]
    from ftmodel import create
    model, pre, _ = create(name)
    model = model.cuda().eval().half()

    def prep(p):
        try:
            return pre(Image.open(IMAGES / f"{p['id']}.jpg").convert("RGB"))
        except Exception:
            return None

    E = np.zeros((len(rows), X.shape[1]), np.float32)
    good = np.zeros(len(rows), bool)
    with ThreadPoolExecutor(12) as ex:
        for k in range(0, len(rows), 256):
            ts = list(ex.map(prep, rows[k:k + 256]))
            keep = [j for j, t in enumerate(ts) if t is not None]
            if not keep:
                continue
            import time
            from ftmodel import gpu_rest
            tb = time.time()
            with torch.no_grad():
                e = torch.nn.functional.normalize(model.encode_image(torch.stack([ts[j] for j in keep]).cuda().half()).float(), dim=-1)
            E[[k + j for j in keep]] = e.cpu().numpy()
            gpu_rest(tb)
            good[[k + j for j in keep]] = True

    by_sp = {}
    for i, s in enumerate(y):
        if ok[i]:
            by_sp.setdefault(s, []).append(i)
    kept, dups_ala, dups_self = [], 0, 0
    seen = {}
    for j, p in enumerate(rows):
        if not good[j]:
            continue
        s = sp_index[p["sci"]]
        if base_keep is not None:
            kept.append(j)
            continue
        ala = by_sp.get(s, [])
        if ala and (X[ala] @ E[j]).max() > DUP:
            dups_ala += 1
            continue
        prev = seen.setdefault(s, [])
        if prev and (E[prev] @ E[j]).max() > DUP:
            dups_self += 1
            continue
        prev.append(j)
        kept.append(j)
    np.save(HERE / "emb" / f"{name}_extra.npy", E[kept].astype(np.float16))
    (HERE / "emb" / f"extra_index_{name}.json").write_text(json.dumps([rows[j] for j in kept]), encoding="utf-8")
    if base_keep is None:   # finetune.py trains on the base model's kept list
        (HERE / "emb" / "extra_index.json").write_text(json.dumps([rows[j] for j in kept]), encoding="utf-8")
    src = {}
    for j in kept:
        src[rows[j]["src"]] = src.get(rows[j]["src"], 0) + 1
    print(f"{len(rows)} extra photos: kept {len(kept)}, dropped {dups_ala} copies of ALA photos, "
          f"{dups_self} repeats; kept by source {src}; species {len({rows[j]['sci'] for j in kept})}")


if __name__ == "__main__":
    main()

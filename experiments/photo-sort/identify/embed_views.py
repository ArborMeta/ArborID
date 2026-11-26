"""Embeddings of several views of each val/test photo, to test using the whole photo
instead of only the centre square.

Views: 0 centre crop (as now) | 1 whole photo padded to a square | 2 whole photo squashed to a square
       3 / 4 squares at the two ends of the long side (top/bottom or left/right)
  python identify/embed_views.py bioclip-2   -> identify/emb/<name>_views.npy  [N, 5, D] float16 for val+test rows
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

IMAGES = HERE.parent / "images_train"
MEAN = (int(0.48145466 * 255), int(0.4578275 * 255), int(0.40821073 * 255))


def views(img):
    img = img.convert("RGB")
    w, h = img.size
    s = max(w, h)
    pad = Image.new("RGB", (s, s), MEAN)
    pad.paste(img, ((s - w) // 2, (s - h) // 2))
    m = min(w, h)
    if h >= w:
        a, b = img.crop((0, 0, w, m)), img.crop((0, h - m, w, h))
    else:
        a, b = img.crop((0, 0, m, h)), img.crop((w - m, 0, w, h))
    return [img, pad, img.resize((224, 224), Image.BICUBIC), a, b]


def main():
    name = sys.argv[1]
    idx, X, T, y, ok, split = load(name)
    rows = np.where(ok & np.isin(split, ["val", "test"]))[0]
    from ftmodel import create
    model, pre, _ = create(name)
    model = model.cuda().eval().half()
    out = np.zeros((len(X), 5, X.shape[1]), np.float16)

    def prep(i):
        v = views(Image.open(IMAGES / f"{idx['photos'][i]['id']}.jpg"))
        return torch.stack([pre(x) for x in v])

    with ThreadPoolExecutor(12) as ex:
        for k in range(0, len(rows), 64):
            chunk = rows[k:k + 64]
            x = torch.cat(list(ex.map(prep, chunk))).cuda().half()
            import time
            from ftmodel import gpu_rest
            tb = time.time()
            with torch.no_grad():
                e = torch.nn.functional.normalize(model.encode_image(x).float(), dim=-1)
            gpu_rest(tb)
            out[chunk] = e.view(len(chunk), 5, -1).cpu().numpy()
            if k % 6400 == 0:
                print(f"{k}/{len(rows)}", flush=True)
    np.save(HERE / "emb" / f"{name}_views.npy", out)
    print("done", flush=True)


if __name__ == "__main__":
    main()

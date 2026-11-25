"""Tune the location step and multi-photo damping on val photos; report accuracy + calibration on test.

  python identify/eval_location.py bioclip

Needs: eval_<name>.npz (from train.py), coords.json (fetch_coords.py), model/grid.npz (build_grid.py).
The photo's own record is in the grid, so it is subtracted from the true species' counts first
(otherwise the test would leak the answer). Writes model/identify_config.json for the app.
"""
import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

from train import calibration_table, load, softmax

HERE = Path(__file__).resolve().parent
MODEL = HERE / "model"
RADII = [10, 25, 50, 100, 200]


def counts_for(points, g, n_species):
    """For each (lat, lon), record counts per species within each radius in RADII -> [P, R, S]."""
    glat, glon = g["lat"] / 10.0, g["lon"] / 10.0
    sp, n = g["sp"].astype(np.int64), g["n"].astype(np.float64)
    out = np.zeros((len(points), len(RADII), n_species), np.float32)
    for k, (lat, lon) in enumerate(points):
        box = (np.abs(glat - lat) < 2.0) & (np.abs(glon - lon) < 2.5)
        d = np.sqrt(((glat[box] - lat) * 111) ** 2 + ((glon[box] - lon) * 111 * math.cos(math.radians(lat))) ** 2)
        s, c = sp[box], n[box]
        for r, R in enumerate(RADII):
            m = d <= R
            out[k, r] = np.bincount(s[m], c[m], minlength=n_species)
    return out


def logprior(cnt, near_r, wide_r, wide_w, gamma, absent):
    score = cnt[:, near_r] + wide_w * cnt[:, wide_r]
    return np.where(score > 0, gamma * np.log(score + 1.0), math.log(absent))


def nll_top(logp, y):
    logp = logp - logp.max(1, keepdims=True)
    logp = logp - np.log(np.exp(logp).sum(1, keepdims=True))
    return -logp[np.arange(len(y)), y].mean(), (logp.argmax(1) == y).mean()


def main():
    name = sys.argv[1]
    idx, X, T, y, ok, split = load(name)
    ev = np.load(HERE / f"eval_{name}.npz")
    W, b, scale, t = ev["W"], ev["b"], float(ev["scale"]), float(ev["t"])
    coords = json.loads((HERE / "coords.json").read_text())
    g = np.load(MODEL / "grid.npz")
    S = len(idx["species"])
    genus = np.array([s["genus"] for s in idx["species"]])

    sets = {}
    for nm in ("va", "te"):
        rows = [i for i in ev[nm] if coords.get(idx["photos"][i]["id"])]
        pts = [coords[idx["photos"][i]["id"]] for i in rows]
        cnt = counts_for(pts, g, S)
        yy = y[rows]
        cnt[np.arange(len(rows)), :, yy] = np.maximum(cnt[np.arange(len(rows)), :, yy] - 1, 0)  # remove own record
        img = (scale * X[rows] @ W.T + b) / t
        sets[nm] = (np.array(rows), img, cnt, yy)
        print(f"{nm}: {len(rows)} photos with coordinates")

    img, cnt, yy = sets["va"][1], sets["va"][2], sets["va"][3]
    best = None
    for near_r, wide_r, wide_w, gamma, absent, it in itertools.product(
            range(len(RADII)), range(len(RADII)), [0, 0.05, 0.2], [0.25, 0.5, 0.75, 1.0], [1e-2, 1e-3, 1e-4], [0.8, 1.0, 1.25]):
        if wide_r <= near_r and wide_w:
            continue
        nll, top1 = nll_top(img * it + logprior(cnt, near_r, wide_r, wide_w, gamma, absent), yy)
        if best is None or nll < best[0]:
            best = (nll, top1, near_r, wide_r, wide_w, gamma, absent, it)
    nll, top1, near_r, wide_r, wide_w, gamma, absent, it = best
    print(f"best on val: near {RADII[near_r]} km, wide {RADII[wide_r]} km x{wide_w}, gamma {gamma}, absent {absent}, "
          f"image temp x{it}  (val top-1 {top1:.1%})")

    # multi-photo damping: groups of 2-3 val photos of one species by one photographer
    rows, img_v, cnt_v, y_v = sets["va"]
    groups = defaultdict(list)
    for k, i in enumerate(rows):
        groups[(idx["photos"][i]["sci"], idx["photos"][i]["by"])].append(k)
    groups = [v[:3] for v in groups.values() if len(v) >= 2]
    best_d = None
    for damp in [0.4, 0.5, 0.6, 0.7, 0.8, 1.0]:
        lp = np.stack([damp * (img_v[v] * it).sum(0) + logprior(cnt_v[v[:1]], near_r, wide_r, wide_w, gamma, absent)[0]
                       for v in groups])
        nll_g, top1_g = nll_top(lp, y_v[[v[0] for v in groups]])
        if best_d is None or nll_g < best_d[0]:
            best_d = (nll_g, top1_g, damp)
    print(f"multi-photo damping {best_d[2]} ({len(groups)} val groups, top-1 {best_d[1]:.1%})")

    # test
    rows, img_t, cnt_t, y_t = sets["te"]
    for label, lp in [("test, image only", img_t), ("test, image + location",
                                                     img_t * it + logprior(cnt_t, near_r, wide_r, wide_w, gamma, absent))]:
        p = softmax(lp)
        order = np.argsort(-p, 1)
        top5 = (order[:, :5] == y_t[:, None]).any(1).mean()
        gen = (genus[order[:, 0]] == genus[y_t]).mean()
        print(f"{label}: top-1 {(order[:, 0] == y_t).mean():.1%}  top-5 {top5:.1%}  genus {gen:.1%}")
    print("calibration on test (image + location):")
    print(calibration_table(p, y_t))
    groups = defaultdict(list)
    for k, i in enumerate(rows):
        groups[(idx["photos"][i]["sci"], idx["photos"][i]["by"])].append(k)
    groups = [v[:3] for v in groups.values() if len(v) >= 2]
    lp = np.stack([best_d[2] * (img_t[v] * it).sum(0) + logprior(cnt_t[v[:1]], near_r, wide_r, wide_w, gamma, absent)[0]
                   for v in groups])
    yg = y_t[[v[0] for v in groups]]
    p = softmax(lp)
    order = np.argsort(-p, 1)
    print(f"test, 2-3 photos + location ({len(groups)} groups): top-1 {(order[:, 0] == yg).mean():.1%}  "
          f"top-5 {(order[:, :5] == yg[:, None]).any(1).mean():.1%}  genus {(genus[order[:, 0]] == genus[yg]).mean():.1%}")
    print(calibration_table(p, yg))

    cfg = {"onnx": f"{name}_visual_w8.onnx", "head": f"{name}_head.npz", "temperature": t / it,
           "multi_photo_damping": best_d[2],
           "location": {"near_km": RADII[near_r], "wide_km": RADII[wide_r], "wide_weight": wide_w,
                        "gamma": gamma, "absent": absent}}
    MODEL.mkdir(exist_ok=True)
    (MODEL / f"identify_config_{name}.json").write_text(json.dumps(cfg, indent=1))
    print(cfg)


if __name__ == "__main__":
    main()

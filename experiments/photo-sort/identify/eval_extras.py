"""Test 'whole photo' views and the season step on top of the current model + location settings.

  python identify/eval_extras.py bioclip-2 [head.npz]
Uses the train-split head (eval_<name>.npz) unless another is given, the view embeddings from
embed_views.py, the location settings in the app's model/identify_config.json, months.jsonl and
photo_months.json. Tunes on val, reports on test.
"""
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

from eval_location import RADII, counts_for, nll_top
from train import calibration_table, load, softmax

HERE = Path(__file__).resolve().parent
APP_MODEL = HERE.parent.parent.parent / "model"

VIEW_SETS = {"centre crop (now)": [0], "whole, padded": [1], "whole, squashed": [2],
             "centre + padded": [0, 1], "centre + both ends": [0, 3, 4], "centre + padded + both ends": [0, 1, 3, 4],
             "all five": [0, 1, 2, 3, 4]}


def month_table(species):
    rows = {}
    for line in (HERE / "months.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        rows[r["sci"]] = r["months"]
    M = np.array([rows.get(s["sci"], [0] * 12) for s in species], np.float64)
    M = M + 0.5 * (np.roll(M, 1, 1) + np.roll(M, -1, 1))       # a photo in early June is near May too
    q = M.sum(0) / M.sum()
    return M, q


def season_logprior(M, q, month, alpha, beta):
    p = (M[:, month - 1] + alpha * q[month - 1]) / (M.sum(1) + alpha)
    return beta * np.log(p / q[month - 1])


def location_logprior(cnt, loc):
    near = cnt[:, RADII.index(loc["near_km"])]
    wide = cnt[:, RADII.index(loc["wide_km"])]
    score = near + loc["wide_weight"] * wide
    return np.where(score > 0, loc["gamma"] * np.log(score + 1.0), math.log(loc["absent"]))


def main():
    name = sys.argv[1]
    idx, X, T, y, ok, split = load(name)
    head = np.load(sys.argv[2] if len(sys.argv) > 2 else HERE / f"eval_{name}.npz")
    W, b, scale = head["W"].astype(np.float32), head["b"], float(head["scale"])
    t = float(head["t"]) if "t" in head else float(np.load(HERE / f"eval_{name}.npz")["t"])
    V = np.load(HERE / "emb" / f"{name}_views.npy").astype(np.float32)
    cfg = json.loads((APP_MODEL / "identify_config.json").read_text())
    loc = cfg["location"]
    coords = json.loads((HERE / "coords.json").read_text())
    pmonth = json.loads((HERE / "photo_months.json").read_text())
    g = np.load(HERE / "model" / "grid.npz")
    S = len(idx["species"])
    genus = np.array([s["genus"] for s in idx["species"]])
    M, q = month_table(idx["species"])

    def logits(rows, views):
        e = V[rows][:, views].mean(1)
        e /= np.linalg.norm(e, axis=1, keepdims=True)
        return (scale * e @ W.T + b) / t

    data = {}
    for nm in ("val", "test"):
        rows = np.where(ok & (split == nm))[0]
        located = np.array([i for i in rows if coords.get(idx["photos"][i]["id"])])
        cnt = counts_for([coords[idx["photos"][i]["id"]] for i in located], g, S)
        yy = y[located]
        cnt[np.arange(len(located)), :, yy] = np.maximum(cnt[np.arange(len(located)), :, yy] - 1, 0)
        data[nm] = (rows, located, location_logprior(cnt, loc))

    print("== whole photo: image only, all test photos (top-1 / top-5 / genus)")
    for label, vs in VIEW_SETS.items():
        rows = data["test"][0]
        p = logits(rows, vs)
        o = np.argsort(-p, 1)[:, :5]
        print(f"  {label:28s} {(o[:, 0] == y[rows]).mean():.1%} / {(o == y[rows][:, None]).any(1).mean():.1%} / "
              f"{(genus[o[:, 0]] == genus[y[rows]]).mean():.1%}")

    best_vs = None
    for label, vs in VIEW_SETS.items():
        rows = data["val"][0]
        nll, top1 = nll_top(logits(rows, vs) * 0.8, y[rows])
        if best_vs is None or top1 > best_vs[0]:
            best_vs = (top1, label, vs)
    print(f"best views on val (top-1): {best_vs[1]} {best_vs[0]:.1%}")
    vs = best_vs[2]

    # season: tune on val photos that have a location and a month
    def with_month(nm):
        rows, located, lp = data[nm]
        keep = [k for k, i in enumerate(located) if pmonth.get(idx["photos"][i]["id"])]
        months = np.array([pmonth[idx["photos"][located[k]]["id"]] for k in keep])
        return located[keep], lp[keep], months

    vrows, vlp, vm = with_month("val")
    best = None
    for alpha, beta, it in itertools.product([2, 5, 20, 50], [0, 0.25, 0.5, 0.75, 1.0], [0.8, 1.0]):
        sp = np.stack([season_logprior(M, q, m, alpha, beta) for m in vm])
        nll, top1 = nll_top(logits(vrows, vs) * it + vlp + sp, y[vrows])
        if best is None or nll < best[0]:
            best = (nll, alpha, beta, it)
    _, alpha, beta, it = best
    print(f"season on val: alpha {alpha}, beta {beta}, image temp x{it}  ({len(vrows)} val photos with location + month)")

    trows, tlp, tm = with_month("test")
    sp = np.stack([season_logprior(M, q, m, alpha, beta) for m in tm])
    print(f"== test photos with location + month ({len(trows)}):")
    for label, z in [("now: centre crop + location", logits(trows, [0]) * 0.8 + tlp),
                     ("whole photo + location", logits(trows, vs) * it + tlp),
                     ("whole photo + location + season", logits(trows, vs) * it + tlp + sp)]:
        p = softmax(z)
        o = np.argsort(-p, 1)[:, :5]
        print(f"  {label:34s} top-1 {(o[:, 0] == y[trows]).mean():.1%}  top-5 {(o == y[trows][:, None]).any(1).mean():.1%}  "
              f"genus {(genus[o[:, 0]] == genus[y[trows]]).mean():.1%}")
    print(calibration_table(p, y[trows]))
    json.dump({"views": vs, "season": {"alpha": alpha, "beta": beta}, "image_temp": it},
              open(HERE / f"extras_{name}.json", "w"))


if __name__ == "__main__":
    main()

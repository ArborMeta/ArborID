"""Train and evaluate the species classifier on BioCLIP embeddings.

  python identify/train.py bioclip [--final]

Split: per species, each photographer's photos go wholly to train, val or test (so near-identical
shots from one outing can't leak into the test set). Herbarium sheets are train-only; val/test are
field photos. --final also trains on val+test and writes identify/model/<name>_head.npz.

Classifier: a linear layer over the frozen image embedding, initialised from the species' text
embeddings (zero-shot) and regularised towards them, so species with few photos fall back to
the text embedding instead of overfitting.
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
EMB = HERE / "emb"
MODEL = HERE / "model"


def split_of(sci, by):
    h = int(hashlib.md5(f"{sci}|{by}".encode()).hexdigest()[:8], 16) % 100
    return "test" if h < 15 else "val" if h < 25 else "train"


def load(name):
    idx = json.loads((EMB / "index.json").read_text(encoding="utf-8"))
    X = np.load(EMB / f"{name}_img.npy").astype(np.float32)
    T = np.load(EMB / f"{name}_txt.npy").astype(np.float32)
    sp_index = {s["sci"]: i for i, s in enumerate(idx["species"])}
    y = np.array([sp_index[p["sci"]] for p in idx["photos"]])
    ok = np.abs(X).sum(1) > 0
    split = np.array(["train" if p["herb"] else split_of(p["sci"], p["by"]) for p in idx["photos"]])
    return idx, X, T, y, ok, split


def train_head(X, y, T, epochs=40, reg=1e-3, lr=2e-3):
    dev = "cuda"
    Xt, yt = torch.tensor(X, device=dev), torch.tensor(y, device=dev)
    W0 = torch.tensor(T, device=dev)
    W = torch.nn.Parameter(W0.clone())
    b = torch.nn.Parameter(torch.zeros(len(T), device=dev))
    scale = torch.nn.Parameter(torch.tensor(30.0, device=dev))
    counts = torch.bincount(yt, minlength=len(T)).float()
    cw = (counts.clamp(min=1) ** -0.5)
    cw = cw / cw[yt].mean()
    opt = torch.optim.AdamW([W, b, scale], lr=lr, weight_decay=0)
    n = len(Xt)
    for ep in range(epochs):
        perm = torch.randperm(n, device=dev)
        for i in range(0, n, 4096):
            j = perm[i:i + 4096]
            logits = scale * Xt[j] @ F.normalize(W, dim=-1).T + b
            loss = F.cross_entropy(logits, yt[j], weight=cw) + reg * ((W - W0) ** 2).sum(1).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
    with torch.no_grad():
        return F.normalize(W, dim=-1).cpu().numpy(), b.cpu().numpy(), float(scale)


def logits_of(X, W, b, scale):
    return scale * X @ W.T + b


def topk_acc(logits, y, k):
    top = np.argsort(-logits, 1)[:, :k]
    return (top == y[:, None]).any(1).mean()


def fit_temperature(logits, y):
    """Temperature that minimises validation log-loss (grid search: robust, unlike LBFGS here)."""
    lt, yt = torch.tensor(logits, dtype=torch.float64), torch.tensor(y)
    grid = np.exp(np.linspace(np.log(0.2), np.log(5.0), 161))
    losses = [float(F.cross_entropy(lt / t, yt)) for t in grid]
    return float(grid[int(np.argmin(losses))])


def calibration_table(probs, y):
    conf = probs.max(1)
    right = probs.argmax(1) == y
    rows = []
    for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .9), (.9, 1.01)]:
        m = (conf >= lo) & (conf < hi)
        if m.sum():
            rows.append(f"  says {lo:.0%}-{min(hi, 1):.0%}: {m.sum():6d} photos, mean claim {conf[m].mean():.0%}, actually right {right[m].mean():.0%}")
    return "\n".join(rows)


def softmax(z):
    z = z - z.max(1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(1, keepdims=True)


def main():
    name = sys.argv[1]
    idx, X, T, y, ok, split = load(name)
    genus = np.array([s["genus"] for s in idx["species"]])
    tr, va, te = (ok & (split == s) for s in ("train", "val", "test"))
    print(f"{name}: train {tr.sum()}, val {va.sum()}, test {te.sum()} photos")

    zs = 100 * X[te] @ T.T
    print(f"zero-shot (text only):  top-1 {topk_acc(zs, y[te], 1):.1%}  top-5 {topk_acc(zs, y[te], 5):.1%}")

    # --extra: add the rare-species photos from fetch_extra.py / embed_extra.py to TRAINING only
    # (val/test stay the same ALA photos, so results stay comparable)
    Xtr, ytr = X[tr], y[tr]
    suffix = ""
    if "--extra" in sys.argv:
        sp_index = {s["sci"]: i for i, s in enumerate(idx["species"])}
        Xe = np.load(EMB / f"{name}_extra.npy").astype(np.float32)
        ye = np.array([sp_index[p["sci"]] for p in json.loads((EMB / f"extra_index_{name}.json").read_text(encoding="utf-8"))])
        Xtr, ytr = np.concatenate([Xtr, Xe]), np.concatenate([ytr, ye])
        suffix = "_extra"
        print(f"+ {len(Xe)} extra rare-species photos in training")
    W, b, scale = train_head(Xtr, ytr, T)
    lv, lt = logits_of(X[va], W, b, scale), logits_of(X[te], W, b, scale)
    t = fit_temperature(lv, y[va])
    pt = softmax(lt / t)
    g_right = (genus[pt.argmax(1)] == genus[y[te]]).mean()
    print(f"trained (image only):  top-1 {topk_acc(lt, y[te], 1):.1%}  top-5 {topk_acc(lt, y[te], 5):.1%}  "
          f"top-10 {topk_acc(lt, y[te], 10):.1%}  genus right {g_right:.1%}   temperature {t:.2f}")
    print("calibration on test (image only):")
    print(calibration_table(pt, y[te]))
    # rare species: fewer than 30 ALA field photos
    field = np.bincount(y[ok & np.array([not p["herb"] for p in idx["photos"]])], minlength=len(T))
    rare = field[y[te]] < 30
    lr = lt[rare]
    print(f"rare species only ({rare.sum()} test photos): top-1 {topk_acc(lr, y[te][rare], 1):.1%}  "
          f"top-5 {topk_acc(lr, y[te][rare], 5):.1%}")

    np.savez(HERE / f"eval_{name}{suffix}.npz", W=W, b=b, scale=scale, t=t, te=np.where(te)[0], va=np.where(va)[0])
    if "--final" in sys.argv:
        MODEL.mkdir(exist_ok=True)
        Xall, yall = X[ok], y[ok]
        if suffix:
            Xall, yall = np.concatenate([Xall, Xe]), np.concatenate([yall, ye])
        W, b, scale = train_head(Xall, yall, T)
        np.savez(MODEL / f"{name}_head.npz", W=W.astype(np.float16), b=b, scale=scale, t=t)
        print("final head written")


if __name__ == "__main__":
    main()

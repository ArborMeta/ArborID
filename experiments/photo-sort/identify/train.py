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
    lt, yt = torch.tensor(logits), torch.tensor(y)
    t = torch.nn.Parameter(torch.tensor(1.0))
    opt = torch.optim.LBFGS([t], max_iter=100)

    def closure():
        opt.zero_grad()
        loss = F.cross_entropy(lt / t, yt)
        loss.backward()
        return loss
    opt.step(closure)
    return float(t)


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

    W, b, scale = train_head(X[tr], y[tr], T)
    lv, lt = logits_of(X[va], W, b, scale), logits_of(X[te], W, b, scale)
    t = fit_temperature(lv, y[va])
    pt = softmax(lt / t)
    g_right = (genus[pt.argmax(1)] == genus[y[te]]).mean()
    print(f"trained (image only):  top-1 {topk_acc(lt, y[te], 1):.1%}  top-5 {topk_acc(lt, y[te], 5):.1%}  "
          f"top-10 {topk_acc(lt, y[te], 10):.1%}  genus right {g_right:.1%}   temperature {t:.2f}")
    print("calibration on test (image only):")
    print(calibration_table(pt, y[te]))

    np.savez(HERE / f"eval_{name}.npz", W=W, b=b, scale=scale, t=t, te=np.where(te)[0], va=np.where(va)[0])
    if "--final" in sys.argv:
        MODEL.mkdir(exist_ok=True)
        W, b, scale = train_head(X[ok], y[ok], T)
        np.savez(MODEL / f"{name}_head.npz", W=W.astype(np.float16), b=b, scale=scale, t=t)
        print("final head written")


if __name__ == "__main__":
    main()

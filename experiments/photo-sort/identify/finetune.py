"""Fine-tune the last blocks of the BioCLIP-2 image encoder on the atlas photos (GPU).

  python identify/finetune.py [--blocks 8] [--epochs 6] [--bs 96]

Trains on the TRAIN split (ALA photos incl. herbarium sheets) + the extra rare-species photos
(emb/extra_index.json). Val/test photos are never trained on. The species head starts from the current
linear head (eval_bioclip-2.npz) and is trained jointly. Augmentation: random crops (incl. close-ups),
flips, colour jitter. After every epoch: val top-1/top-5 (centre crop); the best epoch's encoder is saved to
identify/model/bioclip-2-ft_visual.pt. Then re-run embed.py / train.py / etc. with name "bioclip-2-ft".
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms as Tr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ftmodel import create  # noqa: E402
from train import load  # noqa: E402

SORT = HERE.parent
MEAN, STD = (0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711)


class Photos(Dataset):
    def __init__(self, paths, labels, tf):
        self.paths, self.labels, self.tf = paths, labels, tf

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        try:
            img = Image.open(self.paths[i]).convert("RGB")
        except Exception:
            img = Image.new("RGB", (224, 224))
        return self.tf(img), self.labels[i]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=8)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--bs", type=int, default=96)
    ap.add_argument("--lr", type=float, default=2e-5)
    a = ap.parse_args()
    torch.manual_seed(0)

    idx, X, T, y, ok, split = load("bioclip-2")
    sp_index = {s["sci"]: i for i, s in enumerate(idx["species"])}
    tr = np.where(ok & (split == "train"))[0]
    va = np.where(ok & (split == "val"))[0]
    paths = [str(SORT / "images_train" / f"{idx['photos'][i]['id']}.jpg") for i in tr]
    labels = [int(y[i]) for i in tr]
    extra_file = HERE / "emb" / "extra_index.json"
    if extra_file.exists():
        extra = json.loads(extra_file.read_text(encoding="utf-8"))
        paths += [str(SORT / "images_extra" / f"{p['id']}.jpg") for p in extra]
        labels += [sp_index[p["sci"]] for p in extra]
    print(f"train {len(paths)} photos ({len(paths) - len(tr)} extra), val {len(va)}", flush=True)

    train_tf = Tr.Compose([Tr.RandomResizedCrop(224, scale=(0.3, 1.0), interpolation=Tr.InterpolationMode.BICUBIC),
                           Tr.RandomHorizontalFlip(), Tr.ColorJitter(0.25, 0.25, 0.2, 0.02),
                           Tr.ToTensor(), Tr.Normalize(MEAN, STD)])
    model, pre, _ = create("bioclip-2")
    visual = model.visual.cuda()
    del model
    for p in visual.parameters():
        p.requires_grad = False
    tuned = list(visual.transformer.resblocks[-a.blocks:]) + [visual.ln_post]
    for m in tuned:
        for p in m.parameters():
            p.requires_grad = True
    visual.proj.requires_grad = True
    backbone = [p for p in visual.parameters() if p.requires_grad]
    print(f"tuning last {a.blocks} blocks: {sum(p.numel() for p in backbone) / 1e6:.0f}M params", flush=True)

    head = np.load(HERE / "eval_bioclip-2.npz")
    W = torch.nn.Parameter(torch.tensor(head["W"], device="cuda", dtype=torch.float32))
    b = torch.nn.Parameter(torch.tensor(head["b"], device="cuda", dtype=torch.float32))
    scale = torch.nn.Parameter(torch.tensor(float(head["scale"]), device="cuda"))
    counts = torch.bincount(torch.tensor(labels), minlength=len(T)).float().cuda()
    cw = counts.clamp(min=1) ** -0.5
    cw = cw / cw[torch.tensor(labels, device="cuda")].mean()

    dl = DataLoader(Photos(paths, labels, train_tf), batch_size=a.bs, shuffle=True, num_workers=10,
                    pin_memory=True, persistent_workers=True, drop_last=True)
    vdl = DataLoader(Photos([str(SORT / "images_train" / f"{idx['photos'][i]['id']}.jpg") for i in va],
                            [int(y[i]) for i in va], pre), batch_size=256, num_workers=10, persistent_workers=True)
    opt = torch.optim.AdamW([{"params": backbone, "lr": a.lr, "weight_decay": 0.05},
                             {"params": [W, b, scale], "lr": 5e-4, "weight_decay": 0.0}])
    total = a.epochs * len(dl)
    warm = 300
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / total))))

    def evaluate():
        visual.eval()
        right1 = right5 = n = 0
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            for x, t in vdl:
                e = F.normalize(visual(x.cuda(non_blocking=True)).float(), dim=-1)
                logits = scale * e @ F.normalize(W, dim=-1).T + b
                top = logits.topk(5, dim=1).indices.cpu()
                right1 += (top[:, 0] == t).sum().item()
                right5 += (top == t[:, None]).any(1).sum().item()
                n += len(t)
        visual.train()
        return right1 / n, right5 / n

    v1, v5 = evaluate()
    print(f"before fine-tuning: val top-1 {v1:.1%} top-5 {v5:.1%}", flush=True)
    best = v1
    out = HERE / "model" / "bioclip-2-ft_visual.pt"
    step, t0 = 0, time.time()
    visual.train()
    for ep in range(a.epochs):
        run_loss = 0.0
        for k, (x, t) in enumerate(dl):
            x, t = x.cuda(non_blocking=True), t.cuda(non_blocking=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                e = F.normalize(visual(x).float(), dim=-1)
            logits = scale * e @ F.normalize(W, dim=-1).T + b
            loss = F.cross_entropy(logits, t, weight=cw, label_smoothing=0.1)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(backbone, 1.0)
            opt.step()
            sched.step()
            step += 1
            run_loss += loss.item()
            if k % 200 == 0:
                rate = step * a.bs / (time.time() - t0)
                left = (total - step) * a.bs / rate / 60
                print(f"epoch {ep + 1} step {k}/{len(dl)} loss {run_loss / (k + 1):.3f}  {rate:.0f} img/s  "
                      f"~{left:.0f} min left", flush=True)
        v1, v5 = evaluate()
        print(f"== epoch {ep + 1}: val top-1 {v1:.1%} top-5 {v5:.1%}", flush=True)
        if v1 > best:
            best = v1
            torch.save({k: v.half() for k, v in visual.state_dict().items()}, out)
            print(f"   saved (best so far)", flush=True)
    print(f"done; best val top-1 {best:.1%}", flush=True)


if __name__ == "__main__":
    main()

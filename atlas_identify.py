"""Identify engine for ArborID: photo(s) + location -> ranked atlas species with percentages.

Runs fully offline on the CPU:
  * image model: BioCLIP image encoder (ONNX, int8) + a species head trained on ~160,000 ALA photos
    (experiments/photo-sort/identify/), with a temperature fitted so the percentages are calibrated;
  * location: each species' native wild ALA records on a 0.1-degree grid; species with records near
    the photo's GPS point are favoured, species with none nearby are strongly down-weighted (not
    removed, because records are incomplete);
  * several photos of the same plant are combined (damped product of the per-photo probabilities).

Model files live in model/ (see model/identify_config.json for the fitted constants).
"""
import base64
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import ExifTags, Image, ImageOps

MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


def views(img):
    """The whole photo, not just its centre: centre square, padded to a square, squashed to a square,
    and squares at both ends of the long side (top/bottom or left/right). Their embeddings are averaged."""
    img = img.convert("RGB")
    w, h = img.size
    s, m = max(w, h), min(w, h)
    pad = Image.new("RGB", (s, s), tuple(int(v * 255) for v in MEAN))
    pad.paste(img, ((s - w) // 2, (s - h) // 2))
    if h >= w:
        a, b = img.crop((0, 0, w, m)), img.crop((0, h - m, w, h))
    else:
        a, b = img.crop((0, 0, m, h)), img.crop((w - m, 0, w, h))
    return [img, pad, img.resize((224, 224), Image.BICUBIC), a, b]


def month_of(taken):
    """'2026:05:24 09:14:00' -> 5"""
    try:
        m = int(str(taken)[5:7])
        return m if 1 <= m <= 12 else None
    except (TypeError, ValueError):
        return None


def preprocess(img, size=224):
    """open_clip eval transform: resize shortest side (bicubic), centre crop, CLIP normalise."""
    img = img.convert("RGB")
    w, h = img.size
    s = size / min(w, h)
    img = img.resize((max(size, round(w * s)), max(size, round(h * s))), Image.BICUBIC)
    w, h = img.size
    left, top = (w - size) // 2, (h - size) // 2
    img = img.crop((left, top, left + size, top + size))
    a = (np.asarray(img, dtype=np.float32) / 255.0 - MEAN) / STD
    return a.transpose(2, 0, 1)


def exif_info(img):
    """(lat, lon, taken) from EXIF, any of which may be None."""
    try:
        exif = img.getexif()
    except Exception:
        return None, None, None
    taken = None
    try:
        taken = exif.get_ifd(ExifTags.IFD.Exif).get(36867) or exif.get(306)
    except Exception:
        pass
    try:
        gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if gps and 2 in gps and 4 in gps:
            def deg(v, ref):
                d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
                return -d if str(ref).upper().startswith(("S", "W")) else d
            lat, lon = deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E"))
            if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0.0, 0.0):
                return lat, lon, taken
    except Exception:
        pass
    return None, None, taken


class Identifier:
    def __init__(self, model_dir):
        self.dir = Path(model_dir)
        self._ready = False

    def available(self):
        return (self.dir / "identify_config.json").exists()

    def _load(self):
        if self._ready:
            return
        import onnxruntime as ort
        cfg = json.loads((self.dir / "identify_config.json").read_text(encoding="utf-8"))
        self.cfg = cfg
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(self.dir / cfg["onnx"]), opts, providers=["CPUExecutionProvider"])
        head = np.load(self.dir / cfg["head"])
        self.W = head["W"].astype(np.float32)
        self.b = head["b"].astype(np.float32)
        self.scale = float(head["scale"])
        self.species = json.loads((self.dir / "species.json").read_text(encoding="utf-8"))
        g = np.load(self.dir / "grid.npz")
        self.g_sp, self.g_lat, self.g_lon, self.g_n = g["sp"], g["lat"], g["lon"], g["n"].astype(np.float64)
        self.states = {s: set(v) for s, v in json.loads((self.dir / "states.json").read_text()).items()}
        self.months = None
        if (self.dir / "months.npy").exists() and cfg.get("season"):
            M = np.load(self.dir / "months.npy").astype(np.float64)        # [species, 12] native records by month
            M = M + 0.5 * (np.roll(M, 1, 1) + np.roll(M, -1, 1))           # early June is near May too
            self.months, self.month_share = M, M.sum(0) / M.sum()
        self._ready = True

    def season_logprior(self, month):
        """Favour species recorded in the photo's month (light weight: it helped only a little in testing)."""
        c = self.cfg["season"]
        M, q = self.months, self.month_share
        p = (M[:, month - 1] + c["alpha"] * q[month - 1]) / (M.sum(1) + c["alpha"])
        return c["beta"] * np.log(p / q[month - 1])

    # ------------------------------------------------------------------ pieces
    def photo_logprobs(self, images):
        whole = self.cfg.get("whole_photo", False)
        per = [views(im) if whole else [im] for im in images]
        x = np.stack([preprocess(v) for vs in per for v in vs]).astype(np.float32)
        emb = self.session.run(None, {"pixels": x})[0].reshape(len(images), len(per[0]), -1).mean(1)
        emb /= np.linalg.norm(emb, axis=1, keepdims=True)
        logits = (self.scale * emb @ self.W.T + self.b) / self.cfg["temperature"]
        logits -= logits.max(1, keepdims=True)
        return logits - np.log(np.exp(logits).sum(1, keepdims=True))

    def location_logprior(self, lat, lon):
        """Log prior over species from native records near (lat, lon); also returns record counts."""
        c = self.cfg["location"]
        dlat = (self.g_lat / 10.0 - lat) * 111.0
        dlon = (self.g_lon / 10.0 - lon) * 111.0 * math.cos(math.radians(lat))
        d = np.sqrt(dlat ** 2 + dlon ** 2)
        n = len(self.species)
        near = np.bincount(self.g_sp[d <= c["near_km"]], self.g_n[d <= c["near_km"]], minlength=n)
        wide = np.bincount(self.g_sp[d <= c["wide_km"]], self.g_n[d <= c["wide_km"]], minlength=n)
        score = near + c["wide_weight"] * wide
        prior = np.where(score > 0, c["gamma"] * np.log(score + 1.0), math.log(c["absent"]))
        return prior - np.log(np.exp(prior - prior.max()).sum()) - prior.max(), near.astype(int)

    def state_logprior(self, state):
        c = self.cfg["location"]
        inside = np.array([state in self.states.get(s["sci"], ()) for s in self.species])
        prior = np.where(inside, 0.0, math.log(c["absent"]))
        return prior - np.log(np.exp(prior).sum())

    # ------------------------------------------------------------------ main entry
    def identify(self, images, lat=None, lon=None, state=None, month=None, top=10):
        """images: list of PIL images (EXIF already read). Returns ranked species with percentages."""
        self._load()
        per_photo = self.photo_logprobs(images)
        damp = self.cfg["multi_photo_damping"] if len(images) > 1 else 1.0
        logp = damp * per_photo.sum(0)
        if month and self.months is not None:
            logp = logp + self.season_logprior(month)
        counts = None
        if lat is not None and lon is not None:
            prior, counts = self.location_logprior(lat, lon)
            logp = logp + prior
        elif state:
            logp = logp + self.state_logprior(state)
        logp -= logp.max()
        p = np.exp(logp)
        p /= p.sum()
        order = np.argsort(-p)[:top]
        out = []
        for i in order:
            s = self.species[i]
            out.append({"sci": s["sci"], "common": s["common"], "genus": s["genus"], "family": s["family"],
                        "pct": round(float(p[i]) * 100, 1),
                        "nearby": None if counts is None else int(counts[i])})
        # genus-level summary: often more reliable than the exact species
        genus = {}
        for i in np.argsort(-p)[:300]:
            g = self.species[i]["genus"]
            genus[g] = genus.get(g, 0.0) + float(p[i])
        genera = [{"genus": g, "pct": round(v * 100, 1)}
                  for g, v in sorted(genus.items(), key=lambda kv: -kv[1])[:4]]
        return {"results": out, "genera": genera, "near_km": self.cfg["location"]["near_km"]}


def decode_data_url(data_url):
    """'data:image/jpeg;base64,...' -> PIL image with EXIF orientation applied, plus EXIF info."""
    raw = base64.b64decode(data_url.split(",", 1)[1])
    img = Image.open(io.BytesIO(raw))
    lat, lon, taken = exif_info(img)
    img = ImageOps.exif_transpose(img)
    img.load()
    return img, lat, lon, taken

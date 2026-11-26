"""Extra training photos for species with few ALA field photos (identification only, not the app's sections).

Sources, for species with fewer than RARE field photos in full_results.jsonl:
  * iNaturalist research-grade observations (worldwide) via GBIF, CC0 / CC BY / CC BY-NC only;
  * ALA photo records that the native-range filter left out (planted, outside native states,
    flagged introduced) -- still the right species, so still useful for recognising it.
Herbarium sheets are skipped (already well covered). Up to 2 photos per observation; each species
is topped up to TARGET field photos. Near-duplicates of existing photos are removed later (train.py).

  python identify/fetch_extra.py
Writes identify/extra.jsonl (one row per photo) and downloads into images_extra/  (resumable).
"""
import collections
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SORT = HERE.parent
sys.path.insert(0, str(SORT))
from trial import load_js, APP  # noqa: E402

OUT = HERE / "extra.jsonl"
IMAGES = SORT / "images_extra"
UA = {"User-Agent": "AusTreeAtlas/1.0 (personal botanical desktop app)"}
INAT_DATASET = "50c9509d-22c7-4a22-a47d-8c48425ef4a7"
RARE, TARGET, PER_OBS = 30, 60, 2


def get_json(url, tries=4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return json.load(r)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def inat_photos(sci, want):
    m = get_json("https://api.gbif.org/v1/species/match?" + urllib.parse.urlencode({"name": sci, "kingdom": "Plantae"}))
    key = m.get("acceptedUsageKey") or m.get("usageKey")
    if not key or m.get("matchType") == "NONE" or m.get("rank") not in ("SPECIES", "SUBSPECIES", "VARIETY"):
        return []
    out = []
    for offset in range(0, 900, 300):
        d = get_json(f"https://api.gbif.org/v1/occurrence/search?taxonKey={key}&datasetKey={INAT_DATASET}"
                     f"&mediaType=StillImage&limit=300&offset={offset}")
        for o in d.get("results", []):
            k = 0
            for med in o.get("media", []):
                url, lic = med.get("identifier"), med.get("license") or o.get("license") or ""
                if not url or med.get("type") != "StillImage" or k >= PER_OBS:
                    continue
                if not re.search(r"publicdomain|/by/|/by-nc/|CC0|CC_BY", lic, re.I):
                    continue
                k += 1
                url = url.replace("/original.", "/medium.")
                pid = "inat-" + re.sub(r"\W", "", url.split("/photos/")[-1].split("/")[0]) if "/photos/" in url else None
                if pid:
                    out.append({"id": pid, "url": url, "by": med.get("rightsHolder") or med.get("creator")
                                or o.get("recordedBy") or "iNaturalist user", "lic": lic, "src": "iNaturalist (GBIF)",
                                "obs": o.get("key"), "month": o.get("month")})
            if len(out) >= want:
                return out[:want]
        if d.get("endOfRecords"):
            break
    return out[:want]


def ala_unfiltered(sp, want, known):
    params = [("q", f'lsid:"{sp["guid"]}"'), ("fq", "multimedia:Image"), ("fq", "-basisOfRecord:PRESERVED_SPECIMEN"),
              ("fq", "-dataResourceName:*AVH*"), ("pageSize", 100)]
    d = get_json("https://biocache-ws.ala.org.au/ws/occurrences/search?" + urllib.parse.urlencode(params))
    out = []
    for o in d.get("occurrences", []):
        lic = o.get("license") or ""
        if not re.search(r"CC|public|PD", lic, re.I):
            continue
        who = ((o.get("recordedBy") or o.get("collectors") or [None])[0]) or o.get("dataResourceName") or "Unknown"
        for img in (o.get("images") or [o.get("image")])[:PER_OBS]:
            if img and img not in known:
                known.add(img)
                i = img
                out.append({"id": img, "by": who, "lic": lic, "src": "ALA (outside native filter)",
                            "url": f"https://images-assets.ala.org.au/store/{i[-1]}/{i[-2]}/{i[-3]}/{i[-4]}/{i}/thumbnail",
                            "month": o.get("month")})
        if len(out) >= want:
            break
    return out[:want]


def download(p):
    dest = IMAGES / f"{p['id']}.jpg"
    if dest.exists():
        return True
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(p["url"], headers=UA), timeout=60) as r:
                data = r.read()
            if len(data) > 500:
                dest.write_bytes(data)
                return True
        except Exception:
            time.sleep(1 + attempt)
    return False


def main():
    IMAGES.mkdir(exist_ok=True)
    ala = load_js(APP / "data" / "ala_species.js", "ALA_SPECIES")
    field, known = collections.Counter(), set()
    for line in (SORT / "full_results.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        for p in r["photos"]:
            known.add(p["id"])
            if "herbarium" not in p["src"].lower() and "avh" not in p["src"].lower():
                field[r["sci"]] += 1
    done = set()
    if OUT.exists():
        done = {json.loads(l)["sci"] for l in OUT.read_text(encoding="utf-8").splitlines()}
    todo = [s for s in ala if field[s["sci"]] < RARE and s["sci"] not in done]
    print(f"{len(todo)} species to top up", flush=True)

    def work(sp):
        want = TARGET - field[sp["sci"]]
        try:
            photos = ala_unfiltered(sp, want, set(known))
            photos += inat_photos(sp["sci"], want)
        except Exception as e:
            return sp["sci"], None, str(e)
        with ThreadPoolExecutor(6) as ex:
            ok = list(ex.map(download, photos))
        return sp["sci"], [p for p, k in zip(photos, ok) if k], None

    n_photos = 0
    with OUT.open("a", encoding="utf-8") as f, ThreadPoolExecutor(8) as ex:
        for n, (sci, photos, err) in enumerate(ex.map(work, todo), 1):
            if err:
                print("failed", sci, err, flush=True)
                continue
            f.write(json.dumps({"sci": sci, "photos": photos}) + "\n")
            f.flush()
            n_photos += len(photos)
            if n % 100 == 0:
                print(f"{n}/{len(todo)} species, {n_photos} photos", flush=True)
    print("done", n_photos, "photos", flush=True)


if __name__ == "__main__":
    main()

"""Import real species from the Atlas of Living Australia (ALA) into AusTree Atlas.

For every genus listed in the app's FAMILIES_SCHEMA:
  * all accepted species with >= MIN_RECORDS ALA occurrence records (BIE search)
  * the states/territories each species is recorded in (biocache facets)
  * one openly-licensed thumbnail photo + credit (ALA image service)

Writes app/data/ala_species.js (window.ALA_SPECIES) and app/photos/ala/*.jpg.
Network responses are cached in tools/cache/, so re-runs are fast and resumable.
"""
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MIN_RECORDS = 50           # "well-recorded" threshold chosen by the user
MIN_STATE_RECORDS = 5      # records needed before a state counts as part of the range
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "tools" / "cache"
PHOTO_DIR = ROOT / "app" / "photos" / "ala"
OUT = ROOT / "app" / "data" / "ala_species.js"
UA = {"User-Agent": "AusTreeAtlas/1.0 (personal botanical desktop app)"}

STATES = {
    "New South Wales": "NSW", "Victoria": "VIC", "Queensland": "QLD",
    "Western Australia": "WA", "South Australia": "SA", "Tasmania": "TAS",
    "Northern Territory": "NT", "Australian Capital Territory": "ACT",
}
NAME_OK = re.compile(r"^[A-Z][a-z]+ [a-z][a-z-]+$")  # drops hybrids, phrase names, "sp."


def fetch(url, binary=False, retries=4):
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + (".bin" if binary else ".json"))
    if key.exists():
        return key.read_bytes() if binary else json.loads(key.read_text(encoding="utf-8"))
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            key.write_bytes(data)
            return data if binary else json.loads(data)
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def app_genera():
    html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
    block = html[html.index("const FAMILIES_SCHEMA"):html.index("const ALL_STATES")]
    names = []
    for arr in re.findall(r"genera:\s*\[([^\]]*)\]", block):
        for g in re.findall(r'"([^"]+)"', arr):
            g = g.split()[0]  # "Casuarina fontana" -> "Casuarina"
            if g not in names:
                names.append(g)
    return names


def species_for_genus(genus):
    out, start = [], 0
    while True:
        q = urllib.parse.urlencode([
            ("q", "*:*"), ("fq", "idxtype:TAXON"), ("fq", "rank:species"),
            ("fq", f"rk_genus:{genus}"), ("fq", "taxonomicStatus:accepted"),
            ("pageSize", 500), ("start", start),
        ])
        r = fetch(f"https://bie-ws.ala.org.au/ws/search.json?{q}")["searchResults"]
        out += r["results"]
        start += 500
        if start >= r["totalRecords"]:
            return out


def states_for_genus(genus):
    """{species name: [state codes]} using one facet query per state."""
    result = {}
    for label, code in STATES.items():
        q = urllib.parse.urlencode([
            ("q", f"genus:{genus}"), ("fq", f'stateProvince:"{label}"'),
            ("facets", "species"), ("flimit", -1), ("pageSize", 0),
        ])
        d = fetch(f"https://biocache-ws.ala.org.au/ws/occurrences/search?{q}")
        for f in d.get("facetResults", []):
            for x in f["fieldResult"]:
                if x["count"] >= MIN_STATE_RECORDS:
                    result.setdefault(x["label"], []).append(code)
    return result


def photo_for(image_id):
    meta = fetch(f"https://images.ala.org.au/ws/image/{image_id}")
    lic = (meta.get("recognisedLicence") or {}).get("acronym") or ""
    if not (lic.startswith("CC") or "public" in lic.lower()):
        return None
    dest = PHOTO_DIR / f"{image_id}.jpg"
    if not dest.exists():
        dest.write_bytes(fetch(f"https://images.ala.org.au/image/{image_id}/thumbnail", binary=True))
    who = meta.get("creator") or meta.get("rightsHolder") or "Unknown"
    return {
        "file": f"photos/ala/{image_id}.jpg",
        "large": f"https://images.ala.org.au/image/{image_id}/large",
        "attr": f"© {who}",
        "license": lic,
        "via": "Atlas of Living Australia",
    }


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    genera = app_genera()
    print(f"{len(genera)} genera", flush=True)
    records = []
    for g in genera:
        sp = [s for s in species_for_genus(g)
              if (s.get("occurrenceCount") or 0) >= MIN_RECORDS and NAME_OK.match(s["scientificName"])
              and s.get("kingdom") == "Plantae"]  # e.g. Ficus is also a sea-snail genus
        states = states_for_genus(g) if sp else {}
        for s in sp:
            records.append({
                "sci": s["scientificName"],
                "common": s.get("commonNameSingle") or "",
                "family": s.get("family") or "",
                "genus": s.get("genus") or g,
                "states": sorted(states.get(s["scientificName"], [])),
                "occ": s["occurrenceCount"],
                "guid": s.get("guid") or "",
                "imageId": s.get("image") or "",
            })
        print(f"  {g:16} {len(sp):4} species", flush=True)

    # de-duplicate (a name can appear under two genus queries)
    seen, uniq = set(), []
    for r in records:
        if r["sci"] not in seen:
            seen.add(r["sci"]); uniq.append(r)
    print(f"{len(uniq)} species total; fetching photos...", flush=True)

    def work(r):
        try:
            r["photo"] = photo_for(r["imageId"]) if r["imageId"] else None
        except Exception as e:
            r["photo"] = None
            print(f"  photo error {r['sci']}: {e}", flush=True)
        return r

    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, _ in enumerate(pool.map(work, uniq), 1):
            if i % 100 == 0:
                print(f"  photos {i}/{len(uniq)}", flush=True)

    for r in uniq:
        r.pop("imageId", None)
    OUT.write_text(
        "// Generated by tools/fetch_ala.py from the Atlas of Living Australia (ala.org.au)\n"
        f"// Species with >= {MIN_RECORDS} records in the app's genera. Photo credits per record.\n"
        "window.ALA_SPECIES = " + json.dumps(uniq, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    n_photo = sum(1 for r in uniq if r["photo"])
    print(f"DONE: {len(uniq)} species, {n_photo} with photos -> {OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())

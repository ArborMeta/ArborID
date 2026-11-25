"""List the AusTree Atlas species with native ALA records near a photo's GPS location.

Used to narrow down candidates when identifying a tree from a photo.

  python tools/nearby_species.py photo.jpg            (reads GPS from the photo's EXIF)
  python tools/nearby_species.py --lat -35.3 --lon 149.1
  options: --radius 25   (km, default 25; widened automatically if few records)

Prints species from the app's 3,923 that have native (not cultivated/introduced) records
within the radius, most records first, with their genus and family.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
UA = {"User-Agent": "AusTreeAtlas/1.0 (personal botanical desktop app)"}
STATE_CODES = {"New South Wales": "NSW", "Victoria": "VIC", "Queensland": "QLD", "South Australia": "SA",
               "Western Australia": "WA", "Tasmania": "TAS", "Northern Territory": "NT",
               "Australian Capital Territory": "ACT"}
BASE_FQ = 'country:"Australia" AND -degreeOfEstablishment:"cultivated" AND -establishmentMeans:"introduced"'


def load_js(path, var):
    s = path.read_text(encoding="utf-8")
    s = s[s.index("=", s.index("window." + var)) + 1:]
    return json.loads(s[:s.rindex(";")])


def gps_from_photo(path):
    from PIL import Image
    exif = Image.open(path).getexif()
    gps = exif.get_ifd(0x8825)
    if not gps or 2 not in gps or 4 not in gps:
        return None

    def deg(v, ref):
        d = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
        return -d if ref in ("S", "W") else d
    when = exif.get_ifd(0x8769).get(36867) or exif.get(306)
    return deg(gps[2], gps.get(1, "N")), deg(gps[4], gps.get(3, "E")), when


def nearby(lat, lon, radius):
    params = [("q", "*:*"), ("lat", lat), ("lon", lon), ("radius", radius), ("fq", BASE_FQ),
              ("fq", "kingdom:Plantae"), ("fq", "-basisOfRecord:LIVING_SPECIMEN"),
              ("fq", '-dataResourceName:"Records of the Australian National Botanic Gardens Seedbank"'),
              ("facets", "species,stateProvince"), ("flimit", -1), ("pageSize", 0)]
    url = "https://biocache-ws.ala.org.au/ws/occurrences/search?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        data = json.load(r)
    counts, states = {}, {}
    for f in data.get("facetResults", []):
        for fr in f["fieldResult"]:
            (counts if f["fieldName"] == "species" else states)[fr["label"]] = fr["count"]
    return counts, max(states, key=states.get) if states else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", nargs="?")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--radius", type=float, default=25)
    a = ap.parse_args()

    lat, lon, when = a.lat, a.lon, None
    if a.photo:
        g = gps_from_photo(a.photo)
        if not g:
            sys.exit("No GPS location in this photo's metadata. Give --lat and --lon instead.")
        lat, lon, when = g
    if lat is None or lon is None:
        sys.exit("Give a photo with GPS data, or --lat and --lon.")

    species = {s["sci"]: s for s in load_js(APP / "data" / "ala_species.js", "ALA_SPECIES")}
    ranges = load_js(APP / "data" / "native_ranges.js", "NATIVE_RANGES")
    radius, dropped = a.radius, []
    while True:
        counts, state = nearby(lat, lon, radius)
        code = STATE_CODES.get(state)
        hits, dropped = [], []
        for sci, n in counts.items():
            if sci not in species:
                continue
            native = (ranges.get(sci) or {}).get("states") or species[sci].get("states") or []
            (hits if not code or code in native else dropped).append((n, sci))
        hits.sort(reverse=True)
        if len(hits) >= 15 or radius >= 100:
            break
        radius *= 2

    print(f"Location: {lat:.5f}, {lon:.5f}" + (f"   taken: {when}" if when else ""))
    print(f"State: {state}.  {len(hits)} AusTree Atlas species native to it with wild records within {radius:g} km")
    print(f"({len(dropped)} more have records here but are not native to {state}, so are likely planted: excluded)")
    genera = {}
    for n, sci in hits:
        genera[species[sci]["genus"]] = genera.get(species[sci]["genus"], 0) + 1
    print("by genus:", ", ".join(f"{g} {c}" for g, c in sorted(genera.items(), key=lambda x: -x[1])))
    print()
    for n, sci in hits:
        s = species[sci]
        print(f"{n:6d}  {sci:42s} {s.get('common') or '':34s} {s['family']}")


if __name__ == "__main__":
    main()

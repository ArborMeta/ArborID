"""Pack grid.jsonl into model/grid.npz (species index, lat*10, lon*10, record count per 0.1-degree cell)
and model/species.json / model/states.json for the app.   python identify/build_grid.py
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MODEL = HERE / "model"


def main():
    MODEL.mkdir(exist_ok=True)
    idx = json.loads((HERE / "emb" / "index.json").read_text(encoding="utf-8"))
    species = idx["species"]
    sp_i = {s["sci"]: i for i, s in enumerate(species)}
    sp, lat, lon, n = [], [], [], []
    for line in (HERE / "grid.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        i = sp_i[r["sci"]]
        for cell, c in r["cells"].items():
            if "," not in cell:   # "Not supplied" = records without coordinates
                continue
            a, b = cell.split(",")
            sp.append(i); lat.append(round(float(a) * 10)); lon.append(round(float(b) * 10)); n.append(c)
    np.savez_compressed(MODEL / "grid.npz", sp=np.array(sp, np.uint16), lat=np.array(lat, np.int16),
                        lon=np.array(lon, np.int16), n=np.array(n, np.uint32))
    (MODEL / "species.json").write_text(json.dumps(species, ensure_ascii=False), encoding="utf-8")

    # native states (for photos without GPS): WCVP ranges, else states with records
    app = HERE.parent.parent.parent / "app" / "data"

    def load_js(p, var):
        s = p.read_text(encoding="utf-8")
        s = s[s.index("=", s.index("window." + var)) + 1:]
        return json.loads(s[:s.rindex(";")])
    ala = {s["sci"]: s for s in load_js(app / "ala_species.js", "ALA_SPECIES")}
    ranges = load_js(app / "native_ranges.js", "NATIVE_RANGES")
    states = {s["sci"]: (ranges.get(s["sci"]) or {}).get("states") or ala[s["sci"]].get("states") or []
              for s in species}
    (MODEL / "states.json").write_text(json.dumps(states), encoding="utf-8")

    # native wild records by month (season step), from fetch_months.py
    months_file = HERE / "months.jsonl"
    if months_file.exists():
        rows = {json.loads(l)["sci"]: json.loads(l)["months"]
                for l in months_file.read_text(encoding="utf-8").splitlines()}
        np.save(MODEL / "months.npy", np.array([rows.get(s["sci"], [0] * 12) for s in species], np.uint32))
    print(f"{len(sp)} cells, grid.npz {(MODEL / 'grid.npz').stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

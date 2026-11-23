"""Check ACT nativeness against the Australian Plant Census (APC).

WCVP treats the ACT as part of NSW, so fetch_native.py marks every NSW-native
species as ACT-native. For species that also have ACT records on ALA (listed in
tools/act_candidates.json), this asks the APC, which lists the ACT separately,
and removes "ACT" from app/data/native_ranges.js when the APC doesn't list it as native.

The APC server is slow (30-60 s per request), so this runs a few requests at a
time and caches each answer in tools/cache/ (safe to stop and re-run).
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_ala

ROOT = Path(__file__).resolve().parent.parent
RANGES = ROOT / "app" / "data" / "native_ranges.js"


def apc_distribution(guid):
    """Return the APC distribution text, e.g. 'SA, Qld, NSW, ACT, Vic, Tas'."""
    tail = guid.split("id.biodiversity.org.au/")[-1]          # node/apni/2897845 or taxon/apni/...
    url = f"https://biodiversity.org.au/nsl/services/rest/{tail}"
    import urllib.request, hashlib
    key = fetch_ala.CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if key.exists():
        data = json.loads(key.read_text(encoding="utf-8"))
    else:
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={**fetch_ala.UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=240) as r:
                    raw = r.read()
                data = json.loads(raw)
                key.write_bytes(raw)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(10)
    profile = (data.get("treeElement") or {}).get("profile") or {}
    return (profile.get("APC Dist.") or {}).get("value")


def act_is_native(dist):
    for token in dist.split(","):
        token = token.strip()
        if token.startswith("ACT"):
            return not any(w in token.lower() for w in ("naturalised", "formerly", "doubtfully", "introduced"))
    return False


def main():
    candidates = json.loads((ROOT / "tools" / "act_candidates.json").read_text(encoding="utf-8"))
    print(f"{len(candidates)} species to check", flush=True)
    verdict = {}

    def work(item):
        sci, guid = item
        try:
            dist = apc_distribution(guid)
            return sci, (act_is_native(dist) if dist else None), dist
        except Exception as e:
            return sci, None, f"error: {e}"

    with ThreadPoolExecutor(max_workers=3) as pool:
        for i, (sci, ok, dist) in enumerate(pool.map(work, candidates), 1):
            verdict[sci] = ok
            print(f"[{i}/{len(candidates)}] {sci}: ACT native={ok}  ({dist})", flush=True)

    s = RANGES.read_text(encoding="utf-8")
    head, body = s[:s.index("window.NATIVE_RANGES")], s[s.index("=", s.index("window.NATIVE_RANGES")) + 1:]
    ranges = json.loads(body[:body.rindex(";")])
    # Keep ACT only where the APC confirms it (species with few ACT records
    # were not checked, so their ACT status is unconfirmed and dropped too).
    removed = 0
    for sci, rng in ranges.items():
        if "ACT" in rng["states"] and verdict.get(sci) is not True and verdict.get(sci, False) is not None:
            rng["states"].remove("ACT")
            removed += 1
    RANGES.write_text(head.replace("ACT counted native wherever NSW is.",
                                   "ACT kept only where the Australian Plant Census (APC) lists it as native.")
                      + "window.NATIVE_RANGES = " + json.dumps(ranges, ensure_ascii=False, separators=(",", ":")) + ";\n",
                      encoding="utf-8")
    unknown = sum(1 for v in verdict.values() if v is None)
    print(f"DONE: ACT removed for {removed} species; {unknown} could not be checked (left as is)", flush=True)


if __name__ == "__main__":
    main()

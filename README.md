# AusTree Atlas

A Windows desktop field guide to Australian trees and woody plants: **3,923 native species** with photos, native ranges, and live distribution maps drawn from the [Atlas of Living Australia](https://www.ala.org.au/).

## Identify a plant from photos

Works offline. Add one or more photos of the same plant and the app ranks the most likely atlas species, each with a percentage. It reads the GPS location in the photos and favours species with native records within about 25 km (some weight out to 50 km). Without GPS, you can pick the state instead.

On test photos it hadn't seen, with location:

- the first guess was right 63% of the time;
- the right species was in the top 5 83% of the time;
- the genus was right 86% of the time.

The percentages are calibrated: an "85%" was right about 85% of the time. The model is BioCLIP-2, trained on about 160,000 ALA photos.

## Features

- **Browse and search** 3,923 species from 91 genera, including *Eucalyptus*, *Acacia*, *Banksia*, *Ficus* and *Melaleuca*. Each has at least 50 ALA records.
- **Search by any common name:** 7,761 names from ALA, so "snow gum" finds *Eucalyptus pauciflora* even though its main name is "White Sally". Best matches come first, and the card says which name matched.
- **Filter** by family, genus, native state, bark, foliage and habitat, or jump by letter.
- **Offline photos:** 3,749 openly licensed photos are built in, each with its photographer credit.
- **Native ranges** per state, from Kew's World Checklist of Vascular Plants, with the ACT checked against the Australian Plant Census.
- **Species page** (needs internet): a map of native-range records, records by state and month, the Wikipedia description, common names, conservation status and classification.
- **Photos by plant part:** each species page has **Flowers, Fruit & seeds, Leaves, Bark and Tree** sections. They draw on about 162,000 native-range ALA photos, sorted automatically by an image-recognition model (OpenCLIP ViT-H/14, DFN-5B). The Bark section also shows Wikimedia Commons bark photos. About 1,900 species have bark photos.
- **Identify a plant from photos**, offline, with GPS-aware percentages (see [above](#identify-a-plant-from-photos)).
- **Add your own specimens.** You can also export a list as CSV or save a specimen sheet.

## Download

Get **`AusTree Atlas.exe`** from the [Releases](../../releases) page. It's one portable file with nothing to install.

- Needs Windows 10 or 11 (64-bit) with the Microsoft Edge WebView2 Runtime. Windows 11 has it built in.
- The `.exe` isn't digitally signed, so Windows may say "Windows protected your PC". Choose **More info → Run anyway**.
- Specimens you add are saved per user in `%LOCALAPPDATA%\AusTreeAtlas`.

## Build from source

Needs Python 3.12 or newer.

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
build.bat
```

The result is `dist\AusTree Atlas.exe`. To run without building, use `.venv\Scripts\python main.py`.

## Project layout

| Path | What it is |
|---|---|
| `main.py` | Opens `app/index.html` in a native window (pywebview, Edge WebView2) |
| `app/index.html` | The app: species grid, filters, search, specimen tools |
| `app/detail.js` | Species page: map, charts, gallery, bark photos, description |
| `app/identify.js` | Identify window (photos in, ranked species out) |
| `atlas_identify.py` | Identify engine: image model (onnxruntime, CPU), location step, multi-photo combining |
| `model/` | Identify model files. `*.onnx` isn't in git (346 MB, over GitHub's limit): rebuild it, or take it from a release backup |
| `experiments/photo-sort/identify/` | Scripts that build the Identify model (see below) |
| `app/data/ala_species.js` | Species list from ALA, with photo credits |
| `app/data/native_ranges.js` | Native state ranges (WCVP, ACT via APC) |
| `app/data/photo_categories.js` | ALA photo IDs sorted into plant-part sections, with credits |
| `experiments/photo-sort/` | Scripts that sort the photos on a GPU (`full_run.py`, then `build_app_data.py`) |
| `app/photos/` | Bundled photos (`ala/` from ALA; the rest from iNaturalist) |
| `app/vendor/` | Tailwind, Font Awesome, fonts and Leaflet, bundled for offline use |
| `tools/` | Scripts that download and rebuild the data |

## Refreshing the data

Run these from the project folder with `.venv\Scripts\python`:

1. `tools/fetch_ala.py` downloads species, record counts and photos from ALA. It's resumable, and responses are cached in `tools/cache/`.
2. `tools/fetch_native.py` downloads native state ranges from WCVP via the GBIF API.
3. `tools/fetch_act.py` checks ACT status against the Australian Plant Census. It's slow (about 30–60 s per species), so it runs in the background.
4. Optional, to refresh the photo sections: in `experiments/photo-sort`, create a separate venv from its `requirements.txt` (PyTorch with CUDA for an NVIDIA GPU). Then run `full_run.py`, which takes about 1–2 hours on an RTX 4090 and is resumable, followed by `build_app_data.py`.
5. Optional, to rebuild the Identify model: in `experiments/photo-sort` with its venv, run these scripts from `identify/` in order:
   - `download_train.py` (about 10 min, 3 GB of photos)
   - `fetch_grid.py`
   - `embed.py bioclip-2` (about 10 min on a GPU)
   - `build_grid.py`
   - `fetch_coords.py`
   - `train.py bioclip-2 --final`
   - `eval_location.py bioclip-2`
   - `export_onnx.py bioclip-2`

   Then copy `bioclip-2_visual_w8.onnx`, `bioclip-2_head.npz`, `grid.npz`, `species.json` and `states.json` from `identify/model/` into `model/`. Copy `identify_config_bioclip-2.json` there too, renamed to `identify_config.json`.
6. Run `build.bat` to rebuild the `.exe`.

## Data sources and limitations

- Species come from the app's 91 genera, and ALA can't tell trees from shrubs, so many shrubs are included.
- Bark, foliage, habitat and height are filled in only for 30 hand-written key species. Foliage is also inferred where the genus decides it (gums, she-oaks, conifers, fan palms).
- Maps hide records that are overseas, outside the native states, or flagged as cultivated or introduced. Planted trees inside a native state can't always be told apart.
- 238 species have no WCVP entry under the same name, so their state tags show states with records, not a verified native range.
- Photo sections are sorted automatically, so some photos land in the wrong section. A photo showing two parts can appear in both. 241 species have no usable openly licensed photos and show the plain gallery instead.

- Identify works best for well-photographed species with several photos.
  - Exact eucalypts and wattles are often uncertain from one photo, so check buds, fruit and leaves on the species page.
  - Species with few ALA photos (424 have fewer than 5) are recognised mainly from their name and genus, so they're weaker.
  - A plant that isn't in the atlas (a garden plant or a weed) is still matched to its closest atlas species.

See [DATA-LICENSES.md](DATA-LICENSES.md) for credits and licences.

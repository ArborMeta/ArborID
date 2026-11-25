# Data, photo and library licences

The licence for this project's own code covers **only the code**. Bundled photos, data and libraries keep their original licences, which are listed below.

## Photos (`app/photos/`)

- **`app/photos/ala/`:** 3,717 photos from the [Atlas of Living Australia](https://www.ala.org.au/) image service. Each photo's creator and licence are stored in `app/data/ala_species.js` and shown in the app. The licences are Creative Commons (CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA, CC BY-NC-ND) or CC0. **Most are non-commercial (NC)**, so the bundled photos may not be used commercially.
- **`app/photos/*.jpg`:** 32 photos from [iNaturalist](https://www.inaturalist.org/). Each one's credit and licence are in `app/photos/photos.js`.

Photos are credited in the app wherever they're enlarged.

## Species and distribution data

| Data | Source | Licence |
|---|---|---|
| Species names, families, record counts | Atlas of Living Australia, which uses the [Australian Plant Census](https://biodiversity.org.au/nsl/services/search/taxonomy) taxonomy | CC BY 4.0 (ALA) and CC BY 3.0 AU (APC) |
| Native state ranges | [World Checklist of Vascular Plants](https://powo.science.kew.org/), Royal Botanic Gardens, Kew, via the [GBIF](https://www.gbif.org/) API | CC BY |
| ACT native status | Australian Plant Census (APC), Council of Heads of Australasian Herbaria | CC BY 3.0 AU |

## Identify model (`model/`)

- **Image encoder:** [BioCLIP 2](https://huggingface.co/imageomics/bioclip-2) by the Imageomics Institute, MIT licence. It's bundled as an ONNX export with 8-bit weights.
- **Species classifier:** trained on BioCLIP 2 features of about 160,000 ALA photos (credits as above). The classifier stores numbers only, not photos.
- **Location grid (`grid.npz`):** counts of each species' native wild ALA records per 0.1° cell. Atlas of Living Australia, CC BY 4.0.

## Loaded live (not bundled)

The species page fetches these while it's open. They aren't stored in this repository.

- ALA occurrence maps, records and photo gallery: each photo is credited with its licence in the app.
- Plant-part photo sections (Flowers, Fruit & seeds, Leaves, Bark, Tree): `app/data/photo_categories.js` stores only ALA image IDs, photographer names and licences (CC or public domain only). The photos themselves load from images.ala.org.au and stay under their photographers' licences. The sorting was done with OpenCLIP ViT-H-14-378 using Apple's DFN-5B weights; the model is not included in this repository.
- Wikipedia summaries: CC BY-SA 4.0, linked to the source article.
- Wikimedia Commons bark photos: each credited with its author and licence.
- Esri World Topographic Map tiles: © Esri and contributors.

## Bundled libraries (`app/vendor/`)

| Library | Licence |
|---|---|
| Tailwind CSS 3.4.17 (Play CDN script) | MIT |
| Font Awesome Free 6.4.0 | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT |
| Inter, Cinzel, JetBrains Mono (Google Fonts) | SIL Open Font License 1.1 |
| Leaflet 1.9.4 | BSD 2-Clause |

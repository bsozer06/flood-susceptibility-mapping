# Flood Susceptibility Map (mAHP 2015)

The flood susceptibility map is resulted in my academic research: 
- https://isprs-archives.copernicus.org/articles/XLII-5/361/2018/

Converts a flood susceptibility raster produced with the mAHP method
(`data/mAHP_2015_son_dp5_clip.tif`) into an interactive vector web map. The output is a
single static `.pmtiles` file, published on GitHub Pages (over HTTP range requests, with
no tile server required).

## Pipeline

```
clip.tif  ──(1)──>  data/sel.geojson  ──(2)──>  docs/sel.pmtiles  ──(3)──>  GitHub Pages
 (UTM 36N)          (WGS84, class 1-5)          (vector tile)               (MapLibre)
```

### 0. Setup (one-time)
```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# tippecanoe has no native Windows build -> build a local Docker image:
docker build -t tippecanoe-local -f scripts/tippecanoe.Dockerfile .
```

### 1. Classify + polygonize + reproject
`scripts/classify_polygonize.py`:
- Assigns the UTM 36N (EPSG:32636) CRS to the raster (from the `.tfw` + boundary shapefile `.prj`).
- Splits the continuous mAHP values (~3.91–45.93) into 5 classes using **Jenks natural breaks**.
- Removes speckle with `sieve` (merges noise into the neighboring class).
- Polygonizes connected same-class cells and reprojects UTM 36N → WGS84.
- Produces `data/sel.geojson` (each feature has a `class` 1–5) and `data/breaks.json`.

```powershell
.\.venv\Scripts\python scripts/classify_polygonize.py
```

### 2. GeoJSON → PMTiles
`scripts/build_pmtiles.ps1` (Docker tippecanoe):
```powershell
pwsh scripts/build_pmtiles.ps1
```
`-l susceptibility --coalesce --reorder --drop-densest-as-needed -Z6 -z14` →
`docs/sel.pmtiles` (~8.5 MB) + `docs/breaks.json`.

### 3. Publish (GitHub Pages)
- Commit `docs/index.html` + `docs/sel.pmtiles` + `docs/breaks.json`.
- GitHub repo → Settings → Pages → "Deploy from branch" → branch `main`, folder `/docs`.
- GitHub Pages supports HTTP range requests; PMTiles works without a server.
- `sel.pmtiles` is well below GitHub's 100 MB file limit (~8.5 MB).

## Local preview
Python's `http.server` does not support range requests; use a range-capable server:
```powershell
npx serve docs -l 8765
# http://localhost:8765
```

## Map
`docs/index.html` — keyless CARTO basemap + MapLibre + pmtiles (CDN). Colors the classes
green→red by the `class` (1–5) attribute, and builds the legend and `fitBounds` from
`breaks.json`.

## Classes (Jenks, 2015)
| Class | mAHP range   | Meaning   |
|-------|--------------|-----------|
| 1     | 3.91 – 10.75 | Very low  |
| 2     | 10.75 – 16.99 | Low      |
| 3     | 16.99 – 22.02 | Medium   |
| 4     | 22.02 – 28.00 | High     |
| 5     | 28.00 – 45.93 | Very high |

## Notes
- The source raster has no embedded CRS; positioning comes from the `.tfw` world file
  (UTM Zone 36N / EPSG:32636, 10 m pixels, Ankara region).
- `data/sel.geojson` (~80 MB intermediate output) and `.venv/` can be left out of the repo.

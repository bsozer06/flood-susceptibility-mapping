"""
Splits the mAHP flood-susceptibility raster into 5 classes (Jenks natural
breaks), converts it to per-class polygons, reprojects UTM 36N -> WGS84, and
produces sel.geojson + breaks.json for the web map.

Run:
    .venv/Scripts/python.exe scripts/classify_polygonize.py

Input  : data/mAHP_2015_son_dp5_clip.tif  (no embedded CRS; .tfw holds transform)
Output : data/sel.geojson   (EPSG:4326, each feature has `class` 1..5)
         data/breaks.json   (Jenks break values + class ranges + bbox)
"""

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio import Affine, features
from rasterio.crs import CRS
from rasterio.warp import transform_geom
import jenkspy

# --- File paths ---
ROOT = Path(__file__).resolve().parent.parent
SRC_TIF = ROOT / "data" / "mAHP_2015_son_dp5_clip.tif"
OUT_GEOJSON = ROOT / "data" / "sel.geojson"
OUT_BREAKS = ROOT / "data" / "breaks.json"

# --- Parameters -----
SRC_EPSG = 32636          # UTM Zone 36N (WGS84) -- from .tfw + boundary shapefile .prj
DST_EPSG = 4326           # WGS84 lon/lat for the web map
N_CLASSES = 5
SAMPLE_SIZE = 100_000     # number of sample pixels for the Jenks computation
SIEVE_SIZE = 16           # merge regions smaller than this into neighbours (denoise)


def load_valid_band(path: Path) -> tuple[np.ndarray, np.ndarray, Affine, CRS]:
    """Read band 1 as float64 and build the valid-pixel mask.

    Valid pixels are finite, not equal to nodata, and strictly positive
    (mAHP values are positive; 0 and negatives are treated as nodata).
    The source raster has no embedded CRS, so we assign SRC_EPSG ourselves.
    """
    print(f"Opening raster: {path}")
    with rasterio.open(path) as src:
        band = src.read(1).astype("float64")
        transform = src.transform
        nodata = src.nodata
        src_crs = CRS.from_epsg(SRC_EPSG)  # no embedded CRS; we assign it

        valid = np.isfinite(band)
        if nodata is not None:
            valid &= band != nodata
        valid &= band > 0

    return band, valid, transform, src_crs


def compute_jenks_breaks(
    values: np.ndarray, n_classes: int, sample_size: int
) -> list[float]:
    """Compute Jenks natural breaks, sampling if there are many pixels.

    The break endpoints are pinned to the true min/max so out-of-sample
    extremes are still covered.
    """
    if values.size > sample_size:
        rng = np.random.default_rng(42)
        sample = rng.choice(values, size=sample_size, replace=False)
    else:
        sample = values
    breaks = [float(b) for b in jenkspy.jenks_breaks(sample, n_classes=n_classes)]
    breaks[0] = float(values.min())
    breaks[-1] = float(values.max())
    return breaks


def classify(
    band: np.ndarray, valid: np.ndarray, breaks: list[float], n_classes: int
) -> np.ndarray:
    """Reclassify into 1..n_classes (nodata -> 0) using the interior break edges."""
    edges = np.array(breaks[1:-1])  # interior edges
    class_arr = np.zeros(band.shape, dtype="int16")
    class_arr[valid] = np.digitize(band[valid], edges, right=False) + 1
    class_arr[valid] = np.clip(class_arr[valid], 1, n_classes)
    return class_arr


def apply_sieve(class_arr: np.ndarray, valid: np.ndarray, size: int) -> np.ndarray:
    """Merge small connected regions into neighbours to remove speckle.

    Prevents salt-and-pepper noise and excessive fragmentation on the web map.
    Returns the array unchanged when size <= 1.
    """
    if not (size and size > 1):
        return class_arr
    print(f"Applying sieve (min {size} pixels)...")
    sieved = features.sieve(class_arr, size=size, mask=valid)
    counts = {c: int((sieved == c).sum()) for c in range(1, N_CLASSES + 1)}
    print("Class pixel counts after sieve:", counts)
    return sieved


def polygonize(
    class_arr: np.ndarray,
    valid: np.ndarray,
    transform: Affine,
    src_crs: CRS,
    dst_crs: CRS,
) -> tuple[list[tuple[dict, int]], tuple[float, float, float, float]]:
    """Vectorize same-class connected cells, reproject to dst_crs, and track bbox.

    Returns the list of (geometry, class) features and the overall WGS84 bbox.
    """
    features_4326: list[tuple[dict, int]] = []
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for geom, value in features.shapes(class_arr, mask=valid, transform=transform):
        cls = int(value)
        if cls < 1:
            continue
        geom_ll = transform_geom(src_crs, dst_crs, geom)
        features_4326.append((geom_ll, cls))
        # update bbox from the reprojected polygon coordinates
        for ring in geom_ll["coordinates"]:
            arr = np.asarray(ring, dtype="float64")
            minx = min(minx, arr[:, 0].min()); maxx = max(maxx, arr[:, 0].max())
            miny = min(miny, arr[:, 1].min()); maxy = max(maxy, arr[:, 1].max())

    return features_4326, (minx, miny, maxx, maxy)


def write_geojson(path: Path, features_4326: list[tuple[dict, int]]) -> None:
    """Write the per-class polygons as a GeoJSON FeatureCollection."""
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"class": cls}, "geometry": geom}
            for geom, cls in features_4326
        ],
    }
    path.write_text(json.dumps(fc), encoding="utf-8")
    print(f"Wrote: {path}  ({path.stat().st_size / 1e6:.1f} MB)")


def write_breaks(
    path: Path,
    breaks: list[float],
    n_classes: int,
    bbox: tuple[float, float, float, float],
    src_epsg: int,
) -> None:
    """Write the Jenks breaks, class ranges, and bbox (for the legend + map)."""
    ranges = [
        {"class": i + 1, "min": round(breaks[i], 3), "max": round(breaks[i + 1], 3)}
        for i in range(n_classes)
    ]
    path.write_text(
        json.dumps(
            {
                "method": "jenks",
                "n_classes": n_classes,
                "breaks": [round(b, 3) for b in breaks],
                "ranges": ranges,
                "bbox": list(bbox),
                "source_crs": f"EPSG:{src_epsg}",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote: {path}")


def main() -> None:
    band, valid, transform, src_crs = load_valid_band(SRC_TIF)

    n_valid = int(valid.sum())
    if n_valid == 0:
        raise SystemExit("No valid pixels found.")
    vals = band[valid]
    print(f"Valid pixels: {n_valid:,}  ({100 * n_valid / band.size:.1f}%)")
    print(f"Value range : {vals.min():.3f} .. {vals.max():.3f}  mean={vals.mean():.3f}")

    breaks = compute_jenks_breaks(vals, N_CLASSES, SAMPLE_SIZE)
    print("Jenks breaks:", [round(b, 3) for b in breaks])

    class_arr = classify(band, valid, breaks, N_CLASSES)
    counts = {c: int((class_arr == c).sum()) for c in range(1, N_CLASSES + 1)}
    print("Class pixel counts:", counts)

    class_arr = apply_sieve(class_arr, valid, SIEVE_SIZE)

    print("Polygonizing...")
    features_4326, bbox = polygonize(
        class_arr, valid, transform, src_crs, CRS.from_epsg(DST_EPSG)
    )
    print(f"Polygon (feature) count: {len(features_4326):,}")
    print(f"WGS84 bbox: [{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}]")

    write_geojson(OUT_GEOJSON, features_4326)
    write_breaks(OUT_BREAKS, breaks, N_CLASSES, bbox, SRC_EPSG)


if __name__ == "__main__":
    main()

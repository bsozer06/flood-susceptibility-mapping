"""
mAHP sel duyarlilik raster'ini 5 sinifa ayirip (Jenks dogal kirilim),
sinif bazli poligonlara cevirir, UTM 36N -> WGS84 reprojeksiyon yapar
ve web haritasi icin sel.geojson + breaks.json uretir.

Calistirma:
    .venv/Scripts/python.exe scripts/classify_polygonize.py

Girdi : data/mAHP_2015_son_dp5_clip.tif  (CRS gomulu degil; .tfw transform var)
Cikti : data/sel.geojson   (EPSG:4326, her feature'da `class` 1..5)
        data/breaks.json   (Jenks kirilim degerleri + sinif araliklari + bbox)
"""

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio import features
from rasterio.crs import CRS
from rasterio.warp import transform_geom
import jenkspy

# --- File paths ---
ROOT = Path(__file__).resolve().parent.parent
SRC_TIF = ROOT / "data" / "mAHP_2015_son_dp5_clip.tif"
OUT_GEOJSON = ROOT / "data" / "sel.geojson"
OUT_BREAKS = ROOT / "data" / "breaks.json"

# --- Parameters -----
SRC_EPSG = 32636          # UTM Zone 36N (WGS84) -- .tfw + sinir shapefile .prj'den
DST_EPSG = 4326           # Web haritasi icin WGS84 lon/lat
N_CLASSES = 5
SAMPLE_SIZE = 100_000     # Jenks hesabi icin ornek piksel sayisi
SIEVE_SIZE = 16           # Bundan kucuk pikselleri komsuya kat (gurultu temizleme)


def main():
    print(f"Raster is openning: {SRC_TIF}")
    with rasterio.open(SRC_TIF) as src:
        band = src.read(1).astype("float64")
        transform = src.transform
        nodata = src.nodata
        src_crs = CRS.from_epsg(SRC_EPSG)  # gomulu CRS yok, biz atiyoruz

        # Gecerli veri maskesi: nodata ve NaN disi
        valid = np.isfinite(band)
        if nodata is not None:
            valid &= band != nodata
        # mAHP degerleri pozitif; 0 ve negatifleri de nodata say
        valid &= band > 0

    n_valid = int(valid.sum())
    if n_valid == 0:
        raise SystemExit("Gecerli piksel bulunamadi.")
    vals = band[valid]
    print(f"Gecerli piksel: {n_valid:,}  ({100*n_valid/band.size:.1f}%)")
    print(f"Deger araligi : {vals.min():.3f} .. {vals.max():.3f}  ort={vals.mean():.3f}")

    # --- Jenks dogal kirilim (gerekirse orneklem) ---
    if n_valid > SAMPLE_SIZE:
        rng = np.random.default_rng(42)
        sample = rng.choice(vals, size=SAMPLE_SIZE, replace=False)
    else:
        sample = vals
    breaks = jenkspy.jenks_breaks(sample, n_classes=N_CLASSES)
    breaks = [float(b) for b in breaks]
    # Orneklem disi uc degerleri kapsayacak sekilde uclari gercek min/max'a sabitle
    breaks[0] = float(vals.min())
    breaks[-1] = float(vals.max())
    print("Jenks kirilimlari:", [round(b, 3) for b in breaks])

    # --- Yeniden siniflandirma: 1..5 (nodata -> 0) ---
    # np.digitize ile sinif indeksleri (1..N_CLASSES)
    edges = np.array(breaks[1:-1])  # ic kenarlar
    class_arr = np.zeros(band.shape, dtype="int16")
    class_arr[valid] = np.digitize(band[valid], edges, right=False) + 1
    class_arr[valid] = np.clip(class_arr[valid], 1, N_CLASSES)

    counts = {c: int((class_arr == c).sum()) for c in range(1, N_CLASSES + 1)}
    print("Sinif piksel sayilari:", counts)

    # --- Benek (speckle) temizligi: kucuk bagli bolgeleri komsuya kat ---
    # Web haritasinda salt-and-pepper gorunumu ve asiri parcalanmayi onler.
    if SIEVE_SIZE and SIEVE_SIZE > 1:
        print(f"Sieve uygulaniyor (min {SIEVE_SIZE} piksel)...")
        class_arr = features.sieve(class_arr, size=SIEVE_SIZE, mask=valid)
        counts2 = {c: int((class_arr == c).sum()) for c in range(1, N_CLASSES + 1)}
        print("Sieve sonrasi sinif piksel sayilari:", counts2)

    # --- Poligonlastir (bagli ayni-sinif hucreler tek poligona birlesir) ---
    print("Poligonlastiriliyor...")
    geoms_4326 = []
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for geom, value in features.shapes(class_arr, mask=valid, transform=transform):
        cls = int(value)
        if cls < 1:
            continue
        # UTM 36N -> WGS84
        geom_ll = transform_geom(src_crs, CRS.from_epsg(DST_EPSG), geom)
        geoms_4326.append((geom_ll, cls))
        # bbox guncelle (disk poligon koordinatlarindan)
        for ring in geom_ll["coordinates"]:
            arr = np.asarray(ring, dtype="float64")
            minx = min(minx, arr[:, 0].min()); maxx = max(maxx, arr[:, 0].max())
            miny = min(miny, arr[:, 1].min()); maxy = max(maxy, arr[:, 1].max())

    print(f"Poligon (feature) sayisi: {len(geoms_4326):,}")
    print(f"WGS84 bbox: [{minx:.6f}, {miny:.6f}, {maxx:.6f}, {maxy:.6f}]")

    # --- GeoJSON yaz ---
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"class": cls}, "geometry": geom}
            for geom, cls in geoms_4326
        ],
    }
    OUT_GEOJSON.write_text(json.dumps(fc), encoding="utf-8")
    print(f"Yazildi: {OUT_GEOJSON}  ({OUT_GEOJSON.stat().st_size/1e6:.1f} MB)")

    # --- breaks.json yaz (lejant + harita icin) ---
    ranges = [
        {"class": i + 1, "min": round(breaks[i], 3), "max": round(breaks[i + 1], 3)}
        for i in range(N_CLASSES)
    ]
    OUT_BREAKS.write_text(
        json.dumps(
            {
                "method": "jenks",
                "n_classes": N_CLASSES,
                "breaks": [round(b, 3) for b in breaks],
                "ranges": ranges,
                "bbox": [minx, miny, maxx, maxy],
                "source_crs": f"EPSG:{SRC_EPSG}",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Yazildi: {OUT_BREAKS}")


if __name__ == "__main__":
    main()

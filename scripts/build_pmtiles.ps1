# data/sel.geojson -> docs/sel.pmtiles  (Docker uzerinden tippecanoe)
#
# Kullanim:
#   pwsh scripts/build_pmtiles.ps1
#
# tippecanoe Windows'ta native calismaz; yerel Docker imaji ile calistiriyoruz.
# Imaji once derle:
#   docker build -t tippecanoe-local -f scripts/tippecanoe.Dockerfile .
# Imaj .pmtiles ciktiyi dogrudan uretir.

$ErrorActionPreference = "Stop"

# Proje koku (bu script scripts/ altinda)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path "data/sel.geojson")) {
    throw "data/sel.geojson bulunamadi. Once: .venv/Scripts/python.exe scripts/classify_polygonize.py"
}

New-Item -ItemType Directory -Force -Path "docs" | Out-Null

$image = "tippecanoe-local"

Write-Host "tippecanoe calistiriliyor (Docker)..."
docker run --rm -v "${Root}:/work" -w /work $image tippecanoe `
    -o docs/sel.pmtiles --force `
    -l susceptibility `
    --coalesce --reorder `
    --drop-densest-as-needed `
    -Z6 -z14 `
    data/sel.geojson

if ($LASTEXITCODE -ne 0) { throw "tippecanoe basarisiz (exit $LASTEXITCODE)" }

# Lejant/bbox icin breaks.json'i de docs'a kopyala
Copy-Item "data/breaks.json" "docs/breaks.json" -Force

$size = (Get-Item "docs/sel.pmtiles").Length / 1MB
Write-Host ("Tamam: docs/sel.pmtiles ({0:N1} MB)" -f $size)
Write-Host "Decode kontrolu:"
Write-Host "  docker run --rm -v `"${Root}:/work`" -w /work $image tippecanoe-decode docs/sel.pmtiles | Select-Object -First 5"

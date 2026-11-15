"""Serie mensal de superficie de agua (MapBiomas Agua, Landsat 30 m) no bbox da AOI.

Requer conta Google Earth Engine (uma vez):  earthengine authenticate
Uso:
  python scripts/mapbiomas_water_gee.py --project SEU_PROJETO_GCP --list     # lista assets e bandas
  python scripts/mapbiomas_water_gee.py --project SEU_PROJETO_GCP --asset <ID_MENSAL>
Saida bruta: data/raw/mapbiomas/water_monthly_raw.csv (date,water_km2); depois:
  python -m pantanal_sar.mapbiomas data/raw/mapbiomas/water_monthly_raw.csv --collection 5

NAO VERIFICADO: id do asset mensal e valor de pixel de agua (--water-value, padrao 1).
Use --list para conferir antes de confiar nos numeros.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import ee

from pantanal_sar.config import RAW, load_config

FOLDER = "projects/mapbiomas-public/assets/brazil/water/collection5"
BAND_RE = re.compile(r"(\d{4})[_-]?(\d{2})$")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--asset")
    ap.add_argument("--water-value", type=int, default=1)
    ap.add_argument("--scale", type=int, default=30)
    ap.add_argument("--out", default=str(RAW / "mapbiomas" / "water_monthly_raw.csv"))
    a = ap.parse_args()
    ee.Initialize(project=a.project)

    if a.list:
        for x in ee.data.listAssets({"parent": FOLDER}).get("assets", []):
            print(x["id"])
            if a.asset is None:
                continue
        if a.asset:
            print(ee.Image(a.asset).bandNames().getInfo())
        return
    if not a.asset:
        raise SystemExit("Informe --asset (veja --list).")

    img = ee.Image(a.asset)
    bands = img.bandNames().getInfo()
    monthly = {b: BAND_RE.search(b) for b in bands}
    monthly = {b: m for b, m in monthly.items() if m}
    if not monthly:
        raise SystemExit(f"Nenhuma banda AAAA_MM em {bands[:5]}...; asset nao e mensal.")
    x0, y0, x1, y1 = load_config()["bbox"]
    geom = ee.Geometry.Rectangle([x0, y0, x1, y1], proj="EPSG:4326", geodesic=False)
    px = ee.Image.pixelArea().divide(1e6)

    years = sorted({m.group(1) for m in monthly.values()})
    rows = []
    for y in years:
        names = sorted(b for b, m in monthly.items() if m.group(1) == y)
        stack = img.select(names).eq(a.water_value).multiply(px)
        res = stack.reduceRegion(ee.Reducer.sum(), geom, a.scale, maxPixels=1e10, tileScale=4).getInfo()
        for b in names:
            m = monthly[b]
            rows.append((f"{m.group(1)}-{m.group(2)}-01", res.get(b)))
        print(y, "ok")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "water_km2"])
        w.writerows(sorted(rows))
    print("escrito", out)


if __name__ == "__main__":
    main()

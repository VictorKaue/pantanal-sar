"""OPERA DSWx-S1 (Sentinel-1, banda C): agua por data -> data/series/opera_dswx_s1.csv (contrato v2).

So a camada B01_WTR, recortada ao bbox na grade nativa (EPSG:32721, 30 m). Cobertura no CMR:
a partir de 2024-08, sem jul-ago/2026. Usado para validar a agua do Sentinel-1/NISAR.
WTR: 0 nao agua, 1 agua aberta, 2 agua parcial, 3 vegetacao inundada, 250 mascara HAND,
251 layover/sombra, 252 neve, 253 nuvem, 255 fill. Valido = 0..3.
Dados: NASA OPERA / PO.DAAC, OPERA_L3_DSWX-S1_V1, https://doi.org/10.5067/OPDSWS1-L3V1
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date

import numpy as np

from . import opera
from .config import PROCESSED, RAW, ROOT, load_config

SHORT_NAME = "OPERA_L3_DSWX-S1_V1"
EPSG = 32721
CLEAR = (0, 1, 2, 3)
CACHE = RAW / "opera_dswx_s1"
CSV = ROOT / "data" / "series" / "opera_dswx_s1.csv"
FIELDS = ["date", "source", "sensor", "water_km2", "water_partial_km2", "valid_km2", "valid_frac",
          "method", "quality", "product", "n_granules", "water_inundveg_km2"]
_NAME = re.compile(r"DSWx-S1_(T\w{5})_(\d{8})T(\d{6})Z_\d{8}T\d{6}Z_(\w+?)_30_")


def stats(arr: np.ndarray, pixel_km2: float = (opera.PIXEL / 1000) ** 2) -> dict:
    clear = np.isin(arr, CLEAR)
    return {"water_km2": float((arr == 1).sum() * pixel_km2),
            "water_partial_km2": float((arr == 2).sum() * pixel_km2),
            "water_inundveg_km2": float((arr == 3).sum() * pixel_km2),
            "clear_km2": float(clear.sum() * pixel_km2),
            "clear_frac": float(clear.sum() / arr.size)}


def daily_rows(scenes):
    return [{"date": s["date"], "source": "opera_dswx_s1", "sensor": "Sentinel-1 C-band",
             "water_km2": round(s["water_km2"], 4), "water_partial_km2": round(s["water_partial_km2"], 4),
             "valid_km2": round(s["clear_km2"], 4), "valid_frac": round(s["clear_frac"], 4),
             "method": "DSWx-S1 WTR=1", "quality": opera.quality(s["clear_frac"]),
             "product": SHORT_NAME, "n_granules": s["n_granules"],
             "water_inundveg_km2": round(s["water_inundveg_km2"], 4)} for s in scenes]


def write(rows, path=CSV):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


PROCESSED_DIR = PROCESSED / "opera_dswx_s1"


def export_tifs(granules, grid, folder=PROCESSED_DIR) -> int:
    """<data>_WTR.tif: mosaico do dia da B01_WTR (uint8, classes originais, 255 = sem dado)
    na mesma grade do RTC (EPSG:32721, 30 m). Le o cache de recortes."""
    import rasterio
    from rasterio.transform import Affine
    by_date = defaultdict(list)
    for g in granules:
        f = CACHE / f"{g['title']}.npz"
        if f.exists():
            by_date[g["date"]].append(np.load(f)["wtr"])
    left, top, ncols, nrows = grid
    folder.mkdir(parents=True, exist_ok=True)
    for d, arrs in by_date.items():
        with rasterio.open(folder / f"{d}_WTR.tif", "w", driver="GTiff", height=nrows, width=ncols, count=1,
                           dtype="uint8", crs=f"EPSG:{EPSG}", nodata=255, compress="deflate",
                           transform=Affine(opera.PIXEL, 0, left, 0, -opera.PIXEL, top)) as dst:
            dst.write(opera.composite(arrs, CLEAR), 1)
    return len(by_date)


def run(start: str = "2024-08-01", end: str | None = None) -> None:
    bbox = load_config()["bbox"]
    gr = opera.search(bbox, start, end or date.today().isoformat(), SHORT_NAME, _NAME)
    print(f"{len(gr)} granulos DSWx-S1")
    scenes = opera.scenes_from(gr, opera.aoi_grid(bbox, EPSG), cache=CACHE, epsg=EPSG,
                               clear=CLEAR, stats=stats)
    rows = daily_rows(scenes)
    print(f"{len(rows)} datas, {sum(r['quality'] != 'drop' for r in rows)} com valid_frac >= {opera.MIN_CLEAR}")
    print("escrito", write(rows))
    print(f"{export_tifs(gr, opera.aoi_grid(bbox, EPSG))} GeoTIFFs WTR em {PROCESSED_DIR}")

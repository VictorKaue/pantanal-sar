"""OPERA DSWx-HLS: serie mensal de area de agua -> data/series/opera_dswx_water.csv.

Saida principal: data/series/opera_dswx_hls.csv (contrato v2, uma linha por data).
Ponte de calibracao entre MapBiomas Agua (2025) e NISAR (2026). Baixa so a camada
B01_WTR de cada tile, recorta ao bbox da AOI (grade UTM 30 m, sem reamostragem),
junta os tiles/sensores do mesmo dia e agrega por mes (mediana das datas validas).

Classes WTR: 0 nao agua, 1 agua aberta, 2 agua parcial, 252 neve/gelo, 253 nuvem/
sombra, 254 oceano (mascara), 255 fill. "Claro" = classes 0, 1, 2.
Dados: NASA OPERA / PO.DAAC, OPERA_L3_DSWX-HLS_V1, https://doi.org/10.5067/OPDSW-PL3V1
"""

from __future__ import annotations

import csv
import io
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from statistics import median

import numpy as np
import requests

from .config import RAW, ROOT, load_config, load_env

SHORT_NAME = "OPERA_L3_DSWX-HLS_V1"
CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"
SERIES_CSV = ROOT / "data" / "series" / "opera_dswx_water.csv"  # derivado mensal
DAILY_CSV = ROOT / "data" / "series" / "opera_dswx_hls.csv"  # contrato v2, por data
DAILY_FIELDS = ["date", "source", "sensor", "water_km2", "water_partial_km2", "valid_km2",
                "valid_frac", "method", "quality", "product", "n_granules"]
CACHE = RAW / "opera_dswx"
FIELDS = ["date", "water_km2", "water_partial_km2", "clear_frac", "n_scenes", "source"]
SOURCE = "NASA OPERA DSWx-HLS v1 (HLS L30/S30, 30 m)"
MIN_CLEAR = 0.6
PIXEL = 30.0
FILL = 255
CLEAR_CLASSES = (0, 1, 2)
_NAME = re.compile(r"DSWx-HLS_(T\w{5})_(\d{8})T(\d{6})Z_\d{8}T\d{6}Z_(\w+?)_30_")


# ---------------------------------------------------------------- CMR
def search(bbox, start: str, end: str, short_name: str = SHORT_NAME, pattern=_NAME) -> list[dict]:
    """Granules over bbox. Returns [{title, tile, date, sensor, url}] (WTR url only)."""
    out, page = [], 1
    while True:
        r = requests.get(CMR, params={
            "short_name": short_name, "bounding_box": ",".join(map(str, bbox)),
            "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
            "page_size": 2000, "page_num": page}, timeout=60)
        r.raise_for_status()
        entries = r.json()["feed"]["entry"]
        if not entries:
            break
        for e in entries:
            m = pattern.search(e["title"])
            url = next((link["href"] for link in e["links"]
                        if link["href"].endswith("_B01_WTR.tif") and link["href"].startswith("https")
                        and "data#" in link.get("rel", "")), None)
            if m and url:
                d = m.group(2)
                out.append({"title": e["title"], "tile": m.group(1), "sensor": m.group(4),
                            "date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "url": url})
        page += 1
    return out


def per_month(granules) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for g in granules:
        c[g["date"][:7]] += 1
    return dict(sorted(c.items()))


# ---------------------------------------------------------------- grid / clip
def aoi_grid(bbox, epsg: int = 32621):
    """Target grid in EPSG:32621, the native OPERA grid (UTM 21N with negative northing in the
    southern hemisphere), 30 m, snapped to multiples of 30 m. -> (left, top, ncols, nrows)."""
    from rasterio.warp import transform_bounds
    l, b, r, t = transform_bounds("EPSG:4326", f"EPSG:{epsg}", *bbox)
    left, top = np.floor(l / PIXEL) * PIXEL, np.ceil(t / PIXEL) * PIXEL
    ncols, nrows = int(np.ceil((r - left) / PIXEL)), int(np.ceil((top - b) / PIXEL))
    return float(left), float(top), ncols, nrows


def clip_tile(tif_bytes: bytes, grid, epsg: int = 32621) -> np.ndarray:
    """Read the WTR window of the AOI grid from a tile; outside the tile = 255."""
    import rasterio
    from rasterio.windows import Window
    left, top, ncols, nrows = grid
    with rasterio.MemoryFile(tif_bytes) as mf, mf.open() as src:
        if src.crs.to_epsg() != epsg or abs(src.transform.a - PIXEL) > 1e-6:
            raise ValueError(f"grade inesperada: {src.crs} {src.transform.a}")
        c0 = int(round((left - src.transform.c) / PIXEL))
        r0 = int(round((src.transform.f - top) / PIXEL))
        return src.read(1, window=Window(c0, r0, ncols, nrows), boundless=True, fill_value=FILL)


def composite(arrays, clear=CLEAR_CLASSES) -> np.ndarray:
    """Merge same-day clips: a clear pixel (0/1/2) beats cloud/mask/fill."""
    out = np.full_like(arrays[0], FILL)
    for a in arrays:
        take = np.isin(a, clear) & ~np.isin(out, clear)
        out[take] = a[take]
    return out


def scene_stats(arr: np.ndarray, pixel_km2: float = (PIXEL / 1000) ** 2) -> dict:
    """water_km2 (class 1), water_partial_km2 (class 2), clear_km2, clear_frac (over the whole AOI grid)."""
    clear = np.isin(arr, CLEAR_CLASSES)
    return {"water_km2": float((arr == 1).sum() * pixel_km2),
            "water_partial_km2": float((arr == 2).sum() * pixel_km2),
            "clear_km2": float(clear.sum() * pixel_km2),
            "clear_frac": float(clear.sum() / arr.size)}


# ---------------------------------------------------------------- aggregate
def monthly(scenes, min_clear: float = MIN_CLEAR):
    """scenes: [{date, water_km2, water_partial_km2, clear_frac}]. Drops clear_frac < min_clear,
    then the median of the valid scenes of each month. Returns contract rows."""
    by_month: dict[str, list[dict]] = defaultdict(list)
    for s in scenes:
        if s["clear_frac"] >= min_clear:
            by_month[s["date"][:7]].append(s)
    rows = []
    for ym, ss in sorted(by_month.items()):
        rows.append({
            "date": f"{ym}-01",
            "water_km2": round(median(s["water_km2"] for s in ss), 4),
            "water_partial_km2": round(median(s["water_partial_km2"] for s in ss), 4),
            "clear_frac": round(median(s["clear_frac"] for s in ss), 4),
            "n_scenes": len(ss), "source": SOURCE})
    return rows


def write(rows, path: Path = SERIES_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


# ---------------------------------------------------------------- download
def rasterio_errors():
    import rasterio.errors
    return rasterio.errors.RasterioError


def _session() -> requests.Session:
    load_env()
    s = requests.Session()
    tok = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"  # requests drops it on cross-host redirects
    elif os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        s.auth = (os.environ["EARTHDATA_USERNAME"], os.environ["EARTHDATA_PASSWORD"])
    else:
        raise SystemExit("Faltam EARTHDATA_TOKEN (ou USERNAME/PASSWORD) no .env (ver docs/SETUP.md)")
    return s


def _clip_cached(g: dict, grid, sess, cache: Path = CACHE, epsg: int = 32621) -> np.ndarray | None:
    f = cache / f"{g['title']}.npz"
    if f.exists():
        return np.load(f)["wtr"]
    for attempt in range(4):
        try:
            r = sess.get(g["url"], timeout=180)
            if r.status_code == 404:  # catalogado no CMR mas ausente no arquivo
                print("  404, ignorado:", g["title"])
                return None
            r.raise_for_status()
            arr = clip_tile(r.content, grid, epsg)
            break
        except ValueError as exc:  # grade inesperada (CRS fora do padrao): pular
            print("  grade inesperada, ignorado:", g["title"], exc)
            return None
        except (requests.RequestException, rasterio_errors()) as exc:
            if attempt == 3:
                print("  falhou, ignorado:", g["title"], exc)
                return None
            time.sleep(2 ** attempt)
    cache.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(f, wtr=arr)
    return arr


def scenes_from(granules, grid, workers: int = 6, cache: Path = CACHE, epsg: int = 32621,
                clear=CLEAR_CLASSES, stats=None):
    """Group granules by date, clip WTR, composite same-day tiles/sensors, compute stats."""
    sess = _session()
    by_date: dict[str, list[dict]] = defaultdict(list)
    for g in granules:
        by_date[g["date"]].append(g)
    flat = [g for gs in by_date.values() for g in gs]
    with ThreadPoolExecutor(workers) as ex:
        clips = dict(zip((g["title"] for g in flat),
                         ex.map(lambda g: _clip_cached(g, grid, sess, cache, epsg), flat)))
    out = []
    for d, gs in sorted(by_date.items()):
        arrs = [clips[g["title"]] for g in gs if clips[g["title"]] is not None]
        if arrs:
            out.append({"date": d, "n_granules": len(arrs), **(stats or scene_stats)(composite(arrs, clear))})
    return out


def default_periods():
    """Historico completo para o modelo: 2023-01 ate hoje (contrato v2)."""
    return [("2023-01-01", date.today().isoformat())]


def quality(valid_frac: float) -> str:
    """ok >= 0.8 · low 0.6-0.8 (peso menor no modelo) · drop < 0.6 (fora do modelo)."""
    return "ok" if valid_frac >= 0.8 else "low" if valid_frac >= MIN_CLEAR else "drop"


def daily_rows(scenes):
    """Contract v2 rows (docs/DATA_CONTRACT.md, secao 1): one per date (mosaico do dia)."""
    return [{"date": s["date"], "source": "opera_dswx_hls", "sensor": "HLS optical",
             "water_km2": round(s["water_km2"], 4),
             "water_partial_km2": round(s["water_partial_km2"], 4),
             "valid_km2": round(s["clear_km2"], 4), "valid_frac": round(s["clear_frac"], 4),
             "method": "DSWx WTR=1", "quality": quality(s["clear_frac"]),
             "product": SHORT_NAME, "n_granules": s["n_granules"]} for s in scenes]


def write_daily(rows, path: Path = DAILY_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DAILY_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def run(start: str | None = None, end: str | None = None, only_search: bool = False) -> None:
    bbox = load_config()["bbox"]
    periods = [(start, end)] if start and end else default_periods()
    granules = []
    for s, e in periods:
        granules += search(bbox, s, e)
    print(f"{len(granules)} granulos OPERA DSWx-HLS no bbox {bbox}")
    for ym, n in per_month(granules).items():
        print(f"  {ym}: {n}")
    if only_search:
        return
    scenes = scenes_from(granules, aoi_grid(bbox))
    daily = daily_rows(scenes)
    n_ok = sum(r["quality"] != "drop" for r in daily)
    print(f"{len(daily)} datas, {n_ok} com valid_frac >= {MIN_CLEAR}")
    print("escrito", write_daily(daily))
    rows = monthly(scenes)  # derivado do diario; Mare/timeseries ainda le este
    print("escrito", write(rows), f"(derivado mensal, {len(rows)} meses)")

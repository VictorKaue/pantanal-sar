"""OPERA RTC-S1 (Sentinel-1, banda C): recortes VV/VH por data -> data/processed/s1_rtc/.

Por data: junta os bursts que tocam o bbox (media em escala linear nas sobreposicoes), reprojeta
para a grade do AOI (EPSG:32721, 30 m) e grava <data>_VV.tif e <data>_VH.tif (float32, gamma0
LINEAR como no OPERA, NaN = sem dado; mantissa reduzida a 12 bits, erro <0,05%, para comprimir). Nada bruto vai para o disco: cada burst e lido
da memoria, entao nao ha bruto para apagar. Indice em data/processed/s1_rtc/index.csv.
Os recortes alimentam a Lagoa (agua por limiar -> data/series/s1_rtc.csv).

Acesso: o ASF (datapool.asf.alaska.edu) exige que o app "ASF Data Access" esteja autorizado
no perfil Earthdata (EULA). Sem isso o servidor responde 403 "EULA Acceptance Failure".
Dados: NASA OPERA / ASF DAAC, OPERA_L2_RTC-S1_V1, https://doi.org/10.5067/SNWG/OPERA_L2_RTC-S1_V1
"""

from __future__ import annotations

import csv
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests

from . import opera
from .config import PROCESSED, load_config

SHORT_NAME = "OPERA_L2_RTC-S1_V1"
EPSG = 32721
OUT = PROCESSED / "s1_rtc"
INDEX = OUT / "index.csv"
INDEX_FIELDS = ["date", "n_bursts", "tracks", "valid_frac_vv", "valid_frac_vh", "median_vv_db", "median_vh_db"]
MAX_DISK_GB = 10.0
_NAME = re.compile(r"RTC-S1_(T\d+)-\d+-IW\d_(\d{8})T\d{6}Z_")


def search(bbox, start: str, end: str) -> dict[str, list[dict]]:
    """Burst granules over bbox grouped by acquisition date: {date: [{title, track, vv, vh}]}."""
    out: dict[str, list[dict]] = defaultdict(list)
    page = 1
    while True:
        r = requests.get(opera.CMR, params={
            "short_name": SHORT_NAME, "bounding_box": ",".join(map(str, bbox)),
            "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z", "page_size": 2000, "page_num": page},
            timeout=90)
        r.raise_for_status()
        entries = r.json()["feed"]["entry"]
        if not entries:
            break
        for e in entries:
            m = _NAME.search(e["title"])
            hrefs = {h["href"] for h in e["links"] if h["href"].startswith("https") and "data#" in h.get("rel", "")}
            vv = next((h for h in hrefs if h.endswith("_VV.tif")), None)
            vh = next((h for h in hrefs if h.endswith("_VH.tif")), None)
            if m and vv and vh:
                d = m.group(2)
                out[f"{d[:4]}-{d[4:6]}-{d[6:]}"].append(
                    {"title": e["title"], "track": m.group(1), "vv": vv, "vh": vh})
        page += 1
    return dict(sorted(out.items()))


def _get(sess: requests.Session, url: str) -> bytes | None:
    """GET following redirects by hand, keeping the bearer token on ASF hosts (requests drops
    Authorization when the host changes)."""
    auth = sess.headers.get("Authorization")
    for attempt in range(4):
        try:
            cur = url
            for _ in range(8):
                host = urlparse(cur).hostname or ""
                headers = {"Authorization": auth} if auth and host.endswith("asf.alaska.edu") else {}
                r = sess.get(cur, headers=headers, allow_redirects=False, timeout=180)
                if r.status_code in (301, 302, 303, 307, 308):
                    cur = r.headers["location"]
                    continue
                break
            if r.status_code == 404:
                return None
            if r.status_code == 403 and "EULA" in r.text:
                raise SystemExit("ASF: EULA nao aceita. Autorize o app em "
                                 "https://urs.earthdata.nasa.gov/approve_app?client_id=BO_n7nTIlMljdvU6kRRB3g")
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if attempt == 3:
                return None
            time.sleep(2 ** attempt)
    return None


def to_grid(tif_bytes: bytes, grid, epsg: int = EPSG) -> np.ndarray:
    """Read one burst band and resample it onto the AOI grid (linear power, NaN = no data)."""
    import rasterio
    from rasterio.transform import Affine
    from rasterio.warp import Resampling, reproject
    left, top, ncols, nrows = grid
    dst = np.full((nrows, ncols), np.nan, dtype=np.float32)
    with rasterio.MemoryFile(tif_bytes) as mf, mf.open() as src:
        reproject(rasterio.band(src, 1), dst, dst_transform=Affine(opera.PIXEL, 0, left, 0, -opera.PIXEL, top),
                  dst_crs=f"EPSG:{epsg}", src_nodata=src.nodata if src.nodata is not None else np.nan,
                  dst_nodata=np.nan, resampling=Resampling.bilinear)
    dst[~np.isfinite(dst) | (dst <= 0)] = np.nan
    return dst


def mosaic_linear(arrays) -> np.ndarray:
    """Mean in linear power over overlapping bursts (NaN where no burst)."""
    with np.errstate(all="ignore"):
        return np.nanmean(np.stack(arrays), axis=0).astype(np.float32)


def quantize(lin: np.ndarray) -> np.ndarray:
    """Zero the low 11 mantissa bits: relative error < 0.05 %, far smaller than speckle."""
    return (lin.astype(np.float32).view(np.uint32) & np.uint32(0xFFFFF800)).view(np.float32)


def write_linear(path: Path, lin: np.ndarray, grid, epsg: int = EPSG) -> None:
    import rasterio
    from rasterio.transform import Affine
    left, top, ncols, nrows = grid
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", height=nrows, width=ncols, count=1, dtype="float32",
                       crs=f"EPSG:{epsg}", transform=Affine(opera.PIXEL, 0, left, 0, -opera.PIXEL, top),
                       nodata=float("nan"), compress="deflate", predictor=3, zlevel=6,
                       tiled=True, blockxsize=256, blockysize=256) as dst:
        dst.write(quantize(lin), 1)
        dst.update_tags(units="linear gamma0", source=SHORT_NAME, mosaic="mean of bursts, linear power")


def disk_gb(folder: Path = OUT) -> float:
    return sum(f.stat().st_size for f in folder.glob("*.tif")) / 1e9 if folder.exists() else 0.0


def process_date(d: str, bursts, grid, sess) -> dict | None:
    """Download VV/VH of every burst of the day (in memory), mosaic, write two GeoTIFFs."""
    def fetch(b):
        out = {}
        for pol in ("vv", "vh"):
            raw = _get(sess, b[pol])
            out[pol] = None if raw is None else to_grid(raw, grid)
        return out
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(fetch, bursts))
    stats = {}
    for pol in ("vv", "vh"):
        arrs = [g[pol] for g in got if g[pol] is not None]
        if not arrs:
            return None
        lin = mosaic_linear(arrs)
        write_linear(OUT / f"{d}_{pol.upper()}.tif", lin, grid)
        ok = np.isfinite(lin)
        stats[pol] = (float(ok.mean()), float(10 * np.log10(np.median(lin[ok]))) if ok.any() else float("nan"))
    return {"date": d, "n_bursts": len(bursts), "tracks": "+".join(sorted({b["track"] for b in bursts})),
            "valid_frac_vv": round(stats["vv"][0], 4), "valid_frac_vh": round(stats["vh"][0], 4),
            "median_vv_db": round(stats["vv"][1], 2), "median_vh_db": round(stats["vh"][1], 2)}


def _read_index() -> dict[str, dict]:
    if not INDEX.exists():
        return {}
    with open(INDEX, encoding="utf-8") as f:
        return {r["date"]: r for r in csv.DictReader(f)}


def _write_index(rows: dict[str, dict]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(INDEX, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=INDEX_FIELDS)
        w.writeheader()
        w.writerows(rows[k] for k in sorted(rows))


NISAR_2026 = ["2026-07-17", "2026-08-10", "2026-08-22", "2026-09-03", "2026-09-15",
              "2026-09-27", "2026-10-09", "2026-10-21"]


def batches(dates, nisar=NISAR_2026, near_days: int = 3):
    """Priority order asked by Lagoa: (1) <= 3 d from a NISAR 2026 pass, (2) flood Mar-May and
    dry Aug-Oct of every year, (3) the rest. Returns [(name, [dates])]."""
    from datetime import date as D
    nd = [D.fromisoformat(x) for x in nisar]
    near = lambda d: any(abs((D.fromisoformat(d) - n).days) <= near_days for n in nd)
    b1 = [d for d in dates if near(d)]
    b2 = [d for d in dates if d not in b1 and int(d[5:7]) in (3, 4, 5, 8, 9, 10)]
    b3 = [d for d in dates if d not in b1 and d not in b2]
    return [("1_perto_NISAR_2026", b1), ("2_cheia_seca", b2), ("3_restante", b3)]


def run(start: str = "2023-01-01", end: str = "2026-11-14", only_search: bool = False) -> None:
    bbox = load_config()["bbox"]
    by_date = search(bbox, start, end)
    nb = sum(len(v) for v in by_date.values())
    print(f"RTC-S1: {nb} bursts em {len(by_date)} datas ({start} a {end})")
    if only_search:
        return
    sess = opera._session()
    grid = opera.aoi_grid(bbox, EPSG)
    index = _read_index()
    fails = []
    for name, dates in batches(list(by_date)):
        for d in dates:
            if d in index and (OUT / f"{d}_VV.tif").exists() and (OUT / f"{d}_VH.tif").exists():
                continue
            if disk_gb() > MAX_DISK_GB:
                print(f"PARADO: {disk_gb():.1f} GB em {OUT} (limite {MAX_DISK_GB} GB)")
                return
            row = process_date(d, by_date[d], grid, sess)
            if row is None:
                fails.append(d)
                print("  falha:", d)
                continue
            index[d] = row
            _write_index(index)
            print(f"  {d}: {row['n_bursts']} bursts, valid {row['valid_frac_vv']:.2f}, "
                  f"VV {row['median_vv_db']} dB, VH {row['median_vh_db']} dB · {disk_gb():.2f} GB")
        print(f"LOTE_PRONTO {name}: {len(dates)} datas, {len(index)} no indice, falhas {fails}, "
              f"{disk_gb():.2f} GB", flush=True)

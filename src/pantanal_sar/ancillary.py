"""Ancillary NASA data used to check what NISAR shows.

  FIRMS   -> when and where fire occurred (points). Needs FIRMS_MAP_KEY.
  MCD64A1 -> how much area burned (monthly). Exported from AppEEARS as GeoTIFF (manual step).
  HLS     -> optical image to validate the NISAR water map. Needs Earthdata Login.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import rasterio
import requests
from rasterio.warp import Resampling, reproject, transform as warp_transform

from .config import RAW, load_config, load_env, require_env

FIRMS_API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/{days}/{date}"


# ---------------------------------------------------------------- FIRMS
def fetch_firms() -> Path:
    """Download FIRMS hotspots for the AOI and period, in 10-day windows."""
    key = require_env("FIRMS_MAP_KEY", "Request a free key at https://firms.modaps.eosdis.nasa.gov/api/map_key/")
    cfg = load_config()
    w, s, e, n = cfg["bbox"]
    area = f"{w},{s},{e},{n}"
    start = date.fromisoformat(cfg["firms"]["start"])
    end = date.fromisoformat(cfg["firms"]["end"])
    rows, seen, header = [], set(), None
    for source in cfg["firms"]["sources"]:
        d = start
        while d <= end:
            days = min(10, (end - d).days + 1)
            url = FIRMS_API.format(key=key, source=source, area=area, days=days, date=d.isoformat())
            r = requests.get(url, timeout=120)
            text = r.text.strip()
            if r.ok and text and not text.lower().startswith(("invalid", "error")):
                reader = csv.DictReader(io.StringIO(text))
                for row in reader:
                    k = (row.get("latitude"), row.get("longitude"), row.get("acq_date"), row.get("acq_time"))
                    if k in seen:
                        continue
                    seen.add(k)
                    row["source"] = source
                    rows.append(row)
                    header = header or list(row)
            d += timedelta(days=days)
        print(f"  {source}: total so far {len(rows)}")
    out = RAW / "firms" / f"firms_{cfg['name']}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        fields = sorted({k for r in rows for k in r})
        with open(out, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=fields)
            wr.writeheader()
            wr.writerows(rows)
    print(f"{len(rows)} hotspots -> {out}")
    return out


def load_firms(path: Path | None = None) -> list[dict]:
    cfg = load_config()
    path = path or RAW / "firms" / f"firms_{cfg['name']}.csv"
    if not Path(path).exists():
        return []
    with open(path) as f:
        return [dict(r, lat=float(r["latitude"]), lon=float(r["longitude"])) for r in csv.DictReader(f)]


def firms_rowcol(points, grid, d0: str, d1: str):
    """Rows/cols on the grid of hotspots detected between d0 (excl.) and d1 (incl.)."""
    sel = [p for p in points if d0 < p["acq_date"] <= d1]
    if not sel:
        return np.array([], int), np.array([], int)
    xs, ys = warp_transform("EPSG:4326", grid["crs"], [p["lon"] for p in sel], [p["lat"] for p in sel])
    inv = ~grid["transform"]
    cols, rows = inv * (np.array(xs), np.array(ys))
    return np.floor(rows).astype(int), np.floor(cols).astype(int)


# ---------------------------------------------------------------- MCD64A1 (AppEEARS GeoTIFF)
DOY_RE = re.compile(r"doy(\d{4})(\d{3})")


def mcd64a1_burned(grid, d0: str, d1: str, folder: Path | None = None):
    """Burned mask between d0 and d1 from MCD64A1 'Burn_Date' GeoTIFFs. None if no files."""
    folder = folder or RAW / "mcd64a1"
    files = sorted(Path(folder).glob("*Burn_Date*.tif"))
    if not files:
        return None
    t0 = datetime.fromisoformat(d0).date()
    t1 = datetime.fromisoformat(d1).date()
    out = np.zeros(grid["shape"], dtype=bool)
    covered = False
    for f in files:
        m = DOY_RE.search(f.name)
        if not m:
            continue
        year = int(m.group(1))
        with rasterio.open(f) as src:
            dst = np.zeros(grid["shape"], dtype="int16")
            reproject(rasterio.band(src, 1), dst, dst_transform=grid["transform"], dst_crs=grid["crs"],
                      resampling=Resampling.nearest)
        doy_dates = np.vectorize(lambda v: date(year, 1, 1) + timedelta(int(v) - 1) if v > 0 else date(1, 1, 1))
        burned = dst > 0
        if burned.any():
            dd = doy_dates(dst[burned])
            sel = np.array([(t0 < x <= t1) for x in dd])
            idx = np.argwhere(burned)[sel]
            out[idx[:, 0], idx[:, 1]] = True
        covered = True
    return out if covered else None


# ---------------------------------------------------------------- HLS
HLS_BANDS = {"HLSS30": ("B03", "B11"), "HLSL30": ("B03", "B06")}


def fetch_hls() -> None:
    """Download green, SWIR1 and Fmask of the clearest HLS scene near each NISAR date."""
    import earthaccess

    load_env()
    earthaccess.login(strategy="environment")
    cfg = load_config()
    w, s, e, n = cfg["bbox"]
    win = cfg["hls"]["search_window_days"]
    for d in cfg["nisar"]["dates"]:
        t = date.fromisoformat(d)
        best = None
        for short in HLS_BANDS:
            res = earthaccess.search_data(short_name=short, version="2.0",
                                          temporal=((t - timedelta(win)).isoformat(), (t + timedelta(win)).isoformat()),
                                          bounding_box=(w, s, e, n),
                                          cloud_cover=(0, cfg["hls"]["max_cloud_cover"]))
            for g in res:
                cc = float(g["umm"].get("CloudCover", 100) or 100)
                if best is None or cc < best[0]:
                    best = (cc, short, g)
        if not best:
            print(f"  {d}: no HLS scene under {cfg['hls']['max_cloud_cover']}% cloud")
            continue
        cc, short, g = best
        green, swir = HLS_BANDS[short]
        urls = [u for u in g.data_links() if u.endswith((f".{green}.tif", f".{swir}.tif", ".Fmask.tif"))]
        dest = RAW / "hls" / d
        earthaccess.download(urls, local_path=str(dest))
        print(f"  {d}: {g['umm']['GranuleUR']} ({cc:.0f}% cloud) -> {dest}")


def hls_water(grid, d: str, folder: Path | None = None):
    """Optical water mask (MNDWI > 0, clouds removed) on the NISAR grid. None if missing.

    Returns (water, valid). HLS reflectance scale 1e-4; Fmask bits 1-3 = cloud,
    adjacent cloud, cloud shadow.
    """
    folder = folder or RAW / "hls" / d
    files = list(Path(folder).glob("*.tif"))
    if not files:
        return None
    green = next((f for f in files if f.name.endswith(".B03.tif")), None)
    swir = next((f for f in files if f.name.endswith((".B11.tif", ".B06.tif"))), None)
    fmask = next((f for f in files if f.name.endswith(".Fmask.tif")), None)
    if not (green and swir):
        return None

    def warp(path, dtype, resampling=Resampling.bilinear):
        with rasterio.open(path) as src:
            dst = np.full(grid["shape"], -9999, dtype=dtype)
            reproject(rasterio.band(src, 1), dst, dst_transform=grid["transform"], dst_crs=grid["crs"],
                      resampling=resampling, dst_nodata=-9999)
        return dst

    g = warp(green, "float32").astype("float32")
    sw = warp(swir, "float32").astype("float32")
    valid = (g > -9999) & (sw > -9999)
    if fmask:
        fm = warp(fmask, "int16", Resampling.nearest)
        cloud = (fm & 0b1110) > 0
        valid &= ~cloud & (fm >= 0) & (fm != 255)
    with np.errstate(divide="ignore", invalid="ignore"):
        mndwi = (g - sw) / (g + sw)
    return (mndwi > 0) & valid, valid

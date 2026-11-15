"""Open-water area time series from NISAR GCOV HH (track 132).

Per date: Lee filter on linear HH -> dB -> threshold -> open-water mask ->
area in km2 inside the AOI bbox (valid pixels only). Writes one row per date to
data/series/nisar_water.csv and a QC histogram PNG to data/qc/.

Threshold: valley (local minimum) between the lowest-dB peak (water) and the
main land peak of the smoothed HH histogram; falls back to Otsu. Both are clipped
to processing.water_threshold_db_bounds.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from . import change
from .config import ROOT

SERIES_CSV = ROOT / "data" / "series" / "nisar_water.csv"
QC_DIR = ROOT / "data" / "qc"
FIELDS = ["date", "water_km2", "water_frac", "valid_km2", "threshold_db", "track", "source",
          "water_km2_fixed"]
# Fixed threshold (dB) for a series comparable across dates (valley of 2026-07-17). The
# per-date threshold adapts to wind/incidence; the fixed one keeps the same definition of
# water. Absolute bias is corrected later by the OPERA DSWx calibration (timeseries.py).
FIXED_THRESHOLD_DB = -16.75
CACHE_DIR = ROOT / "data" / "processed" / "nisar"
HIST_RANGE = (-35.0, 5.0)
BIN = 0.1
# Minimum share of the AOI bbox with valid HH for a date to enter the series. The provisional
# 2026-07-05 granule (track 132) has HH = HV = 0 over most of the frame with mask = valid.
MIN_VALID_FRAC = 0.5


def histogram(hh_db: np.ndarray):
    v = hh_db[np.isfinite(hh_db)]
    edges = np.arange(HIST_RANGE[0], HIST_RANGE[1] + BIN, BIN)
    counts, edges = np.histogram(v, bins=edges)
    return counts, 0.5 * (edges[:-1] + edges[1:])


def valley_threshold(hh_db: np.ndarray, bounds=(-24.0, -14.0), sigma_db=0.5) -> float | None:
    """Local minimum between the water peak and the land peak, or None if unimodal."""
    counts, centers = histogram(hh_db)
    h = gaussian_filter1d(counts.astype(float), sigma_db / BIN)
    land = int(np.argmax(h))
    peaks = [i for i in range(1, land) if h[i] > h[i - 1] and h[i] >= h[i + 1]
             and h[i] > 0.002 * h[land]]
    if not peaks:
        return None
    water = peaks[0]  # lowest-dB peak
    vi = water + int(np.argmin(h[water:land + 1]))
    t = float(centers[vi])
    return t if bounds[0] <= t <= bounds[1] else None


def choose_threshold(hh_db, bounds=(-24.0, -14.0)) -> tuple[float, str, float]:
    """Return (threshold, method, otsu_value)."""
    otsu = change.water_threshold(hh_db, bounds)
    v = valley_threshold(hh_db, bounds)
    return (v, "valley", otsu) if v is not None else (otsu, "otsu", otsu)


def bbox_mask(shape, transform, crs, bbox) -> np.ndarray:
    """True for pixels whose centre (lon/lat) lies inside bbox."""
    from rasterio.transform import xy as _xy
    from rasterio.warp import transform as warp

    def rasterio_xy(t, r, c):
        return _xy(t, r, c, offset="center")

    rows, cols = np.indices(shape)
    xs, ys = rasterio_xy(transform, rows.ravel(), cols.ravel())
    lon, lat = warp(crs, "EPSG:4326", xs, ys)
    lon, lat = np.asarray(lon).reshape(shape), np.asarray(lat).reshape(shape)
    w, s, e, n = bbox
    return (lon >= w) & (lon <= e) & (lat >= s) & (lat <= n)


def water_for_date(hh_lin, transform, crs, bbox, bounds=(-24.0, -14.0), speckle=5):
    """Return dict with mask, hh_db, threshold info and areas."""
    hh_db = change.to_db(change.lee_filter(hh_lin, speckle))
    inside = bbox_mask(hh_db.shape, transform, crs, bbox)
    hh_db = np.where(inside, hh_db, np.nan)
    thr, method, otsu = choose_threshold(hh_db, bounds)
    water = change.open_water(hh_db, thr) & inside
    fixed = change.open_water(hh_db, FIXED_THRESHOLD_DB) & inside
    valid = np.isfinite(hh_db)
    px_km2 = abs(transform.a * transform.e) / 1e6
    return dict(hh_db=hh_db, water=water, valid=valid, threshold_db=thr, method=method,
                otsu_db=otsu, water_km2=float(water.sum() * px_km2),
                water_fixed=fixed, water_km2_fixed=float(fixed.sum() * px_km2),
                valid_km2=float(valid.sum() * px_km2), valid_frac=float(valid[inside].mean()))


def save_histogram(path: Path, hh_db, thr, otsu, date, bounds):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    counts, centers = histogram(hh_db)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.fill_between(centers, counts, step="mid", color="0.6")
    ax.axvline(thr, color="tab:blue", label=f"limiar {thr:.1f} dB")
    ax.axvline(otsu, color="tab:orange", ls="--", label=f"Otsu {otsu:.1f} dB")
    ax.axvspan(*bounds, color="tab:blue", alpha=0.08, label="limites")
    ax.set_yscale("log")
    ax.set_xlabel("HH gamma0 (dB), Lee 5x5, 20 m")
    ax.set_ylabel("pixels")
    ax.set_title(f"NISAR GCOV HH, trilha 132, {date}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)


def upsert_row(row: dict, path: Path = SERIES_CSV) -> None:
    rows = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            rows = {r["date"]: {k: r.get(k, "") for k in FIELDS} for r in csv.DictReader(f)}
    rows[row["date"]] = {k: row.get(k, "") for k in FIELDS}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for d in sorted(rows):
            w.writerow(rows[d])


def make_row(date, res, track=132) -> dict:
    frac = res["water_km2"] / res["valid_km2"] if res["valid_km2"] else float("nan")
    return dict(date=date, water_km2=round(res["water_km2"], 2), water_frac=round(frac, 4),
                valid_km2=round(res["valid_km2"], 2), threshold_db=round(res["threshold_db"], 2),
                track=track, source="NISAR_L2_GCOV_PROVISIONAL_V1",
                water_km2_fixed=round(res["water_km2_fixed"], 2))


def date_from_name(name: str) -> str:
    """ISO date of the acquisition start from a NISAR granule name."""
    import re
    m = re.search(r"_(\d{8})T\d{6}_", Path(name).name)
    if not m:
        raise ValueError(f"no acquisition date in {name}")
    d = m.group(1)
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def track_from_name(name: str) -> int:
    from .nisar_search import parse_title
    return int(parse_title(Path(name).stem)["track"])


def cache_path(date: str) -> Path:
    return CACHE_DIR / f"{date}_HHHH_20m_aoi.tif"


def load_hh(source, cfg) -> tuple[np.ndarray, object, str]:
    """AOI window of HHHH (linear, 20 m) from a local .h5, a remote file object or the cache."""
    import h5py
    import rasterio

    from .gcov import read_subset, write_tif

    date = date_from_name(source.name)
    cp = cache_path(date)
    if cp.exists():
        with rasterio.open(cp) as r:
            return r.read(1), r.transform, r.crs.to_string()
    src = source.fobj if hasattr(source, "fobj") else source
    n = cfg["nisar"]
    with h5py.File(src, "r") as h5:
        arrays, transform, crs = read_subset(h5, cfg["bbox"], n["frequency"], ("HHHH",))
    write_tif(cp, arrays["HHHH"], transform, crs)
    return arrays["HHHH"], transform, crs


def process_file(path, cfg=None, downsample: int = 1) -> dict:
    """One granule (local .h5, remote, or cached AOI tif) -> CSV row (upserted) + QC histogram.

    Area uses the native 20 m grid by default: block-averaging to 40 m mixes shoreline and
    narrow channels with land and cut the 2026-07-17 area from 377 to 289 km2.
    """
    from rasterio.transform import Affine

    from .config import load_config
    from .gcov import block_mean

    cfg = cfg or load_config()
    pr = cfg["processing"]
    bounds = tuple(pr["water_threshold_db_bounds"])
    hh, transform, crs = load_hh(path, cfg)
    hh = block_mean(hh, downsample)
    transform = transform * Affine.scale(downsample)
    res = water_for_date(hh, transform, crs, cfg["bbox"], bounds, pr["speckle_window"])
    date = date_from_name(path.name)
    if res["valid_frac"] < MIN_VALID_FRAC:
        print(f"{date}: so {res['valid_frac']:.0%} do AOI com HH valido (zeros/fora da faixa); "
              "data ignorada")
        return dict(row=None, res=res)
    row = make_row(date, res, track_from_name(path.name))
    upsert_row(row)
    save_histogram(QC_DIR / f"nisar_hh_hist_{date}.png", res["hh_db"], res["threshold_db"],
                   res["otsu_db"], date, bounds)
    print(f"{date}: limiar {res['threshold_db']:.2f} dB ({res['method']}, Otsu "
          f"{res['otsu_db']:.2f}), agua {row['water_km2']} km2 (fixo {FIXED_THRESHOLD_DB}: "
          f"{row['water_km2_fixed']} km2) de {row['valid_km2']} km2 validos", flush=True)
    return dict(row=row, res=res)


class _Named:
    """Granule handle: name (for date/track) plus an optional remote file object."""
    def __init__(self, name, fobj=None):
        self.name, self.fobj = name, fobj


def run_stream(dates: list[str] | None = None) -> None:
    """Read only the AOI window of each track-132 granule over HTTPS (no full download).
    Windows are cached in data/processed/nisar/ so reprocessing does not hit the network."""
    import earthaccess

    from .config import load_config, load_env
    from .gcov import _find_granules, _has_env

    load_env()
    earthaccess.login(strategy="environment" if _has_env() else "interactive")
    cfg = load_config()
    cfg["nisar"]["dates"] = dates or cfg["nisar"]["dates"]
    for d, g in _find_granules(cfg).items():
        name = g["umm"]["GranuleUR"] + ".h5"
        if cache_path(d).exists():
            process_file(_Named(name), cfg)
            continue
        fobj = earthaccess.open([g], show_progress=False, open_kwargs={
            "block_size": 16 * 2**20, "cache_type": "blockcache"})[0]
        try:
            process_file(_Named(name, fobj), cfg)
        finally:
            fobj.close()


def run(paths: list[str], stream_dates: list[str] | None = None) -> None:
    if stream_dates is not None:
        return run_stream(stream_dates)
    from .config import RAW
    files = [Path(p) for p in paths] or sorted((RAW / "nisar").glob("NISAR_L2_*GCOV*.h5"))
    if not files:
        raise SystemExit("nenhum .h5 em data/raw/nisar/")
    for f in files:
        process_file(f)

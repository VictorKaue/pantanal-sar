"""Open-water area time series from SAR backscatter (NISAR GCOV HH; ready for Sentinel-1 RTC).

Per date: Lee filter on linear backscatter -> dB -> threshold -> open-water mask ->
area in km2 inside the AOI bbox (valid pixels only). NISAR writes one row per date to
data/series/nisar.csv (docs/DATA_CONTRACT.md v2, section 1), a QC histogram to data/qc/ and map layers to web/data/layers/.

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

SERIES_V2 = ROOT / "data" / "series" / "nisar.csv"           # contract v2, section 1
QC_DIR = ROOT / "data" / "qc"
LAYERS_DIR = ROOT / "web" / "data" / "layers"
FIELDS = ["date", "water_km2", "water_frac", "valid_km2", "threshold_db", "track", "source",
          "water_km2_fixed"]
FIELDS_V2 = ["date", "source", "sensor", "water_km2", "water_partial_km2", "valid_km2",
             "valid_frac", "method", "quality", "product",
             # extras (allowed by the contract; the model ignores them)
             "water_km2_date_thr", "threshold_db", "threshold_method", "track",
             "water_km2_lo", "water_km2_hi"]
# Threshold sensitivity: water_km2_lo = HH < FIXED - 1 dB (stricter, less water),
# water_km2_hi = HH < FIXED + 1 dB (looser, more water).
SENSITIVITY_DB = 1.0
PRODUCT = "NISAR_L2_GCOV_PROVISIONAL_V1"
# quality: ok >= 0.8, low [0.6, 0.8), drop < 0.6 (same rule as opera_dswx_s1.csv, Baia)
OK_VALID_FRAC, LOW_VALID_FRAC = 0.8, 0.6
# Starting bounds (dB) for the per-date threshold on Sentinel-1 RTC gamma0 (C-band). Not
# tuned yet: confirm on the histogram as was done for NISAR HH.
S1_BOUNDS_DB = {"VV": (-24.0, -13.0), "VH": (-30.0, -18.0)}
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
    top = h.max()
    peaks = [i for i in range(1, len(h) - 1) if h[i] > h[i - 1] and h[i] >= h[i + 1]
             and h[i] > 0.002 * top]
    if len(peaks) < 2:
        return None
    water = peaks[0]  # lowest-dB peak
    # land = highest peak to the right of the water peak (water may be the global maximum
    # in a flood-season scene, so the land peak is not always argmax)
    land = max(peaks[1:], key=lambda i: h[i])
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


def backscatter_db(lin: np.ndarray, speckle: int | None = 5) -> np.ndarray:
    """Linear power (gamma0/sigma0) -> dB, after a Lee filter when speckle > 1.
    Values <= 0 or NaN are no data (provisional NISAR uses 0 inside the swath)."""
    a = np.where(np.isfinite(lin) & (lin > 0), lin, np.nan).astype("float32")
    if speckle and speckle > 1:
        a = change.lee_filter(a, speckle)
    return change.to_db(a)


def water_from_db(img_db, transform, crs, bbox, threshold_db: float | None = None,
                  bounds=(-24.0, -14.0)) -> dict:
    """Generic open water by a dB threshold, for any SAR band (NISAR HH, Sentinel-1 VV/VH).

    img_db: backscatter in dB on a projected grid (metres), NaN = no data.
    threshold_db: fixed threshold; None = per-image valley/Otsu clipped to `bounds`.
    Water = img_db < threshold (open water is dark), followed by a 1-pixel opening.
    Returns db (NaN outside bbox), water, valid, threshold_db, method, otsu_db, water_km2,
    valid_km2, bbox_km2, valid_frac.
    """
    inside = bbox_mask(img_db.shape, transform, crs, bbox)
    db = np.where(inside, img_db, np.nan)
    if threshold_db is None:
        thr, method, otsu = choose_threshold(db, bounds)
    else:
        thr, method, otsu = float(threshold_db), "fixed", float("nan")
    water = change.open_water(db, thr) & inside
    valid = np.isfinite(db)
    px_km2 = abs(transform.a * transform.e) / 1e6
    n_in = int(inside.sum())
    return dict(db=db, water=water, valid=valid, threshold_db=thr, method=method, otsu_db=otsu,
                water_km2=float(water.sum() * px_km2), valid_km2=float(valid.sum() * px_km2),
                bbox_km2=n_in * px_km2, valid_frac=float(valid.sum() / n_in) if n_in else 0.0)


def water_for_date(hh_lin, transform, crs, bbox, bounds=(-24.0, -14.0), speckle=5):
    """NISAR HH: per-date threshold and the fixed FIXED_THRESHOLD_DB on the same filtered image."""
    hh_db = backscatter_db(hh_lin, speckle)
    per = water_from_db(hh_db, transform, crs, bbox, None, bounds)
    fix = water_from_db(hh_db, transform, crs, bbox, FIXED_THRESHOLD_DB)
    lo = water_from_db(hh_db, transform, crs, bbox, FIXED_THRESHOLD_DB - SENSITIVITY_DB)
    hi = water_from_db(hh_db, transform, crs, bbox, FIXED_THRESHOLD_DB + SENSITIVITY_DB)
    return dict(hh_db=per["db"], water=per["water"], valid=per["valid"],
                threshold_db=per["threshold_db"], method=per["method"], otsu_db=per["otsu_db"],
                water_km2=per["water_km2"], water_fixed=fix["water"],
                water_km2_fixed=fix["water_km2"], water_km2_lo=lo["water_km2"],
                water_km2_hi=hi["water_km2"], valid_km2=per["valid_km2"],
                bbox_km2=per["bbox_km2"], valid_frac=per["valid_frac"])


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


def upsert_row(row: dict, path: Path = SERIES_V2, fields=FIELDS_V2) -> None:
    rows = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            rows = {r["date"]: {k: r.get(k, "") for k in fields} for r in csv.DictReader(f)}
    rows[row["date"]] = {k: row.get(k, "") for k in fields}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for d in sorted(rows):
            w.writerow(rows[d])


def make_row(date, res, track=132) -> dict:
    frac = res["water_km2"] / res["valid_km2"] if res["valid_km2"] else float("nan")
    return dict(date=date, water_km2=round(res["water_km2"], 2), water_frac=round(frac, 4),
                valid_km2=round(res["valid_km2"], 2), threshold_db=round(res["threshold_db"], 2),
                track=track, source="NISAR_L2_GCOV_PROVISIONAL_V1",
                water_km2_fixed=round(res["water_km2_fixed"], 2))


def quality(valid_frac: float) -> str:
    if valid_frac >= OK_VALID_FRAC:
        return "ok"
    return "low" if valid_frac >= LOW_VALID_FRAC else "drop"


def make_row_v2(date, res, track=132) -> dict:
    """Contract v2 row: water_km2 = fixed threshold (comparable across dates)."""
    return dict(date=date, source="nisar", sensor="NISAR L-band",
                water_km2=round(res["water_km2_fixed"], 2), water_partial_km2="",
                valid_km2=round(res["valid_km2"], 2), valid_frac=round(res["valid_frac"], 4),
                method=f"HH<{FIXED_THRESHOLD_DB:g}dB", quality=quality(res["valid_frac"]),
                product=PRODUCT, water_km2_date_thr=round(res["water_km2"], 2),
                threshold_db=round(res["threshold_db"], 2), threshold_method=res["method"],
                track=track, water_km2_lo=round(res["water_km2_lo"], 2),
                water_km2_hi=round(res["water_km2_hi"], 2))


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


def process_file(path, cfg=None, downsample: int = 1, export_layers: bool = True) -> dict:
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
    track = track_from_name(path.name)
    row = make_row_v2(date, res, track)
    upsert_row(row, SERIES_V2, FIELDS_V2)
    if res["valid_frac"] < MIN_VALID_FRAC:
        print(f"{date}: so {res['valid_frac']:.0%} do AOI com HH valido (zeros/fora da faixa); "
              "quality=drop")
        return dict(row=None, res=res)
    if export_layers:
        export_date_layers(date, res, transform, crs, cfg["bbox"])
    save_histogram(QC_DIR / f"nisar_hh_hist_{date}.png", res["hh_db"], res["threshold_db"],
                   res["otsu_db"], date, bounds)
    print(f"{date}: limiar {res['threshold_db']:.2f} dB ({res['method']}, Otsu "
          f"{res['otsu_db']:.2f}), agua por data {row['water_km2_date_thr']} km2; fixo "
          f"{FIXED_THRESHOLD_DB}: {row['water_km2']} km2 (lo {row['water_km2_lo']}, hi "
          f"{row['water_km2_hi']}) de {row['valid_km2']} km2 validos", flush=True)
    return dict(row=row, res=res)


# ---------------------------------------------------------------- map layers (contract v1/v2)
LAYER_RES_DEG = 0.0005      # ~55 m: water overlay, not the analysis grid (20 m)
HH_LAYER_RES_DEG = 0.001    # ~110 m: HH backdrop, 8-bit palette PNG (<= ~1 MB for GitHub Pages)
DB_RANGE = (-25.0, 0.0)     # grey stretch of the HH layer
WATER_RGBA = (30, 110, 230, 190)


def _bbox_grid(bbox, res=LAYER_RES_DEG):
    from rasterio.transform import from_origin
    w, s, e, n = bbox
    width, height = int(round((e - w) / res)), int(round((n - s) / res))
    return from_origin(w, n, res, res), width, height


def _warp(a, transform, crs, bbox, resampling, res=LAYER_RES_DEG):
    from rasterio.warp import Resampling, reproject
    dt, w, h = _bbox_grid(bbox, res)
    out = np.full((h, w), np.nan, "float32")
    reproject(a.astype("float32"), out, src_transform=transform, src_crs=crs, src_nodata=np.nan,
              dst_transform=dt, dst_crs="EPSG:4326", dst_nodata=np.nan,
              resampling=getattr(Resampling, resampling))
    return out


def layer_images(res, transform, crs, bbox):
    """(HH palette image, water RGBA array), each on a regular lon/lat grid matching bbox exactly.
    HH: HH_LAYER_RES_DEG, mean dB stretched over DB_RANGE to palette indices 1-255 (grey),
    index 0 = transparent (no data). Water: LAYER_RES_DEG, share of 20 m water pixels >= 0.5."""
    from PIL import Image
    db = _warp(res["hh_db"], transform, crs, bbox, "average", HH_LAYER_RES_DEG)
    g = np.clip((db - DB_RANGE[0]) / (DB_RANGE[1] - DB_RANGE[0]), 0, 1)
    idx = np.where(np.isfinite(db), 1 + np.round(np.nan_to_num(g) * 254), 0).astype("uint8")
    hh = Image.fromarray(idx, "P")
    hh.putpalette([0, 0, 0] + [v for i in range(255) for v in (round(i * 255 / 254),) * 3])
    hh.info["transparency"] = 0
    frac = _warp(np.where(res["valid"], res["water_fixed"], np.nan), transform, crs, bbox, "average")
    wat = np.zeros(frac.shape + (4,), "uint8")
    wat[np.nan_to_num(frac) >= 0.5] = WATER_RGBA
    return hh, wat


def leaflet_bounds(bbox):
    w, s, e, n = bbox
    return [[s, w], [n, e]]


def export_date_layers(date, res, transform, crs, bbox, out_dir: Path = LAYERS_DIR) -> list[dict]:
    """Write <date>_nisar_hh.png and <date>_nisar_open_water.png + layers/nisar_layers.json."""
    from PIL import Image
    hh, wat = layer_images(res, transform, crs, bbox)
    out_dir.mkdir(parents=True, exist_ok=True)
    hh.save(out_dir / f"{date}_nisar_hh.png", optimize=True, transparency=0)
    Image.fromarray(wat, "RGBA").save(out_dir / f"{date}_nisar_open_water.png", optimize=True)
    b = leaflet_bounds(bbox)
    layers = [
        {"id": f"{date}_nisar_hh", "type": "backscatter", "date": date, "source": "nisar",
         "origin": "measured", "label_pt": "Radar NISAR (HH, dB)", "label_en": "NISAR radar (HH, dB)",
         "file": f"layers/{date}_nisar_hh.png", "bounds": b,
         "value_range_db": list(DB_RANGE), "resolution_deg": HH_LAYER_RES_DEG},
        {"id": f"{date}_nisar_open_water", "type": "open_water", "date": date, "source": "nisar",
         "origin": "measured", "label_pt": "Água aberta (NISAR)", "label_en": "Open water (NISAR)",
         "color": "rgba(%d,%d,%d,%.2f)" % (*WATER_RGBA[:3], WATER_RGBA[3] / 255),
         "file": f"layers/{date}_nisar_open_water.png", "bounds": b,
         "method": f"HH<{FIXED_THRESHOLD_DB:g}dB", "water_km2": round(res["water_km2_fixed"], 2),
         "resolution_deg": LAYER_RES_DEG},
    ]
    _upsert_layers(layers, out_dir / "nisar_layers.json")
    return layers


def _upsert_layers(new: list[dict], path: Path) -> None:
    import json
    old = json.loads(path.read_text()) if path.exists() else []
    ids = {x["id"] for x in new}
    allx = [x for x in old if x["id"] not in ids] + new
    allx.sort(key=lambda x: (x["date"], x["type"]))
    path.write_text(json.dumps(allx, indent=1, ensure_ascii=False))


def update_manifest(layers_json: Path = LAYERS_DIR / "nisar_layers.json",
                    manifest: Path = ROOT / "web" / "data" / "manifest.json") -> None:
    """Replace the manifest's NISAR layers and `dates` with the real ones; other keys untouched.
    Old layers without source == 'nisar' (demo, v1) are removed."""
    import json
    layers = json.loads(layers_json.read_text())
    m = json.loads(manifest.read_text()) if manifest.exists() else {}
    m["layers"] = [x for x in m.get("layers", []) if x.get("source") not in
                   ("nisar", "measured", "derived")] + layers
    m["dates"] = sorted({x["date"] for x in layers})
    manifest.write_text(json.dumps(m, indent=1, ensure_ascii=False))


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


def run_cached(cfg=None) -> None:
    """Reprocess every cached AOI window (data/processed/nisar/*_HHHH_20m_aoi.tif): series v2,
    legacy CSV, histograms and web layers. No network."""
    from .config import load_config
    cfg = cfg or load_config()
    tifs = sorted(CACHE_DIR.glob("*_HHHH_20m_aoi.tif"))
    if not tifs:
        raise SystemExit("sem recortes em data/processed/nisar/; rode water-series --stream")
    track, frame = cfg["nisar"]["track"], cfg["nisar"]["frame"]
    for t in tifs:
        d = t.name[:10].replace("-", "")
        name = f"NISAR_L2_PR_GCOV_000_{track:03d}_A_{frame:03d}_2005_DHDH_A_{d}T000000_x.h5"
        process_file(_Named(name), cfg)
    update_manifest()

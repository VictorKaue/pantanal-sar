"""Open-water series from Sentinel-1 RTC (OPERA_L2_RTC-S1_V1) -> data/series/s1_rtc.csv (contract v2).

Input (written by Baia): data/processed/s1_rtc/<AAAA-MM-DD>_VV.tif and _VH.tif, gamma0 in
linear power (as in OPERA RTC-S1), any projected CRS, NaN or 0 = no data; index.csv there
lists date, tracks and valid_frac_vv. Each date is one relative orbit (track) and covers a
different share of the bbox (T039 ~85%, T141 ~51%), so water_km2 is only comparable within a
footprint: the `track` column is kept and quality follows valid_frac (drop < 0.6).

Method (same as NISAR, see water_series.water_from_db):
  1. Pick calibration dates: wet season (Mar-May) and dry season (Aug-Oct) of each year,
     preferring the dates with the largest valid_frac (index.csv).
  2. For VV and VH, valley threshold of the Lee-filtered dB histogram on each calibration date.
  3. Pick the polarization with a valley on more calibration dates (tie: deeper valleys).
  4. ONE fixed threshold for the whole series = median of that polarization's valleys.
  5. water_km2 per date = pixels below the fixed threshold inside the AOI bbox.

Validation (data/qc/s1_validation.csv): F1/kappa against OPERA DSWx-S1 (same day, from
2024-08) and against NISAR (track 132, nearest S1 date within MAX_PAIR_DAYS), on the 30 m
OPERA AOI grid (EPSG:32621).
"""

from __future__ import annotations

import csv
import re
import statistics
from datetime import date as _date
from pathlib import Path

import numpy as np

from . import water_series as ws
from .config import ROOT

S1_DIR = ROOT / "data" / "processed" / "s1_rtc"
DSWX_S1_DIR = ROOT / "data" / "processed" / "opera_dswx_s1"   # <date>_WTR.tif (DSWx-S1 classes)
SERIES_CSV = ROOT / "data" / "series" / "s1_rtc.csv"
VALIDATION_CSV = ROOT / "data" / "qc" / "s1_validation.csv"
CALIB_JSON = ROOT / "data" / "qc" / "s1_threshold.json"
PRODUCT = "OPERA_L2_RTC-S1_V1"
WET_MONTHS, DRY_MONTHS = (3, 4, 5), (8, 9, 10)
PER_SEASON = 2           # calibration dates per season and year
MAX_PAIR_DAYS = 3        # S1 vs NISAR pairing window
SPECKLE = 5
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(VV|VH)\.tif$")


# ---------------------------------------------------------------- io
def read_index(d: Path = S1_DIR) -> dict[str, dict]:
    """index.csv from Baia: {date: {"track": "T039", "valid_frac": 0.85}} (empty if absent)."""
    p = d / "index.csv"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return {r["date"]: {"track": r.get("tracks", ""),
                            "valid_frac": float(r.get("valid_frac_vv") or 0)}
                for r in csv.DictReader(f)}


def list_dates(d: Path = S1_DIR) -> list[str]:
    """Dates with both VV and VH."""
    found: dict[str, set] = {}
    for f in d.glob("*.tif"):
        m = _DATE.match(f.name)
        if m:
            found.setdefault(m.group(1), set()).add(m.group(2))
    dates = sorted(k for k, v in found.items() if {"VV", "VH"} <= v)
    idx = read_index(d)
    # with an index, only dates Baia has registered (a file without index row is not final)
    return [x for x in dates if x in idx] if idx else dates


def load(date: str, pol: str, d: Path = S1_DIR):
    import rasterio
    with rasterio.open(d / f"{date}_{pol}.tif") as r:
        return r.read(1).astype("float32"), r.transform, r.crs.to_string()


def load_db(date: str, pol: str, d: Path = S1_DIR):
    lin, t, crs = load(date, pol, d)
    return ws.backscatter_db(lin, SPECKLE), t, crs


def bbox_area_km2(bbox) -> float:
    """Geodesic area of the AOI bbox (denominator of valid_frac, same for every source)."""
    R = 6371.0072  # authalic radius (km); error < 0.1% at this size
    w, s, e, n = bbox
    return abs(R**2 * np.radians(e - w) * (np.sin(np.radians(n)) - np.sin(np.radians(s))))


# ---------------------------------------------------------------- threshold
def calibration_dates(dates: list[str], per_season: int = PER_SEASON,
                      valid: dict[str, float] | None = None) -> dict[str, list[str]]:
    """Up to `per_season` dates per (year, season). With `valid` ({date: valid_frac}), only the
    dates with the largest coverage are candidates; then spread over the season."""
    out = {"wet": [], "dry": []}
    groups: dict[tuple, list[str]] = {}
    for d in dates:
        m = int(d[5:7])
        season = "wet" if m in WET_MONTHS else "dry" if m in DRY_MONTHS else None
        if season:
            groups.setdefault((d[:4], season), []).append(d)
    for (_, season), ds in sorted(groups.items()):
        if valid:
            best = max(valid.get(x, 0) for x in ds)
            ds = [x for x in ds if valid.get(x, 0) >= best - 0.05]
        idx = np.unique(np.linspace(0, len(ds) - 1, min(per_season, len(ds))).round().astype(int))
        out[season] += [ds[i] for i in idx]
    return out


def valley_depth(db: np.ndarray, t: float) -> float:
    """1 - h(valley)/h(water peak) on the smoothed histogram (0 = no dip, 1 = empty valley)."""
    from scipy.ndimage import gaussian_filter1d
    counts, centers = ws.histogram(db)
    h = gaussian_filter1d(counts.astype(float), 0.5 / ws.BIN)
    vi = int(np.argmin(abs(centers - t)))
    peak = h[:vi].max() if vi > 0 else 0
    return float(1 - h[vi] / peak) if peak > 0 else 0.0


def calibrate(dates: list[str], bbox, d: Path = S1_DIR, bounds=ws.S1_BOUNDS_DB) -> dict:
    """Choose polarization and one fixed threshold from wet/dry calibration dates."""
    idx = read_index(d)
    cal = calibration_dates(dates, valid={k: v["valid_frac"] for k, v in idx.items()})
    per = {"VV": [], "VH": []}
    for season, ds in cal.items():
        for date in ds:
            for pol in ("VV", "VH"):
                db, t, crs = load_db(date, pol, d)
                db = np.where(ws.bbox_mask(db.shape, t, crs, bbox), db, np.nan)
                v = ws.valley_threshold(db, bounds[pol])
                per[pol].append({"date": date, "season": season, "valley_db": v,
                                 "depth": valley_depth(db, v) if v is not None else 0.0})
                _hist(db, v, date, pol, bounds[pol])
    score = {p: (sum(x["valley_db"] is not None for x in r),
                 float(np.mean([x["depth"] for x in r])) if r else 0.0) for p, r in per.items()}
    pol = max(score, key=lambda p: score[p])
    vals = [x["valley_db"] for x in per[pol] if x["valley_db"] is not None]
    if not vals:
        raise SystemExit(f"nenhum vale no histograma de {pol} nas datas de calibracao: revisar")
    thr = round(statistics.median(vals), 2)
    return {"pol": pol, "threshold_db": thr, "score": score, "calibration": per,
            "dates": cal}


def _hist(db, thr, date, pol, bounds):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    counts, centers = ws.histogram(db)
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.fill_between(centers, counts, step="mid", color="0.6")
    if thr is not None:
        ax.axvline(thr, color="tab:blue", label=f"vale {thr:.1f} dB")
    ax.axvspan(*bounds, color="tab:blue", alpha=0.08, label="limites")
    ax.set_yscale("log")
    ax.set_xlabel(f"{pol} gamma0 (dB), Lee 5x5")
    ax.set_title(f"Sentinel-1 RTC {pol}, {date}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    p = ws.QC_DIR / "s1" / f"s1_{pol}_hist_{date}.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(p, dpi=100)
    plt.close(fig)


# ---------------------------------------------------------------- series
def row(date, res, pol, thr, bbox_km2, track="") -> dict:
    vf = res["valid_km2"] / bbox_km2 if bbox_km2 else 0.0
    return dict(date=date, source="s1_rtc", sensor="Sentinel-1 C-band",
                water_km2=round(res["water_km2"], 2), water_partial_km2="",
                valid_km2=round(res["valid_km2"], 2), valid_frac=round(min(vf, 1.0), 4),
                method=f"{pol}<{thr:g}dB", quality=ws.quality(vf), product=PRODUCT,
                threshold_db=thr, pol=pol, track=track,
                water_frac=round(res["water_km2"] / res["valid_km2"], 5) if res["valid_km2"] else "")


FOOTPRINT_TOL = 0.97  # valid_frac below 97% of the track's median footprint -> drop


def footprint_quality(rows: list[dict]) -> list[dict]:
    """water_km2 is only comparable on the same footprint: a date of a track with fewer bursts
    than usual (e.g. 2026-10-12, T039, 10 of 14 bursts) is marked drop."""
    by: dict[str, list[float]] = {}
    for r in rows:
        by.setdefault(r["track"], []).append(r["valid_frac"])
    med = {k: statistics.median(v) for k, v in by.items()}
    for r in rows:
        if r["track"] and r["valid_frac"] < FOOTPRINT_TOL * med[r["track"]]:
            r["quality"] = "drop"
    return rows


FIELDS = ws.FIELDS_V2[:10] + ["threshold_db", "pol", "track", "water_frac", "flag"]
# Same-day check against DSWx-S1: F1 below this with false positives > false negatives means
# the fixed VH threshold is catching dry, smooth or burned ground (dark in VV and VH), as in the
# 2024 Sep-Oct drought and fire season. Such dates get quality=low and a flag.
FLAG_F1 = 0.5


def water_mask(date, pol, thr, bbox, d: Path = S1_DIR):
    db, t, crs = load_db(date, pol, d)
    return ws.water_from_db(db, t, crs, bbox, threshold_db=thr), t, crs


def run(cfg=None, d: Path = S1_DIR, out: Path = SERIES_CSV) -> dict:
    import json

    from .config import load_config
    cfg = cfg or load_config()
    bbox = cfg["bbox"]
    dates = list_dates(d)
    if not dates:
        raise SystemExit(f"sem recortes em {d} (<data>_VV.tif e _VH.tif)")
    cal = calibrate(dates, bbox, d)
    pol, thr = cal["pol"], cal["threshold_db"]
    CALIB_JSON.parent.mkdir(parents=True, exist_ok=True)
    CALIB_JSON.write_text(json.dumps(cal, indent=1))
    print(f"S1: {len(dates)} datas; polarizacao {pol}, limiar fixo {thr} dB "
          f"(score {cal['score']})")
    area = bbox_area_km2(bbox)
    idx = read_index(d)
    rows = []
    for date in dates:
        res, _, _ = water_mask(date, pol, thr, bbox, d)
        rows.append(row(date, res, pol, thr, area, idx.get(date, {}).get("track", "")))
    for r in footprint_quality(rows):
        ws.upsert_row(r, out, FIELDS)
    print(f"-> {out}")
    return cal


# ---------------------------------------------------------------- validation
def to_grid(values: np.ndarray, transform, crs, bbox) -> np.ndarray:
    """Float raster (1 water, 0 not water, NaN invalid) -> 30 m OPERA AOI grid; >= 0.5 = water."""
    from rasterio.transform import Affine
    from rasterio.warp import Resampling, reproject

    from .opera import PIXEL, aoi_grid
    left, top, nc, nr = aoi_grid(bbox)
    out = np.full((nr, nc), np.nan, "float32")
    reproject(values.astype("float32"), out, src_transform=transform, src_crs=crs,
              src_nodata=np.nan, dst_transform=Affine(PIXEL, 0, left, 0, -PIXEL, top),
              dst_crs="EPSG:32621", dst_nodata=np.nan, resampling=Resampling.average)
    return np.where(np.isfinite(out), (out >= 0.5).astype("float32"), np.nan)


def agreement(a: np.ndarray, b: np.ndarray) -> dict:
    """F1 and Cohen's kappa of two 0/1/NaN masks on the same grid (water = positive class)."""
    m = np.isfinite(a) & np.isfinite(b)
    A, B = a[m] == 1, b[m] == 1
    tp, fp, fn = int((A & B).sum()), int((A & ~B).sum()), int((~A & B).sum())
    tn = int(m.sum()) - tp - fp - fn
    n = tp + fp + fn + tn
    if n == 0:
        return dict(n=0, f1=float("nan"), kappa=float("nan"), tp=0, fp=0, fn=0, tn=0)
    po = (tp + tn) / n
    pe = ((tp + fp) * (tp + fn) + (fn + tn) * (fp + tn)) / n**2
    f1 = 2 * tp / (2 * tp + fp + fn) if (tp + fp + fn) else float("nan")
    kappa = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    return dict(n=n, f1=round(f1, 4), kappa=round(kappa, 4), tp=tp, fp=fp, fn=fn, tn=tn)


def _as_float(res) -> np.ndarray:
    return np.where(res["valid"], res["water"].astype("float32"), np.nan)


def dswx_s1(date: str, d: Path = DSWX_S1_DIR):
    """DSWx-S1 WTR layer -> (0/1/NaN, transform, crs). 1 = open water; 0 (not water),
    2 (partial) and 3 (inundated vegetation) = not open water; anything else (HAND,
    layover/shadow, snow, cloud, fill) = invalid. None if missing."""
    import rasterio
    p = d / f"{date}_WTR.tif"
    if not p.exists():
        return None
    with rasterio.open(p) as r:
        w = r.read(1)
        return (np.where(w == 1, 1.0, np.where(np.isin(w, (0, 2, 3)), 0.0, np.nan)).astype("float32"),
                r.transform, r.crs.to_string())


def nisar_mask(date: str, bbox):
    import rasterio
    p = ws.cache_path(date)
    if not p.exists():
        return None
    with rasterio.open(p) as r:
        hh, t, crs = r.read(1), r.transform, r.crs.to_string()
    res = ws.water_from_db(ws.backscatter_db(hh, SPECKLE), t, crs, bbox, ws.FIXED_THRESHOLD_DB)
    return _as_float(res), t, crs


def nisar_dates() -> list[str]:
    return sorted(p.name[:10] for p in ws.CACHE_DIR.glob("*_HHHH_20m_aoi.tif"))


def validate(cfg=None, d: Path = S1_DIR, dswx_dir: Path = DSWX_S1_DIR,
             out: Path = VALIDATION_CSV, series: Path = SERIES_CSV) -> list[dict]:
    import json

    from .config import load_config
    cfg = cfg or load_config()
    bbox = cfg["bbox"]
    cal = json.loads(CALIB_JSON.read_text())
    pol, thr = cal["pol"], cal["threshold_db"]
    s1_dates = list_dates(d)
    idx = read_index(d)
    rows = []

    def s1_grid(date):
        res, t, crs = water_mask(date, pol, thr, bbox, d)
        return to_grid(_as_float(res), t, crs, bbox)

    for date in s1_dates:
        if date < "2024-08-01":
            continue
        ref = dswx_s1(date, dswx_dir)
        if ref is None:
            continue
        r = agreement(s1_grid(date), to_grid(*ref, bbox))
        rows.append(dict(s1_date=date, ref="opera_dswx_s1", ref_date=date, gap_days=0,
                         track=idx.get(date, {}).get("track", ""), **r))
    for nd in nisar_dates():
        near = [(abs((_date.fromisoformat(s) - _date.fromisoformat(nd)).days), s) for s in s1_dates]
        near = [x for x in near if x[0] <= MAX_PAIR_DAYS]
        if not near:
            continue
        nm = nisar_mask(nd, bbox)
        if nm is None:
            continue
        ng = to_grid(*nm, bbox)
        for gap, s in sorted(near):  # every S1 date in the window (one per track)
            r = agreement(s1_grid(s), ng)
            rows.append(dict(s1_date=s, ref="nisar", ref_date=nd, gap_days=gap,
                             track=idx.get(s, {}).get("track", ""), **r))
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["s1_date", "ref", "ref_date", "gap_days", "track", "n", "f1", "kappa", "tp", "fp", "fn", "tn"]
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    flag_vs_dswx(rows, series)
    for ref in ("opera_dswx_s1", "nisar"):
        rr = [x for x in rows if x["ref"] == ref and np.isfinite(x["f1"])]
        if rr:
            print(f"S1 x {ref}: {len(rr)} pares, F1 mediano {np.median([x['f1'] for x in rr]):.2f}, "
                  f"kappa mediano {np.median([x['kappa'] for x in rr]):.2f}")
        else:
            print(f"S1 x {ref}: nenhum par disponivel")
    return rows


HLS_CSV = ROOT / "data" / "series" / "opera_dswx_hls.csv"
HLS_MAX_GAP = 3      # days between S1 and an optical DSWx-HLS scene (quality ok)
HLS_EXCESS = 1.5     # S1/HLS ratio above 1.5x the track's median ratio = excess ...
LEVEL_EXCESS = 1.3   # ... and S1 water above 1.3x the track's median water (a low optical
                     # value alone, e.g. 2026-04-08, must not flag a normal S1 date)


def hls_ratio_excess(rows: list[dict], hls: Path = HLS_CSV) -> set[str]:
    """Dates whose S1/HLS water ratio is > HLS_EXCESS x the median ratio of the same track.
    The S1 footprint (one track) is smaller than the bbox, so the ratio, not the area, is
    compared; the median per track is the normal relation between the two sensors."""
    if not hls.exists():
        return set()
    with open(hls, encoding="utf-8") as f:
        ref = {r["date"]: float(r["water_km2"]) for r in csv.DictReader(f)
               if r.get("quality") == "ok" and float(r["water_km2"] or 0) > 0}
    rdates = sorted(ref)
    ratios: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        if not r.get("track") or r.get("quality") == "drop":
            continue  # footprint drops (T141, partial bursts) are not comparable
        d0 = _date.fromisoformat(r["date"])
        near = [(abs((_date.fromisoformat(x) - d0).days), x) for x in rdates
                if abs((_date.fromisoformat(x) - d0).days) <= HLS_MAX_GAP]
        if near:
            ratios.setdefault(r["track"], []).append(
                (r["date"], float(r["water_km2"]) / ref[min(near)[1]]))
    level: dict[str, list[float]] = {}
    water = {}
    for r in rows:
        if r.get("track") and r.get("quality") != "drop":
            level.setdefault(r["track"], []).append(float(r["water_km2"]))
            water[r["date"]] = float(r["water_km2"])
    out = set()
    for tr, rr in ratios.items():
        med = statistics.median(x for _, x in rr)
        lvl = statistics.median(level[tr])
        out |= {d for d, x in rr if x > HLS_EXCESS * med and water[d] > LEVEL_EXCESS * lvl}
    return out


def flag_vs_dswx(val_rows: list[dict], series: Path = SERIES_CSV, hls: Path = HLS_CSV) -> list[str]:
    """Drop series dates with excess water: same-day DSWx-S1 F1 < FLAG_F1 with more false
    positives than false negatives (from 2024-08-23), or S1/DSWx-HLS ratio excess (any year).
    drop, not low: Prophet ignores weights, so only drop keeps them out of the model."""
    bad_s1 = {r["s1_date"] for r in val_rows
              if r["ref"] == "opera_dswx_s1" and np.isfinite(float(r["f1"]))
              and float(r["f1"]) < FLAG_F1 and int(r["fp"]) > int(r["fn"])}
    if not series.exists():
        return []
    with open(series, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # idempotent: rebuild quality from coverage before applying the flags again
    for r in rows:
        r["flag"] = ""
        r["valid_frac"] = float(r["valid_frac"])
        r["quality"] = ws.quality(r["valid_frac"])
    footprint_quality(rows)
    bad_hls = hls_ratio_excess(rows, hls)
    for r in rows:
        why = []
        if r["date"] in bad_s1:
            why.append("F1<0,5 vs DSWx-S1 com excesso")
        if r["date"] in bad_hls:
            why.append("razao S1/DSWx-HLS alta")
        if why:
            r["flag"] = "excesso de agua (solo seco/queimado escuro?): " + "; ".join(why)
            r["quality"] = "drop"
    with open(series, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in FIELDS} for r in rows)
    bad = sorted(bad_s1 | bad_hls)
    if bad:
        print(f"S1: {len(bad)} datas com excesso de agua -> quality=drop: {', '.join(bad)}")
    return bad

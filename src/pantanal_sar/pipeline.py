"""End-to-end processing on the AOI cuts in data/processed/nisar/.

Steps
  1. Lee filter + dB for every date (HH and HV).
  2. Water per date: open water (Otsu on HH) + flooded vegetation (experimental).
  3. Per consecutive pair: dry-down (was water, is not) and burn scars
     (HV drop on stable land, confirmed by nearby FIRMS hotspots when available).
  4. Statistics: did areas that dried burn more often than areas that stayed dry
     or stayed wet? Fire reference = MCD64A1, else FIRMS, else NISAR (reported).
  5. Validation: water vs HLS optical; burn vs MCD64A1 (when files exist).
Outputs: data/processed/masks/*.tif and data/processed/stats.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from scipy.stats import chi2_contingency
from sklearn.metrics import cohen_kappa_score, f1_score, precision_score, recall_score

from . import change
from .ancillary import firms_rowcol, hls_water, load_firms, mcd64a1_burned
from .config import PROCESSED, load_config
from .gcov import write_tif


def _load(path: Path, grid=None):
    with rasterio.open(path) as src:
        if grid is None:
            grid = {"shape": (src.height, src.width), "transform": src.transform, "crs": src.crs}
            return src.read(1).astype("float32"), grid
        dst = np.full(grid["shape"], np.nan, dtype="float32")
        reproject(rasterio.band(src, 1), dst, dst_transform=grid["transform"], dst_crs=grid["crs"],
                  resampling=Resampling.bilinear, dst_nodata=np.nan)
        return dst, grid


def load_stack(folder: Path):
    files = sorted(folder.glob("*_HHHH.tif"))
    if not files:
        raise SystemExit(f"No *_HHHH.tif in {folder}. Run `cli fetch-nisar` (or `cli demo`).")
    grid, stack = None, {}
    for f in files:
        d = f.name.split("_")[0]
        hh, grid = _load(f, grid)
        hv_path = f.with_name(f"{d}_HVHV.tif")
        hv = _load(hv_path, grid)[0] if hv_path.exists() else None
        stack[d] = {"hh": hh, "hv": hv}
    return stack, grid


def metrics(pred: np.ndarray, ref: np.ndarray, valid: np.ndarray) -> dict:
    p, r = pred[valid].ravel(), ref[valid].ravel()
    if p.size == 0:
        return {}
    return {
        "precision": round(float(precision_score(r, p, zero_division=0)), 3),
        "recall": round(float(recall_score(r, p, zero_division=0)), 3),
        "f1": round(float(f1_score(r, p, zero_division=0)), 3),
        "kappa": round(float(cohen_kappa_score(r, p)), 3),
        "n_pixels": int(p.size),
    }


def odds_ratio_test(burned, group_a, group_b, spacing: int) -> dict:
    """Burn odds in group A vs group B on a spaced sample (limits spatial autocorrelation)."""
    s = (slice(None, None, spacing), slice(None, None, spacing))
    a, b, f = group_a[s], group_b[s], burned[s]
    t = np.array([[int((f & a).sum()), int((~f & a).sum())],
                  [int((f & b).sum()), int((~f & b).sum())]])
    out = {"table": t.tolist(), "sample_spacing_px": spacing}
    if (t.sum(axis=1) == 0).any() or t[:, 0].sum() == 0:
        out["note"] = "not enough burned or group pixels in the sample"
        return out
    zero = (t == 0).any()
    tc = t + 0.5 if zero else t.astype(float)  # Haldane correction only when a cell is zero
    out["haldane_corrected"] = bool(zero)
    orr = (tc[0, 0] * tc[1, 1]) / (tc[0, 1] * tc[1, 0])
    se = math.sqrt((1 / tc).sum())
    out.update({
        "burn_rate_a": round(t[0, 0] / t[0].sum(), 4),
        "burn_rate_b": round(t[1, 0] / t[1].sum(), 4),
        "odds_ratio": round(orr, 3),
        "ci95": [round(math.exp(math.log(orr) - 1.96 * se), 3), round(math.exp(math.log(orr) + 1.96 * se), 3)],
    })
    if (t > 0).all():
        out["chi2_p_value"] = float(chi2_contingency(t)[1])
    return out


def run(folder: Path | None = None, out_dir: Path | None = None, demo: bool = False) -> dict:
    cfg = load_config()
    pc = cfg["processing"]
    folder = folder or PROCESSED / "nisar"
    out_dir = out_dir or PROCESSED
    masks_dir = out_dir / "masks"
    stack, grid = load_stack(folder)
    dates = sorted(stack)
    px_area = abs(grid["transform"].a * grid["transform"].e)
    firms = load_firms() if not demo else load_firms(folder / "firms_demo.csv")
    buffer_px = pc["firms_buffer_m"] / abs(grid["transform"].a)

    def save(name, arr):
        write_tif(masks_dir / f"{name}.tif", arr.astype("uint8"), grid["transform"], grid["crs"], nodata=255)

    stats = {"aoi": cfg["name"], "dates": dates, "pixel_size_m": abs(grid["transform"].a),
             "demo": demo, "per_date": {}, "per_pair": {}, "validation": {}}
    water, db = {}, {}
    for d in dates:
        hh = change.lee_filter(stack[d]["hh"], pc["speckle_window"])
        hv = change.lee_filter(stack[d]["hv"], pc["speckle_window"]) if stack[d]["hv"] is not None else None
        hh_db, hv_db = change.to_db(hh), change.to_db(hv) if hv is not None else None
        thr = change.water_threshold(hh_db, pc["water_threshold_db_bounds"])
        ow = change.open_water(hh_db, thr)
        fv = change.flooded_vegetation(hh_db, hv_db, pc["flooded_veg_hh_db_min"], pc["flooded_veg_hh_minus_hv_db_min"])
        water[d] = ow | fv
        db[d] = {"hh": hh_db, "hv": hv_db, "hh_lin": hh, "hv_lin": hv}
        save(f"{d}_open_water", ow)
        save(f"{d}_flooded_veg", fv)
        write_tif(masks_dir / f"{d}_HH_db.tif", hh_db, grid["transform"], grid["crs"])
        stats["per_date"][d] = {"water_threshold_db": round(thr, 2),
                                "open_water_km2": round(change.area_km2(ow, px_area), 2),
                                "flooded_veg_km2": round(change.area_km2(fv, px_area), 2)}
        hv_ref = hls_water(grid, d) if not demo else None
        if hv_ref is not None:
            ref, valid = hv_ref
            stats["validation"][f"water_{d}_vs_HLS"] = metrics(ow, ref, valid)

    burned_any = np.zeros(grid["shape"], bool)
    dried_so_far = np.zeros(grid["shape"], bool)
    dried_then_burned = np.zeros(grid["shape"], bool)
    fire_ref = np.zeros(grid["shape"], bool)
    fire_ref_source = set()
    for d0, d1 in zip(dates[:-1], dates[1:]):
        key = f"{d0}_{d1}"
        dr = change.dried(water[d0], water[d1])
        dried_so_far |= dr
        if db[d0]["hv_lin"] is not None and db[d1]["hv_lin"] is not None:
            cand, thr = change.burn_candidates(db[d0]["hv_lin"], db[d1]["hv_lin"], water[d0], water[d1],
                                               pc["burn_hv_drop_sigma"])
        else:
            cand, thr = np.zeros(grid["shape"], bool), float("nan")
        r, c = firms_rowcol(firms, grid, d0, d1)
        # With FIRMS loaded, a scar is kept only if a hotspot touches it in this window.
        # Without FIRMS, candidates are kept but flagged as unconfirmed.
        near = change.near_points(grid["shape"], r, c, buffer_px) if firms else None
        burn = change.confirm_objects(cand, near) if near is not None else cand
        burned_any |= burn
        dried_then_burned |= burn & dried_so_far
        save(f"{key}_dried", dr)
        save(f"{key}_burn", burn)
        pair = {"dried_km2": round(change.area_km2(dr, px_area), 2),
                "burn_km2": round(change.area_km2(burn, px_area), 2),
                "burn_hv_threshold_db": None if math.isnan(thr) else round(thr, 2),
                "firms_hotspots": int(len(r)),
                "burn_confirmed_by_firms": near is not None}
        mcd = mcd64a1_burned(grid, d0, d1) if not demo else None
        if mcd is not None:
            pair["burn_vs_MCD64A1"] = metrics(burn, mcd, np.isfinite(db[d1]["hh"]))
            fire_ref |= mcd
            fire_ref_source.add("MCD64A1")
        else:
            fire_ref |= burn
            fire_ref_source.add("NISAR burn scar" + (" confirmed by FIRMS" if near is not None else " (unconfirmed)"))
        stats["per_pair"][key] = pair
    save("dried_then_burned", dried_then_burned)
    save("burned_any", burned_any)

    valid = np.isfinite(db[dates[0]]["hh"]) & np.isfinite(db[dates[-1]]["hh"])
    w0, w1 = water[dates[0]], water[dates[-1]]
    groups = {"dried": w0 & ~w1 & valid, "stayed_wet": w0 & w1 & valid, "always_dry": ~w0 & ~w1 & valid}
    sp = max(1, int(round(cfg["analysis"]["sample_spacing_m"] / abs(grid["transform"].a))))
    stats["analysis"] = {
        "fire_reference": sorted(fire_ref_source),
        "groups_km2": {k: round(change.area_km2(v, px_area), 2) for k, v in groups.items()},
        "dried_vs_always_dry": odds_ratio_test(fire_ref, groups["dried"], groups["always_dry"], sp),
        "dried_vs_stayed_wet": odds_ratio_test(fire_ref, groups["dried"], groups["stayed_wet"], sp),
        "dried_then_burned_km2": round(change.area_km2(dried_then_burned, px_area), 2),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats["analysis"], indent=2))
    return stats

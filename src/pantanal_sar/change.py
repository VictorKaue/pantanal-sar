"""Pure-numpy change detection: water, flooded vegetation, dry-down and burn scars.

All inputs are linear gamma0 arrays on the same grid (same track, same frame).
Thresholds are computed from the data itself so the method transfers to other areas.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_opening, distance_transform_edt, label, uniform_filter
from skimage.filters import threshold_otsu


def to_db(a: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (10 * np.log10(a)).astype("float32")


def lee_filter(a: np.ndarray, size: int = 5) -> np.ndarray:
    """Basic Lee speckle filter on linear intensity. NaNs are preserved."""
    valid = np.isfinite(a)
    x = np.where(valid, a, 0).astype("float64")
    w = uniform_filter(valid.astype("float64"), size)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = uniform_filter(x, size) / w
        sq = uniform_filter(x * x, size) / w
    var = np.maximum(sq - mean**2, 0)
    noise = np.nanmean(var[valid]) if valid.any() else 0
    with np.errstate(invalid="ignore", divide="ignore"):
        k = var / (var + noise)
    out = mean + k * (x - mean)
    out[~valid] = np.nan
    return out.astype("float32")


def water_threshold(hh_db: np.ndarray, bounds=(-24.0, -14.0)) -> float:
    """Otsu threshold on HH (dB), clipped to physically plausible bounds."""
    v = hh_db[np.isfinite(hh_db)]
    v = v[(v > -35) & (v < 5)]
    t = float(threshold_otsu(v)) if v.size > 100 else float(np.mean(bounds))
    return float(np.clip(t, *bounds))


def open_water(hh_db: np.ndarray, threshold: float) -> np.ndarray:
    m = np.isfinite(hh_db) & (hh_db < threshold)
    return binary_opening(m, iterations=1)


def flooded_vegetation(hh_db, hv_db, hh_min=-2.0, diff_min=8.0) -> np.ndarray:
    """Experimental: double bounce (very bright HH, HH >> HV) under vegetation."""
    if hv_db is None:
        return np.zeros_like(hh_db, dtype=bool)
    return np.isfinite(hh_db) & (hh_db > hh_min) & ((hh_db - hv_db) > diff_min)


def log_ratio_db(after_lin: np.ndarray, before_lin: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (10 * np.log10(after_lin / before_lin)).astype("float32")


def dried(water_before: np.ndarray, water_after: np.ndarray) -> np.ndarray:
    """Pixels that were water and are no longer water (flood recession)."""
    return water_before & ~water_after


def burn_candidates(hv_before, hv_after, water_before, water_after, sigma=2.0):
    """HV drop larger than `sigma` std of the stable-land log-ratio.

    Returns (mask, threshold_db). Water pixels are excluded so that flooding
    (which also lowers backscatter) is not mistaken for fire.
    """
    lr = log_ratio_db(hv_after, hv_before)
    stable = np.isfinite(lr) & ~water_before & ~water_after
    if stable.sum() < 100:
        return np.zeros_like(lr, dtype=bool), float("nan")
    mu, sd = float(np.nanmean(lr[stable])), float(np.nanstd(lr[stable]))
    thr = mu - sigma * sd
    return stable & (lr < thr), thr


def near_points(shape, rows, cols, max_dist_px: float) -> np.ndarray:
    """Boolean mask of pixels within max_dist_px of any (row, col) point."""
    seed = np.ones(shape, dtype=bool)
    r = np.asarray(rows, dtype=int)
    c = np.asarray(cols, dtype=int)
    ok = (r >= 0) & (r < shape[0]) & (c >= 0) & (c < shape[1])
    if not ok.any():
        return np.zeros(shape, dtype=bool)
    seed[r[ok], c[ok]] = False
    return distance_transform_edt(seed) <= max_dist_px


def confirm_objects(candidates: np.ndarray, evidence: np.ndarray, min_px: int = 4) -> np.ndarray:
    """Keep whole connected candidate patches that touch the evidence mask.

    A burn scar is usually much larger than the hotspot buffer, so we keep the
    entire patch when at least one hotspot falls on or near it.
    """
    lab, n = label(candidates)
    if n == 0:
        return np.zeros_like(candidates, dtype=bool)
    hit = np.unique(lab[evidence & candidates])
    sizes = np.bincount(lab.ravel())
    keep = np.zeros(n + 1, dtype=bool)
    keep[hit] = True
    keep[sizes < min_px] = False
    keep[0] = False
    return keep[lab]


def area_km2(mask: np.ndarray, pixel_area_m2: float) -> float:
    return float(mask.sum() * pixel_area_m2 / 1e6)

import numpy as np
from rasterio.transform import Affine

from pantanal_sar import water_series as ws


def test_valley_between_peaks():
    rng = np.random.default_rng(0)
    db = np.concatenate([rng.normal(-22, 1.0, 20000), rng.normal(-8, 1.5, 80000)])
    t = ws.valley_threshold(db, bounds=(-24, -9))
    assert t is not None and -19 < t < -12


def test_unimodal_falls_back_to_otsu():
    rng = np.random.default_rng(1)
    db = rng.normal(-8, 1.5, 50000)
    thr, method, _ = ws.choose_threshold(db, bounds=(-24, -14))
    assert method == "otsu" and -24 <= thr <= -14


def test_area_and_bbox():
    hh = np.full((20, 20), 0.1, "float32")  # -10 dB land
    hh[:10] = 0.003                          # ~-25 dB water, top half
    t = Affine(0.01, 0, -58.0, 0, -0.01, -16.0)  # degrees grid, EPSG:4326
    res = ws.water_for_date(hh, t, "EPSG:4326", [-58.0, -16.2, -57.8, -16.0], bounds=(-24, -12))
    assert res["valid"].all()
    assert 0.3 < res["water"].mean() < 0.6


def test_zero_backscatter_is_invalid():
    hh = np.zeros((20, 20), "float32")       # provisional granule: HH = 0 with mask valid
    hh[:, :5] = 0.1
    hh[hh == 0] = np.nan                      # gcov.read_subset turns <= 0 into NaN
    t = Affine(0.01, 0, -58.0, 0, -0.01, -16.0)
    res = ws.water_for_date(hh, t, "EPSG:4326", [-58.0, -16.2, -57.8, -16.0], bounds=(-24, -12))
    assert res["valid_frac"] < ws.MIN_VALID_FRAC


def test_date_from_name():
    n = "NISAR_L2_PR_GCOV_024_132_A_169_2005_DHDH_A_20260705T094227_20260705T094302_P05023_N_F_J_001.h5"
    assert ws.date_from_name(n) == "2026-07-05" and ws.track_from_name(n) == 132

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


def _utm_scene(rng, water_db, land_db, shape=(200, 200)):
    """Synthetic UTM 21S grid (20 m) centred in the Pantanal; top-left quarter is water."""
    lin = 10 ** (rng.normal(land_db, 1.0, shape) / 10)
    lin[:100, :100] = 10 ** (rng.normal(water_db, 1.0, (100, 100)) / 10)
    t = Affine(20.0, 0, 400000.0, 0, -20.0, 8100000.0)
    return lin.astype("float32"), t


def test_generic_water_sentinel1_vv():
    # Sentinel-1 RTC VV: open water ~ -22 dB, land ~ -9 dB (C-band). Generic function, no NISAR.
    rng = np.random.default_rng(2)
    vv, t = _utm_scene(rng, -22, -9)
    db = ws.backscatter_db(vv, speckle=5)
    big = [-60, -30, -50, -10]  # bbox containing the whole synthetic grid
    auto = ws.water_from_db(db, t, "EPSG:32721", big, None, ws.S1_BOUNDS_DB["VV"])
    fixed = ws.water_from_db(db, t, "EPSG:32721", big, threshold_db=-18.0)
    true_km2 = 100 * 100 * 400 / 1e6  # 4 km2
    for r in (auto, fixed):
        assert abs(r["water_km2"] - true_km2) / true_km2 < 0.05
        assert r["valid_frac"] == 1.0
    assert fixed["method"] == "fixed" and -24 <= auto["threshold_db"] <= -13


def test_generic_water_vh_and_nodata():
    rng = np.random.default_rng(3)
    vh, t = _utm_scene(rng, -28, -16)
    vh[150:, :] = 0  # no data (fill) must not count as water
    db = ws.backscatter_db(vh, speckle=None)
    r = ws.water_from_db(db, t, "EPSG:32721", [-60, -30, -50, -10], threshold_db=-22.0)
    assert abs(r["water_km2"] - 4.0) < 0.3
    assert abs(r["valid_frac"] - 0.75) < 1e-6


def test_v2_row_uses_fixed_threshold():
    res = dict(water_km2=600.0, water_km2_fixed=250.0, valid_km2=11777.5, valid_frac=1.0,
               threshold_db=-14.0, method="otsu", water_km2_lo=200.0, water_km2_hi=320.0)
    row = ws.make_row_v2("2026-08-22", res)
    assert row["water_km2"] == 250.0 and row["water_km2_date_thr"] == 600.0
    assert row["source"] == "nisar" and row["quality"] == "ok" and row["method"] == "HH<-16.75dB"
    assert set(ws.FIELDS_V2[:10]) == {"date", "source", "sensor", "water_km2", "water_partial_km2",
                                      "valid_km2", "valid_frac", "method", "quality", "product"}
    assert ws.quality(0.0) == "drop" and ws.quality(0.7) == "low"
    assert row["water_km2_lo"] == 200.0 and row["water_km2_hi"] == 320.0


def test_sensitivity_bounds_order():
    rng = np.random.default_rng(4)
    db = rng.uniform(-22, -10, (60, 60)).astype("float32")
    hh = 10 ** (db / 10)
    t = Affine(0.001, 0, -58.0, 0, -0.001, -16.0)
    r = ws.water_for_date(hh, t, "EPSG:4326", [-58.0, -16.06, -57.94, -16.0], speckle=1)
    assert r["water_km2_lo"] <= r["water_km2_fixed"] <= r["water_km2_hi"]


def test_layer_images_match_bbox():
    hh = np.full((40, 40), 0.1, "float32")
    hh[:20] = 0.003
    t = Affine(0.005, 0, -58.0, 0, -0.005, -16.0)
    bbox = [-58.0, -16.2, -57.8, -16.0]
    res = ws.water_for_date(hh, t, "EPSG:4326", bbox, bounds=(-24, -12))
    img_hh, img_w = ws.layer_images(res, t, "EPSG:4326", bbox)
    assert img_hh.mode == "P" and img_hh.size == (200, 200) and img_w.shape == (400, 400, 4)
    a = np.asarray(img_hh)
    assert a[:90].mean() < a[110:].mean() and (a > 0).all()  # water darker; no transparent px
    assert img_w[..., 3][10:150, 10:-10].all() and not img_w[..., 3][250:].any()
    assert ws.leaflet_bounds(bbox) == [[-16.2, -58.0], [-16.0, -57.8]]

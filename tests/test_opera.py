import numpy as np

from pantanal_sar import opera


def test_scene_stats_and_clear_frac():
    a = np.array([[0, 1], [2, 253]], dtype=np.uint8)
    s = opera.scene_stats(a, pixel_km2=1.0)
    assert s["water_km2"] == 1 and s["water_partial_km2"] == 1
    assert s["clear_km2"] == 3 and s["clear_frac"] == 0.75


def test_composite_clear_beats_cloud_and_fill():
    a = np.array([[253, 1], [255, 0]], dtype=np.uint8)
    b = np.array([[1, 253], [2, 255]], dtype=np.uint8)
    c = opera.composite([a, b])
    assert c.tolist() == [[1, 1], [2, 0]]


def test_monthly_median_and_discard():
    sc = [
        {"date": "2025-03-02", "water_km2": 10, "water_partial_km2": 1, "clear_frac": 0.9},
        {"date": "2025-03-12", "water_km2": 30, "water_partial_km2": 3, "clear_frac": 0.7},
        {"date": "2025-03-22", "water_km2": 999, "water_partial_km2": 9, "clear_frac": 0.5},  # descartada
        {"date": "2025-04-05", "water_km2": 5, "water_partial_km2": 0, "clear_frac": 0.2},   # mes some
    ]
    rows = opera.monthly(sc)
    assert len(rows) == 1
    r = rows[0]
    assert r["date"] == "2025-03-01" and r["water_km2"] == 20 and r["n_scenes"] == 2
    assert set(r) == set(opera.FIELDS)


def test_aoi_grid_is_30m_aligned():
    left, top, nc, nr = opera.aoi_grid([-58.3, -17.5, -57.3, -16.5])
    assert left % 30 == 0 and top % 30 == 0
    assert 3300 < nc < 3800 and 3300 < nr < 3800


def test_daily_rows_follow_contract_and_quality():
    sc = [{"date": "2024-05-01", "water_km2": 1.23456, "water_partial_km2": 2.0, "clear_km2": 90.0,
           "clear_frac": 0.9, "n_granules": 3},
          {"date": "2024-05-02", "water_km2": 5, "water_partial_km2": 0, "clear_km2": 70.0,
           "clear_frac": 0.7, "n_granules": 2},
          {"date": "2024-05-03", "water_km2": 5, "water_partial_km2": 0, "clear_km2": 10.0,
           "clear_frac": 0.1, "n_granules": 1}]
    rows = opera.daily_rows(sc)
    assert [r["quality"] for r in rows] == ["ok", "low", "drop"]
    assert set(opera.DAILY_FIELDS) == set(rows[0])
    assert rows[0]["source"] == "opera_dswx_hls" and rows[0]["valid_frac"] == 0.9


def test_dswx_s1_stats_classes():
    from pantanal_sar import opera_s1
    a = np.array([[0, 1], [2, 3], [251, 255]], dtype=np.uint8)
    s = opera_s1.stats(a, pixel_km2=1.0)
    assert s["water_km2"] == 1 and s["water_partial_km2"] == 1 and s["water_inundveg_km2"] == 1
    assert s["clear_km2"] == 4 and abs(s["clear_frac"] - 4 / 6) < 1e-9

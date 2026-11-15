"""Synthetic Sentinel-1 RTC tests (no download)."""
import numpy as np
import rasterio
from rasterio.transform import Affine

from pantanal_sar import s1_water as s1

BBOX = [-58.0, -17.0, -57.9, -16.9]           # ~10.6 x 11 km
T = Affine(30.0, 0, 393000.0, 0, -30.0, 8131000.0)  # UTM 21S, covers BBOX
SHAPE = (420, 420)


def _write(d, date, pol, water_rows, water_db, land_db, rng):
    a = rng.normal(land_db, 1.0, SHAPE)
    a[:water_rows] = rng.normal(water_db, 1.0, (water_rows, SHAPE[1]))
    with rasterio.open(d / f"{date}_{pol}.tif", "w", driver="GTiff", height=SHAPE[0],
                       width=SHAPE[1], count=1, dtype="float32", crs="EPSG:32721",
                       transform=T, nodata=np.nan) as f:
        f.write((10 ** (a / 10)).astype("float32"), 1)


def _scene(d, rng):
    # wet (April) more water than dry (September); VV bimodal, VH weaker contrast
    for date, rows in (("2024-04-10", 200), ("2024-04-22", 190), ("2024-09-05", 80),
                       ("2024-09-17", 70), ("2024-07-01", 120)):
        _write(d, date, "VV", rows, -22, -9, rng)
        _write(d, date, "VH", rows, -26, -22, rng)


def test_calibration_dates():
    ds = ["2024-03-01", "2024-04-01", "2024-05-01", "2024-07-01", "2024-09-01", "2025-10-01"]
    c = s1.calibration_dates(ds, per_season=2)
    assert c["wet"] == ["2024-03-01", "2024-05-01"] and c["dry"] == ["2024-09-01", "2025-10-01"]


def test_agreement():
    a = np.array([1, 1, 0, 0, np.nan], "float32")
    b = np.array([1, 0, 0, 0, 1], "float32")
    r = s1.agreement(a, b)
    assert r["n"] == 4 and r["tp"] == 1 and r["fp"] == 1 and abs(r["f1"] - 2 / 3) < 1e-3
    assert abs(s1.agreement(b[:4], b[:4])["kappa"] - 1) < 1e-9


def test_pipeline_synthetic(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    _scene(tmp_path, rng)
    monkeypatch.setattr(s1, "CALIB_JSON", tmp_path / "cal.json")
    monkeypatch.setattr(s1.ws, "QC_DIR", tmp_path / "qc")
    out = tmp_path / "s1_rtc.csv"
    cal = s1.run({"bbox": BBOX}, d=tmp_path, out=out)
    assert cal["pol"] == "VV" and -19 < cal["threshold_db"] < -12
    import csv
    rows = list(csv.DictReader(open(out)))
    assert [r["date"] for r in rows] == s1.list_dates(tmp_path)
    r0 = rows[0]
    assert r0["source"] == "s1_rtc" and r0["method"].startswith("VV<") and r0["quality"] == "ok"
    wet = float(next(r for r in rows if r["date"] == "2024-04-10")["water_km2"])
    dry = float(next(r for r in rows if r["date"] == "2024-09-05")["water_km2"])
    assert wet > 2 * dry
    # validation against a synthetic DSWx-S1 identical to the truth of 2024-09-05
    dsw = tmp_path / "dswx"
    dsw.mkdir()
    w = np.zeros(SHAPE, "uint8")
    w[:80] = 1
    with rasterio.open(dsw / "2024-09-05_WTR.tif", "w", driver="GTiff", height=SHAPE[0],
                       width=SHAPE[1], count=1, dtype="uint8", crs="EPSG:32721",
                       transform=T, nodata=255) as f:
        f.write(w, 1)
    monkeypatch.setattr(s1, "nisar_dates", lambda: [])
    res = s1.validate({"bbox": BBOX}, d=tmp_path, dswx_dir=dsw, out=tmp_path / "val.csv",
                      series=out)
    assert len(res) == 1 and res[0]["f1"] > 0.9 and res[0]["kappa"] > 0.85


def test_calibration_prefers_coverage():
    ds = ["2025-04-01", "2025-04-06", "2025-04-13", "2025-04-18"]
    v = {"2025-04-01": 0.51, "2025-04-06": 0.85, "2025-04-13": 0.51, "2025-04-18": 0.85}
    assert s1.calibration_dates(ds, 2, v)["wet"] == ["2025-04-06", "2025-04-18"]


def test_dswx_s1_classes(tmp_path):
    w = np.array([[0, 1, 2, 3], [250, 251, 253, 255]], "uint8")
    with rasterio.open(tmp_path / "2025-01-01_WTR.tif", "w", driver="GTiff", height=2, width=4,
                       count=1, dtype="uint8", crs="EPSG:32721", transform=T) as f:
        f.write(w, 1)
    a, _, _ = s1.dswx_s1("2025-01-01", tmp_path)
    assert a[0].tolist() == [0, 1, 0, 0] and np.isnan(a[1]).all()


def test_footprint_quality():
    rows = [dict(track="T039", valid_frac=f, quality="ok") for f in (0.85, 0.85, 0.85, 0.75)]
    q = [r["quality"] for r in s1.footprint_quality(rows)]
    assert q == ["ok", "ok", "ok", "drop"]


def test_list_dates_respects_index(tmp_path):
    for date in ("2025-03-03", "2026-07-15"):
        for pol in ("VV", "VH"):
            (tmp_path / f"{date}_{pol}.tif").write_bytes(b"")
    assert s1.list_dates(tmp_path) == ["2025-03-03", "2026-07-15"]
    (tmp_path / "index.csv").write_text("date,tracks,valid_frac_vv\n2026-07-15,T141,0.51\n")
    assert s1.list_dates(tmp_path) == ["2026-07-15"]


def test_flag_vs_dswx(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("date,quality,water_km2,track,valid_frac\n2024-08-16,ok,364,T039,0.85\n"
                 "2024-09-21,ok,775,T039,0.85\n2024-10-27,ok,184,T039,0.85\n"
                 "2025-08-05,ok,213,T039,0.85\n2026-09-30,ok,215,T039,0.85\n")
    hls = tmp_path / "h.csv"
    hls.write_text("date,water_km2,quality\n2024-08-18,452,ok\n2024-10-27,400,ok\n"
                   "2025-08-06,400,ok\n2026-09-29,400,ok\n")
    val = [dict(s1_date="2024-09-21", ref="opera_dswx_s1", f1=0.36, fp=649107, fn=113881),
           dict(s1_date="2024-10-27", ref="opera_dswx_s1", f1=0.74, fp=6918, fn=130835)]
    # 2024-08-16: ratio 0.81 vs median 0.53 -> 1.5x -> flagged by the optical check
    assert s1.flag_vs_dswx(val, p, hls) == ["2024-08-16", "2024-09-21"]
    import csv
    rows = {r["date"]: r for r in csv.DictReader(open(p))}
    assert rows["2024-09-21"]["quality"] == "drop" and "DSWx-S1" in rows["2024-09-21"]["flag"]
    assert rows["2024-08-16"]["quality"] == "drop" and "HLS" in rows["2024-08-16"]["flag"]
    assert rows["2024-10-27"]["quality"] == "ok" and rows["2024-10-27"]["water_km2"] == "184"
    assert s1.flag_vs_dswx(val, p, hls) == ["2024-08-16", "2024-09-21"]  # idempotent

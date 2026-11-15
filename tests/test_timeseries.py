import json

import numpy as np
import pandas as pd
import pytest

from pantanal_sar import timeseries as ts

pytest.importorskip("prophet")

CFG = {"name": "teste", "bbox": [-58.3, -17.5, -57.3, -16.5]}
GATE = ts.DEFAULT_GATE


def _scfg(ids, **fc):
    return {**ts.DEFAULTS, "sources": [{"id": i, "label_pt": f"L {i}"} for i in ids],
            "calibration_gate": dict(GATE), "forecast": {**ts.DEFAULT_FORECAST, **fc}}


def _run(ids, tmp_path=None, frames=None, **fc):
    frames = frames or ts.synthetic(ids)
    scfg = _scfg(list(frames), **fc)
    res = ts.run_model(frames, scfg)
    if tmp_path is not None:
        ts.export(res, frames, scfg, CFG, demo=ts.is_synthetic(frames), web_dir=tmp_path)
    return frames, res


def _model(res):
    m = res["model"]
    return m[m["kind"] == "fit"].reset_index(drop=True), m[m["kind"] == "forecast"].reset_index(drop=True)


# ---- A. detection is always NISAR alone

def test_one_source_detection_only_no_forecast(tmp_path):
    _, res = _run(["nisar"], tmp_path)
    fit, fc = _model(res)
    m = res["metrics"]
    assert len(fit) == 9 and fit["observed_km2"].notna().all()
    assert m["forecast_source"] is None and len(fc) == 0
    assert any("Sem previsao" in s for s in m["limitations_pt"])
    assert any("estacao seca" in s for s in m["limitations_pt"])


def test_detection_ignores_other_sources():
    _, r1 = _run(["nisar"])
    _, r3 = _run(["nisar", "opera_dswx_hls", "s1_rtc"])
    f1, f3 = _model(r1)[0], _model(r3)[0]
    assert list(f1["date"]) == list(f3["date"])
    np.testing.assert_allclose(f1["expected_km2"], f3["expected_km2"])
    assert set(f3["label_pt"]) <= {"Observado", "Fora da faixa esperada (95%)"}
    assert (f3.loc[f3["anomaly"], "label_pt"] == "Fora da faixa esperada (95%)").all()


# ---- B. forecast on the longest complete source, in its own scale

def test_two_sources_forecast_on_s1_level_calibrated(tmp_path):
    frames, res = _run(["nisar", "s1_rtc"], tmp_path, sources=["s1_rtc"], check_sources=[])
    m = res["metrics"]
    t = m["calibration_tests"]["s1_rtc"]
    assert t["passed"] and t["skill"] >= 0.10 and t["loo_mape_pct"] <= 25 and t["coef"] > 0
    assert m["forecast_source"] == "s1_rtc" and m["level_calibrated"] is True and m["forecast_seasonal"]
    _, fc = _model(res)
    assert len(fc) == 4 and (fc["label_pt"] == "Projeção").all()
    assert (fc["lo80_pct"] < fc["forecast_pct"]).all() and (fc["forecast_pct"] < fc["hi80_pct"]).all()
    assert (fc["lo80_km2"] < fc["expected_km2"]).all() and (fc["expected_km2"] < fc["hi80_km2"]).all()
    base = m["forecast_base"]["water_km2_src"]                     # model yhat at the last obs date
    np.testing.assert_allclose(fc["forecast_pct"], (fc["expected_src_km2"] / base - 1) * 100)
    np.testing.assert_allclose(fc["lo80_pct"], (fc["lo80_src_km2"] / base - 1) * 100)
    assert m["forecast_base"]["kind"].startswith("modelo")
    assert m["forecast_base"]["date"] == frames["s1_rtc"]["date"].max().strftime("%Y-%m-%d")
    d = pd.DataFrame({"date": pd.to_datetime(["2026-10-01", "2026-10-20", "2026-10-25", "2026-11-01"]),
                      "water_km2": [999.0, 100, 300, 120], "weight": 1.0})
    tc = ts.trailing_composite(d, 15)
    assert tc["n"] == 3 and tc["water_km2"] == 120.0 and tc["date"] == pd.Timestamp("2026-11-01")


def test_three_sources_chain_and_package(tmp_path):
    _, res = _run(["nisar", "opera_dswx_hls", "s1_rtc"], tmp_path, sources=["s1_rtc"], check_sources=[])
    assert res["metrics"]["calibration"]["opera_dswx_hls"]["via"] == "s1_rtc"
    obs = json.loads((tmp_path / "series" / "observations.json").read_text())
    assert {"date", "source", "water_km2_raw", "water_km2", "water_km2_sd", "calibrated", "quality"} == set(obs[0])
    model = json.loads((tmp_path / "series" / "model.json").read_text())
    assert {"forecast_pct", "lo80_pct", "hi80_pct", "forecast_source", "level_calibrated"} <= set(model[0])
    met = json.loads((tmp_path / "series" / "metrics.json").read_text())
    for k in ("forecast_source", "level_calibrated", "skill", "calibration_tests", "limitations_pt", "holdout"):
        assert k in met
    for f in ("observations", "model", "metrics"):
        assert (tmp_path / "series" / f"{f}.csv").exists()
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["schema_version"] == 2 and man["demo"] is True
    assert man["forecast"] == {"source": "s1_rtc", "level_calibrated": True}
    assert {s["id"]: s["calibrated"] for s in man["sources"]} == {
        "nisar": True, "opera_dswx_hls": True, "s1_rtc": True}
    assert all("skill" in s for s in man["sources"])


def test_forecast_source_is_fixed_s1_is_check_only():
    f = ts.synthetic(["nisar", "s1_rtc"])
    s1 = f["s1_rtc"]
    # a long DSWx-like source with the same shape (2 days off the S1 dates), and anti-correlated
    # with NISAR in level so it fails the gate -> level_calibrated false
    f["opera_dswx_hls"] = ts.clean(pd.DataFrame({"date": s1["date"] + pd.Timedelta(days=2),
                                                 "water_km2": 0.8 * s1["water_km2"] + 10}), "opera_dswx_hls")
    _, res = _run(None, frames=f)            # default config: sources [opera_dswx_hls], check [s1_rtc]
    m = res["metrics"]
    assert m["forecast_source"] == "opera_dswx_hls"
    chk = m["forecast_check"]
    assert chk["source"] == "s1_rtc" and len(chk["forecast_pct"]) == 4 and len(chk["weeks"]) == 4
    assert chk["r_seasonal"] > 0.9 and all(chk["same_direction"])
    _, fc = _model(res)
    assert list(fc["check_same_direction"]) == chk["same_direction"]
    assert any(s.startswith("Checagem independente com s1_rtc") for s in m["limitations_pt"])


def test_no_check_source_recorded_as_skipped():
    f = ts.synthetic(["nisar", "s1_rtc"])
    _, res = _run(None, frames=f, sources=["s1_rtc"], check_sources=["opera_dswx_hls"])
    assert res["metrics"]["forecast_check"]["source"] is None
    _, fc = _model(res)
    assert fc["check_same_direction"].isna().all()


# ---- calibration gate

def test_skill_rejects_source_no_better_than_constant():
    rng = np.random.default_rng(3)
    y = rng.uniform(180, 380, 8)                         # dry-season NISAR
    x = rng.uniform(300, 600, 8)                         # unrelated source
    f = ts.fit_pairs(x, y, np.ones(8), {**GATE, "max_loo_mape_pct": 100})
    assert not f["ok"] and f["skill"] < 0.10 and "skill" in ts._fail_text(f)


def test_narrow_range_uses_proportional_with_bootstrap_ci():
    rng = np.random.default_rng(1)
    x = rng.uniform(150, 300, 10)
    y = 1.25 * x * rng.normal(1, 0.03, 10)
    f = ts.fit_pairs(x, y, np.ones(10), GATE)
    assert f["cv_target"] < 0.3 and f["model"] == "proporcional"
    assert f["ok"] and f["skill"] >= 0.10
    assert f["b"] == pytest.approx(1.25, abs=0.06) and f["ci"][0] < f["b"] < f["ci"][1]


def test_wide_range_uses_linear():
    x = np.linspace(100, 900, 12)
    y = 80 + 0.7 * x + np.random.default_rng(2).normal(0, 10, 12)
    f = ts.fit_pairs(x, y, np.ones(12), GATE)
    assert f["ok"] and f["model"] == "linear" and f["b"] == pytest.approx(0.7, abs=0.05)


def test_linear_failing_gate_falls_back_to_proportional():
    x = np.array([100.0, 200, 300, 400, 500, 600, 700, 800, 900])
    y = 1.2 * x * np.array([1, 1.01, 0.99, 1, 1.02, 0.98, 1, 1.01, 0.99])
    y[2] *= 3                                    # one outlier: pulls the linear fit, not the median ratio
    f = ts.fit_pairs(x, y, np.ones(9), GATE)
    assert f["cv_target"] >= GATE["narrow_cv"]
    linear = next(t for t in f["tries"] if t["model"] == "linear")
    assert linear["fail"] and f["model"] == "proporcional" and f["ok"]


def test_rejected_source_out_with_numbers():
    nis = ts.synthetic(["nisar"])["nisar"]
    few = pd.DataFrame({"date": nis["date"][:3] + pd.Timedelta(days=1), "water_km2": [300.0, 280, 250]})
    frames = {"nisar": nis, "few": ts.clean(few, "few")}
    cals, skipped, tests = ts.calibrate_all(frames, "nisar", 4, GATE)
    assert set(cals) == {"nisar"} and "n=3 < 8" in skipped["few"] and not tests["few"]["passed"]
    res = ts.run_model(frames, _scfg(frames))
    obs = res["observations"]
    assert obs.loc[obs["source"] == "few", "water_km2"].isna().all()
    assert any(s.startswith("few: sem nivel") for s in res["metrics"]["limitations_pt"])


def test_monthly_fallback():
    f = ts.synthetic(["nisar"])
    days = ["2026-07-23", "2026-08-16", "2026-09-09", "2026-10-15"]   # 6 days from every NISAR pass
    src = ts.clean(pd.DataFrame({"date": days, "water_km2": [300.0, 260, 220, 230]}), "m")
    x, y, w, pairing = ts.pair(src, f["nisar"].assign(value=f["nisar"]["water_km2"]), 4)
    assert pairing == "mensal" and len(x) == 4


# ---- package details

def test_drop_rows_excluded_low_rows_downweighted():
    df = pd.DataFrame({"date": ["2026-01-01", "2026-01-13", "2026-01-25"], "water_km2": [1.0, 2.0, 3.0],
                       "quality": ["ok", "low", "drop"]})
    c = ts.clean(df, "x")
    assert len(c) == 2 and list(c["weight"]) == [1.0, 0.5]


def test_layers_kept_v1_keys_dropped(tmp_path):
    (tmp_path / "layers").mkdir()
    (tmp_path / "layers" / "2026-09-27_open_water.png").write_bytes(b"png")
    prev = {"schema_version": 2, "firms": "firms.geojson", "stats": {"demo": True}, "extra": 1, "layers": [
        {"id": "a", "type": "open_water", "date": "2026-09-27", "source": "nisar",
         "file": "layers/2026-09-27_open_water.png", "bounds": [[-17.5, -58.3], [-16.5, -57.3]]},
        {"id": "old", "type": "burn", "date": "2026-07-05", "file": "2026-07-05_burn.png"}]}
    (tmp_path / "manifest.json").write_text(json.dumps(prev))
    _run(["nisar"], tmp_path)
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert [l["id"] for l in man["layers"]] == ["a"] and man["dates"] == ["2026-09-27"]
    assert man["extra"] == 1 and "firms" not in man and "stats" not in man
    assert man["demo"] is True                            # computed: synthetic NISAR went in


def test_demo_flag_is_computed_not_fixed(tmp_path):
    frames = ts.synthetic(["nisar"])
    frames["nisar"]["product"] = "NISAR_L2_GCOV_PROVISIONAL_V1"
    frames["nisar"]["method"] = "HH<-16.75dB"
    assert not ts.is_synthetic(frames)
    (tmp_path / "manifest.json").write_text(json.dumps({"schema_version": 2, "demo": True}))  # stale flag
    _run(None, tmp_path, frames=frames)
    assert json.loads((tmp_path / "manifest.json").read_text())["demo"] is False


def test_gate_requires_n8_and_skill_ci_above_zero():
    rng = np.random.default_rng(7)
    x = rng.uniform(150, 300, 6)
    y = 1.25 * x * rng.normal(1, 0.02, 6)                 # excellent fit but only 6 pairs
    f = ts.fit_pairs(x, y, np.ones(6), GATE)
    assert not f["ok"] and "n=6 < 8" in ts._fail_text(f)
    x = rng.uniform(150, 300, 12)
    y = 1.25 * x * rng.normal(1, 0.03, 12)
    f = ts.fit_pairs(x, y, np.ones(12), GATE)
    assert f["ok"] and f["skill_ci"][0] > 0 and f["skill_ci"][0] <= f["skill"] <= f["skill_ci"][1]


def test_skill_ci_can_reject_lucky_skill():
    e_model = np.array([0.05, 0.40, 0.06, 0.35, 0.05, 0.30, 0.04, 0.33, 0.06, 0.20])
    e_const = np.array([0.30, 0.10, 0.28, 0.12, 0.25, 0.15, 0.30, 0.10, 0.27, 0.20])
    sk = 1 - e_model.mean() / e_const.mean()
    ci = ts.skill_ci(e_model, e_const)
    assert sk > 0.10 and ci[0] < 0                       # point skill passes, CI does not exclude 0


def test_composite_median_and_variant_comparison():
    d = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=6, freq="5D"),
                      "water_km2": [100.0, 300, 110, 120, 500, 130], "weight": 1.0, "quality": "ok"})
    c = ts.composite(d, 15)
    assert list(c["n"]) == [3, 3] and list(c["water_km2"]) == [110.0, 130.0]
    f = ts.synthetic(["nisar", "s1_rtc"])
    rng = np.random.default_rng(0)
    s1 = f["s1_rtc"].copy()
    s1["water_km2"] = s1["water_km2"] * rng.lognormal(0, 0.35, len(s1))   # very noisy individual rows
    f["s1_rtc"] = s1
    _, res = _run(None, frames=f, sources=["s1_rtc"], check_sources=[])
    m = res["metrics"]
    v = m["forecast_variants"]
    assert set(v) == {"obs", "composto15"}
    for k in v.values():
        assert {"mape_pct", "coverage80", "n"} <= set(k["alvo_composto"])
    assert m["forecast_variant"] in v and m["forecast_base"]["variant"] == m["forecast_variant"]
    assert m["forecast_base"]["kind"].startswith("modelo") and m["forecast_base"]["observed_n_15d"] >= 1
    assert "cobertura IC80" in m["forecast_variant_reason"]


def test_source_filter_from_config():
    d = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=4, freq="12D"), "water_km2": [1.0, 2, 3, 4],
                      "track": ["T039", "T141", "T039", "T039"], "valid_frac": [0.85, 0.51, 0.75, 0.85]})
    f = ts.apply_filter(ts.clean(d, "s1"), {"track": ["T039"], "min_valid_frac": 0.8})
    assert list(f["water_km2"]) == [1.0, 4.0]
    with pytest.raises(ValueError):
        ts.apply_filter(ts.clean(d, "s1"), {"trak": ["T039"]})


def test_seasonal_comparison_and_notes_in_limitations():
    f = ts.synthetic(["nisar", "opera_dswx_hls", "s1_rtc"])
    sc = ts.seasonal_comparison(f, ["s1_rtc", "opera_dswx_hls"])
    p = sc["pairs"]["s1_rtc~opera_dswx_hls"]
    assert p["corr_monthly"] > 0.8 and p["n_months"] >= 12 and set(sc["amplitude_rel"]) == {"s1_rtc", "opera_dswx_hls"}
    scfg = _scfg(list(f))
    scfg["sources"][2]["notes_pt"] = ["banda C nao ve agua sob vegetacao"]
    res = ts.run_model(f, scfg)
    lim = res["metrics"]["limitations_pt"]
    assert "s1_rtc: banda C nao ve agua sob vegetacao" in lim
    assert any(s.startswith("Forma sazonal") and "s1_rtc" in s and "opera_dswx_hls" in s for s in lim)
    assert "seasonal_comparison" in res["metrics"]



def test_check_invalid_without_obs_in_horizon_months():
    f = ts.synthetic(["nisar", "s1_rtc"])
    s1 = f["s1_rtc"]
    f["opera_dswx_hls"] = ts.clean(pd.DataFrame({"date": s1["date"] + pd.Timedelta(days=2),
                                                 "water_km2": 0.8 * s1["water_km2"] + 10}), "opera_dswx_hls")
    f["s1_rtc"] = s1[~s1["date"].dt.month.isin([11, 12])].reset_index(drop=True)   # no Nov/Dec in any year
    _, res = _run(None, frames=f)
    chk = res["metrics"]["forecast_check"]
    assert chk["source"] == "s1_rtc" and chk["valid"] is False and chk["same_direction"] is None
    assert "meses do horizonte" in chk["skipped"] and chk["forecast_pct"] is None and chk["weeks"] is None
    _, fc = _model(res)
    assert fc["check_same_direction"].isna().all()
    assert any("Sem checagem independente valida" in s for s in res["metrics"]["limitations_pt"])


def test_completeness_is_month_coverage_and_incomplete_pairs_are_not_concluded():
    f = ts.synthetic(["nisar", "s1_rtc"])
    s1 = f["s1_rtc"]
    f["opera_dswx_hls"] = ts.clean(pd.DataFrame({"date": s1["date"] + pd.Timedelta(days=2),
                                                 "water_km2": 0.8 * s1["water_km2"] + 10}), "opera_dswx_hls")
    # many rows but only 7 calendar months (like s1 T039 before batch 3)
    f["s1_rtc"] = s1[s1["date"].dt.month.isin([3, 4, 5, 7, 8, 9, 10])].reset_index(drop=True)
    assert len(f["s1_rtc"]) > 24
    cov = ts.coverage(f["s1_rtc"], ts.DEFAULT_FORECAST)
    assert cov["n_months"] == 7 and not cov["complete"]
    _, res = _run(None, frames=f)
    m = res["metrics"]
    p = m["seasonal_comparison"]["pairs"]["opera_dswx_hls~s1_rtc"]
    assert p["conclusive"] is False and p["incomplete_sources"] == ["s1_rtc"]
    lim = m["limitations_pt"]
    assert not any(s.startswith("Forma sazonal") for s in lim)
    assert any("forma sazonal opera_dswx_hls x s1_rtc adiada" in s for s in lim)
    chk = m["forecast_check"]
    assert chk["valid"] is False and "serie incompleta" in chk["skipped"]
    # a forecast source with 7 months is not complete either
    sid, why = ts.pick_forecast_source({"s1_rtc": f["s1_rtc"]}, {**ts.DEFAULT_FORECAST, "sources": ["s1_rtc"]}, "nisar")
    assert sid is None and "7/12 meses" in why



# ---- correction round (docs/DATA_REVIEW.md)

def test_detection_95_chance_and_method_sensitivity():
    f = ts.synthetic(["nisar"])
    n = f["nisar"]
    f["nisar"] = n.assign(water_km2_lo=n["water_km2"] * 0.6, water_km2_hi=n["water_km2"] * 1.4 + 20)
    _, res = _run(None, frames=f)
    m = res["metrics"]
    assert m["detection_interval"] == 0.95
    ch = m["detection_chance"]
    assert ch["p_outside_each"] == 0.05 and ch["expected_outside"] == pytest.approx(0.45)
    assert ch["p_at_least_k"] == pytest.approx(ts.p_at_least(ch["k_outside"], 9, 0.05))
    assert ts.p_at_least(0, 8, 0.2) == pytest.approx(1.0) and ts.p_at_least(3, 8, 0.2) == pytest.approx(0.203, abs=1e-3)
    fit, _ = _model(res)
    assert fit["lo95_km2"].notna().all() and fit["lo80_km2"].isna().all()
    np.testing.assert_allclose(fit["method_lo_km2"], f["nisar"]["water_km2_lo"])
    tr = m["trend_range_km2_per_day"]
    assert tr["available"] and tr["min"] <= tr["central"] <= tr["max"]
    assert set(m["detection_sensitivity"]) == {"central", "lo", "hi"}
    assert any(s.startswith("Sensibilidade ao limiar do NISAR") for s in m["limitations_pt"])


def test_no_sensitivity_columns_is_declared():
    _, res = _run(["nisar"])
    assert res["metrics"]["trend_range_km2_per_day"]["available"] is False
    assert any("faltam colunas water_km2_lo/hi" in s for s in res["metrics"]["limitations_pt"])


def test_coverage_normalisation_and_rolling_outliers():
    d = pd.DataFrame({"date": pd.date_range("2024-08-01", periods=12, freq="5D"),
                      "water_km2": [400.0, 300, 410, 5, 395, 280, 405, 9, 400, 390, 410, 400],
                      "valid_km2": [11800.0, 8850, 11800, 11000, 11800, 8260, 11800, 11000, 11800, 11800, 11800, 11800]})
    d["valid_frac"] = d["valid_km2"] / 11800
    df, note = ts.prepare_source(ts.clean(d, "dswx"), {"normalize_coverage": True,
                                                       "outlier": {"window_days": 31, "min_ratio": 0.3}})
    assert note["normalize_coverage"]["full_area_km2"] == pytest.approx(11800)
    assert note["outliers_dropped"]["dates"] == ["2024-08-16", "2024-09-05"]
    r = df.set_index(df["date"].dt.strftime("%Y-%m-%d"))
    assert r.loc["2024-08-06", "water_km2"] == pytest.approx(300 / 8850 * 11800)    # 75% coverage -> 400
    assert r.loc["2024-08-06", "water_km2_obs"] == 300


def test_exclude_ranges_filter():
    d = ts.clean(pd.DataFrame({"date": pd.date_range("2024-08-01", periods=6, freq="20D"), "water_km2": 1.0}), "s1")
    f = ts.apply_filter(d, {"exclude_ranges": [["2024-08-16", "2024-10-15"]]})
    assert list(f["date"].dt.strftime("%m-%d")) == ["08-01", "10-20", "11-09"]   # 08-21, 09-10, 09-30 out


def test_forecast_km2_null_when_level_not_calibrated_and_interval_scaled():
    f = ts.synthetic(["nisar", "s1_rtc"])
    s1 = f["s1_rtc"]
    long = pd.DataFrame({"date": s1["date"] + pd.Timedelta(days=2), "water_km2": 900 - 2 * s1["water_km2"]})
    f["opera_dswx_hls"] = ts.clean(long, "opera_dswx_hls")       # anti-correlated: fails the gate
    _, res = _run(None, frames=f, check_sources=[])
    m = res["metrics"]
    assert m["level_calibrated"] is False and "NAO publicado" in m["level_method"]
    _, fc = _model(res)
    assert fc[["expected_km2", "lo80_km2", "hi80_km2"]].isna().all().all()
    assert fc["forecast_pct"].notna().all() and (fc["lo80_pct"] < fc["hi80_pct"]).all()
    fi = m["forecast_interval"]
    assert fi["scale"] is not None and fi["scale"] > 0 and fi["nominal"] == 0.8

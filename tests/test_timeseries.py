import json

import pandas as pd
import pytest

from pantanal_sar import timeseries as ts

pytest.importorskip("prophet")


def test_direct_calibration_linear():
    d = ts.synthetic(scenario="direto")
    cal = ts.calibrate(d["nisar"], d["mapbiomas"])
    assert cal.path == "direto" and cal.steps["direto"]["n"] == 4
    assert 0.8 < cal.b < 1.5


def test_bridge_composes_two_fits():
    d = ts.synthetic(scenario="ponte")
    with pytest.raises(ts.CalibrationError):
        ts.calibrate_direct(d["nisar"], d["mapbiomas"])
    cal = ts.calibrate(d["nisar"], d["mapbiomas"], d["dswx"])
    a1, b1 = cal.steps["a_mapbiomas_dswx"]["a"], cal.steps["a_mapbiomas_dswx"]["b"]
    a2, b2 = cal.steps["b_dswx_nisar"]["a"], cal.steps["b_dswx_nisar"]["b"]
    assert cal.path == "ponte"
    assert cal.b == pytest.approx(b1 * b2) and cal.a == pytest.approx(a1 + b1 * a2)
    # truth: MapBiomas = 1.1 * NISAR + 80
    assert cal.b == pytest.approx(1.1, abs=0.15)
    assert cal.steps["a_mapbiomas_dswx"]["n"] == 12 and cal.steps["a_mapbiomas_dswx"]["r2"] > 0.9
    assert cal.steps["b_dswx_nisar"]["pairing"].startswith("janela")
    s1, s2 = cal.steps["a_mapbiomas_dswx"]["sd"], cal.steps["b_dswx_nisar"]["sd"]
    assert cal.sd >= max(s1, b1 * s2)


def test_bridge_monthly_fallback_when_few_pairs():
    d = ts.synthetic(scenario="ponte")
    days = pd.date_range("2026-06-02", "2026-11-02", freq="MS") + pd.Timedelta(days=1)  # no NISAR date on day 2
    sparse = pd.DataFrame({"date": days, "water_km2": 500.0, "clear_frac": 1.0})
    x, y, pairing = ts.pair_dswx_nisar(d["nisar"], sparse, window=0)
    assert pairing == "mensal" and len(x) == 4    # Jul..Oct 2026


def test_no_overlap_no_dswx_falls_back_to_phase1():
    d = ts.synthetic(scenario="fase1")
    res = ts.run_model(d["nisar"], d["mapbiomas"], None, phase="auto")
    assert res["meta"]["phase"] == 1 and res["meta"]["calibration_path"] == "fase1"
    assert "sem DSWx" in res["meta"]["phase_reason"]


def test_phase1_no_yearly_seasonality_and_projection_labelled():
    d = ts.synthetic()
    res = ts.run_model(d["nisar"], None, horizon=3)
    fit = res["fit"]
    assert res["meta"]["phase"] == 1 and not res["meta"]["yearly_seasonality"]
    assert (fit["kind"] == "projecao").sum() == 3
    assert fit.loc[fit["kind"] == "projecao", "observed_km2"].isna().all()
    assert pd.to_datetime(fit.loc[fit["kind"] == "projecao", "ds"]).min() > d["nisar"]["date"].max()
    assert "yearly" not in res["components"]


def test_bridge_phase2_detects_dip_and_records_path(tmp_path):
    d = ts.synthetic(scenario="ponte")
    res = ts.run_model(d["nisar"], d["mapbiomas"], d["dswx"], phase=2)
    assert res["meta"]["yearly_seasonality"] and res["meta"]["calibration_path"] == "ponte"
    obs = res["fit"][res["fit"]["kind"] == "observado"].reset_index(drop=True)
    assert obs["anomaly_km2"].idxmin() == 5 and obs.loc[5, "is_anomaly"]   # dip on 2026-09-03
    assert (obs["cal_sd_km2"] > 0).all()
    (tmp_path / "manifest.json").write_text(json.dumps({"name": "x", "layers": []}))
    ts.write_outputs(res, demo=True, out_dir=tmp_path, web_dir=tmp_path)
    man = json.loads((tmp_path / "manifest.json").read_text())
    assert man["name"] == "x" and man["water_series"]["calibration_path"] == "ponte"
    assert man["water_series"]["demo"] is True
    m = pd.read_csv(tmp_path / "model_metrics.csv").set_index("key")["value"]
    for k in ("cal_a_mapbiomas_dswx_r2", "cal_a_mapbiomas_dswx_n", "cal_b_dswx_nisar_r2", "cal_b_dswx_nisar_n"):
        assert k in m.index


def test_monthly_dswx_pairs_monthly_and_drops_few_scenes():
    d = ts.synthetic(scenario="ponte", dswx_monthly=True)
    cal = ts.calibrate(d["nisar"], d["mapbiomas"], d["dswx"])
    assert cal.steps["b_dswx_nisar"]["pairing"] == "mensal" and cal.steps["b_dswx_nisar"]["n"] == 4
    assert cal.steps["a_mapbiomas_dswx"]["n"] == 11            # Dec/2025 (n_scenes=1) discarded


def test_partial_water_sensitivity_reports_deltas():
    d = ts.synthetic(scenario="ponte", dswx_monthly=True)
    sens = ts.bridge_sensitivity(d["mapbiomas"], d["dswx"], d["nisar"])
    for k in ("a_b", "a_r2", "b_b", "b_r2", "comp_b"):
        assert f"aberta_{k}" in sens and f"aberta_parcial_{k}" in sens and f"delta_{k}" in sens
    assert sens["aberta_a_b"] > sens["aberta_parcial_a_b"]     # partial inflates DSWx -> smaller slope
    only_a = ts.bridge_sensitivity(d["mapbiomas"], d["dswx"], None)   # NISAR missing: step a only
    assert "aberta_a_r2" in only_a and "aberta_b_r2" not in only_a

"""Open-water time series: detection on NISAR, forecast on the longest consistent source.

Contract: docs/DATA_CONTRACT.md (v2). Nothing here is specific to a source:

  config/aoi.yaml  series.sources   ->  data/series/<id>.csv  (contract section 1)
                   series.reference ->  the scale of the detection (nisar)

Detection and forecast are separate so a weak calibration cannot contaminate the detection:

A. DETECTION (essential), always on the reference (NISAR) alone: Prophet trend + few changepoints,
   no annual seasonality (NISAR only covers the 2026 dry season), 80% interval; an anomaly is a
   NISAR date outside the interval of its own series.

B. FORECAST (differential): Prophet with annual seasonality on the first source of
   series.forecast.sources that is complete (usable rows in >= min_months_covered of the 12 calendar
   months, over >= min_years), IN THAT
   SOURCE'S OWN SCALE. Main output is the relative change (%) against the source's last
   observation. A km2 value in the NISAR scale is given only as a secondary output:
     - level_calibrated = true when the source passed the calibration gate (with skill);
     - otherwise proportional k from its pairs with NISAR, interval widened with the bootstrap
       CI of k, level_calibrated = false.

Calibration of each source to the NISAR scale (used for observations.json and B):
   pairs within +-pair_window_days (monthly fallback); linear y = a + b x, or proportional
   y = k x (k = median of ratios, bootstrap CI) when the NISAR range in the pairs is narrow
   (CV < narrow_cv) or the linear fit fails. Gate: n >= min_n, coefficient > 0,
   LOO MAPE <= max_loo_mape_pct and skill = 1 - LOO_source / LOO_constant >= min_skill, where
   LOO_constant predicts each pair with the mean of the others. A source that does not overlap
   NISAR may be calibrated through another calibrated source (chain, sd propagated).
   Sources failing the gate keep water_km2 = null in observations and go to limitations_pt.

Export: web/data/manifest.json (schema_version 2) and web/data/series/{observations,model,
metrics}.{json,csv}. Map layers under layers/ and other v2 keys in the manifest are kept.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from .config import ROOT, WEB_DATA, load_config

SERIES_DIR = ROOT / "data" / "series"
DEMO_WEB = ROOT / "data" / "demo" / "web"     # --demo never writes into web/data
REQUIRED = ("date", "source", "water_km2")
QUALITY_WEIGHT = {"ok": 1.0, "low": 0.5}
MIN_PAIRS = 3
YEARLY_ORDER = 3   # low Fourier order: sparse data, order 10 wiggles between samples
DEFAULT_GATE = {"max_loo_mape_pct": 25.0, "min_n": 8, "min_skill": 0.10, "skill_ci_lo_min": 0.0,
                "narrow_cv": 0.3, "bootstrap": 1000}
DEFAULT_FORECAST = {"sources": ["opera_dswx_hls"], "check_sources": ["s1_rtc"], "min_years": 2.0, "min_months_covered": 10,
                    "step": "7D", "horizon": 4, "holdout_days": 90, "composite_days": 15,
                    "min_coverage": 0.6}
DEFAULTS = {"reference": "nisar", "pair_window_days": 4, "interval": 0.8}
# Detection band 95% (80% flags ~1.6 of 8 points by chance). Method sensitivity: the detection is
# re-run on these columns of the reference CSV when present (threshold -1 dB / +1 dB).
DEFAULT_DETECTION = {"interval": 0.95, "sensitivity_columns": {"lo": "water_km2_lo", "hi": "water_km2_hi"}}
V1_KEYS = {"firms", "stats", "water_series", "name", "bbox"}
LABEL_PT = {"fit": "Observado", "anomaly": "Fora da faixa esperada (95%)", "forecast": "Projeção"}  # contract v2

for _name in ("prophet", "cmdstanpy"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class CalibrationError(ValueError):
    pass


# ---------------------------------------------------------------- config / loading

def series_config(cfg: dict | None = None) -> dict:
    cfg = load_config() if cfg is None else cfg
    s = {**DEFAULTS, **(cfg.get("series") or {})}
    s["sources"] = [x if isinstance(x, dict) else {"id": x} for x in s.get("sources") or [s["reference"]]]
    s["calibration_gate"] = {**DEFAULT_GATE, **(s.get("calibration_gate") or {})}
    s["forecast"] = {**DEFAULT_FORECAST, **(s.get("forecast") or {})}
    return s


def load_source(sid: str, series_dir: Path = SERIES_DIR) -> pd.DataFrame:
    df = pd.read_csv(series_dir / f"{sid}.csv")
    missing = [c for c in REQUIRED if c not in df]
    if missing:
        raise ValueError(f"{sid}.csv sem colunas {missing} (docs/DATA_CONTRACT.md secao 1)")
    return clean(df, sid)


def clean(df: pd.DataFrame, sid: str) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["source"] = sid
    q = df["quality"] if "quality" in df else pd.Series("ok", index=df.index)
    df["quality"] = q.fillna("ok").astype(str).str.lower()
    df = df[(df["quality"] != "drop") & df["water_km2"].notna()].copy()
    df["weight"] = df["quality"].map(QUALITY_WEIGHT).fillna(QUALITY_WEIGHT["low"])
    return df.sort_values("date").reset_index(drop=True)


def apply_filter(df: pd.DataFrame, flt: dict | None) -> pd.DataFrame:
    """Row filter from config (sources[].filter): {col: [allowed values]}, {min_<col>: v}, {max_<col>: v}.
    Unknown columns are an error, so a typo does not silently keep everything."""
    for k, v in (flt or {}).items():
        if k == "exclude_ranges":   # [[start, end], ...] inclusive, ISO dates
            for a, b in v:
                df = df[~df["date"].between(pd.Timestamp(a), pd.Timestamp(b))]
            continue
        if k.startswith(("min_", "max_")):
            col = k[4:]
            if col not in df:
                raise ValueError(f"filtro {k}: coluna {col} ausente")
            df = df[df[col] >= v] if k.startswith("min_") else df[df[col] <= v]
        else:
            if k not in df:
                raise ValueError(f"filtro {k}: coluna ausente")
            df = df[df[k].astype(str).isin([str(x) for x in (v if isinstance(v, list) else [v])])]
    return df.reset_index(drop=True)


def normalize_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """water_km2 := (water_km2 / valid_km2) x full bbox area, so partial cloud-free coverage does not
    bias the area down. Full area = median of valid_km2 / valid_frac of the source. Original kept in
    water_km2_obs."""
    if not {"valid_km2", "valid_frac"} <= set(df) or not len(df):
        raise ValueError("normalize_coverage requer valid_km2 e valid_frac")
    ok = (df["valid_km2"] > 0) & (df["valid_frac"] > 0)
    full = float((df.loc[ok, "valid_km2"] / df.loc[ok, "valid_frac"]).median())
    df = df[ok].copy()
    df["water_km2_obs"] = df["water_km2"]
    df["water_frac"] = df["water_km2"] / df["valid_km2"]
    df["water_km2"] = df["water_frac"] * full
    df.attrs["full_area_km2"] = full
    return df


def drop_rolling_outliers(df: pd.DataFrame, window_days: int = 31, min_ratio: float = 0.3):
    """Drop rows with water_km2 < min_ratio x centred rolling median over window_days (e.g. smoke
    read as land). Returns (kept, dropped)."""
    if len(df) < 3:
        return df, df.iloc[0:0]
    med = (df.set_index("date")["water_km2"].rolling(f"{window_days}D", center=True, min_periods=3).median()
           .to_numpy())
    bad = df["water_km2"].to_numpy() < min_ratio * med
    return df[~bad].reset_index(drop=True), df[bad]


def prepare_source(df: pd.DataFrame, spec: dict) -> tuple[pd.DataFrame, dict]:
    """Apply the per-source options of config (filter, normalize_coverage, outlier)."""
    note = {}
    df = apply_filter(df, spec.get("filter"))
    if spec.get("normalize_coverage"):
        df = normalize_coverage(df)
        note["normalize_coverage"] = {"full_area_km2": df.attrs.get("full_area_km2")}
    if spec.get("outlier"):
        o = spec["outlier"]
        df, bad = drop_rolling_outliers(df, int(o.get("window_days", 31)), float(o.get("min_ratio", 0.3)))
        note["outliers_dropped"] = {"rule": f"water_km2 < {o.get('min_ratio', 0.3)} x mediana movel de "
                                            f"{o.get('window_days', 31)} d",
                                    "dates": bad["date"].dt.strftime("%Y-%m-%d").tolist()}
    return df, note


def load_sources(scfg: dict, series_dir: Path = SERIES_DIR) -> tuple[dict, list, dict]:
    frames, missing, notes = {}, [], {}
    for s in scfg["sources"]:
        if (series_dir / f"{s['id']}.csv").exists():
            frames[s["id"]], n = prepare_source(load_source(s["id"], series_dir), s)
            if n:
                notes[s["id"]] = n
        else:
            missing.append(s["id"])
    return frames, missing, notes


def is_synthetic(frames: dict) -> bool:
    for df in frames.values():
        for c in ("product", "method", "sensor"):
            if c in df and df[c].astype(str).str.upper().str.contains("SYNTHETIC").any():
                return True
    return False


# ---------------------------------------------------------------- calibration

@dataclass
class Cal:
    a: float
    b: float            # slope (linear) or k (proporcional)
    r2: float | None
    n: int
    sd_km2: float
    pairing: str        # "referencia", "+-4 d", "mensal"
    via: str | None     # intermediate source for chained calibrations
    model: str = "referencia"          # linear | proporcional
    loo_mape_pct: float | None = None  # leave-one-out error on the pairs
    loo_const_pct: float | None = None # same, predicting with the mean of the other pairs
    skill: float | None = None         # 1 - loo_mape / loo_const
    skill_ci95: list | None = None     # bootstrap 95% CI of skill (resampling the per-pair LOO errors)
    cv_target: float | None = None     # coefficient of variation of the target in the pairs
    k_ci95: list | None = None         # bootstrap 95% CI of k (proporcional)

    def apply(self, x):
        return self.a + self.b * np.asarray(x, dtype=float)


def pair(src: pd.DataFrame, target: pd.DataFrame, window: int):
    """x = source raw km2, y = target km2 (already in reference scale, column 'value'), w = weight.
    +-window days around each target date (means); monthly means if < MIN_PAIRS pairs."""
    xs, ys, ws = [], [], []
    tol = pd.Timedelta(days=window)
    for d, y, wy in zip(target["date"], target["value"], target["weight"]):
        near = src[(src["date"] - d).abs() <= tol]
        if len(near):
            xs.append(near["water_km2"].mean())
            ys.append(y)
            ws.append(min(wy, near["weight"].mean()))
    if len(xs) >= MIN_PAIRS:
        return np.array(xs), np.array(ys), np.array(ws), f"+-{window} d"
    m = lambda df, c: df.groupby(df["date"].dt.to_period("M"))[c].mean()  # noqa: E731
    both = pd.concat([m(src, "water_km2").rename("x"), m(target, "value").rename("y"),
                      m(src, "weight").rename("w")], axis=1, join="inner").dropna()
    return both["x"].to_numpy(), both["y"].to_numpy(), both["w"].to_numpy(), "mensal"


def wlinfit(x, y, w=None) -> tuple[float, float, float | None, float]:
    """Weighted least squares y = a + b x. Returns a, b, r2, residual sd."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    w = np.ones_like(x) if w is None else np.asarray(w, float)
    n = len(x)
    if n < MIN_PAIRS or np.ptp(x) == 0:
        raise CalibrationError(f"pontos insuficientes para ajuste linear (n={n})")
    b, a = np.polyfit(x, y, 1, w=np.sqrt(w))
    r = y - (a + b * x)
    ss = np.sum(w * (y - np.average(y, weights=w)) ** 2)
    r2 = float(1 - np.sum(w * r ** 2) / ss) if ss > 0 else None
    sd = float(np.sqrt(np.sum(w * r ** 2) / np.sum(w) * n / (n - 2)))
    return float(a), float(b), r2, sd


def propfit(x, y, n_boot: int = 1000, seed: int = 0) -> tuple[float, float | None, float, list]:
    """Proportional y = k x, k = median of the pair ratios. Returns k, r2, residual sd, 95% CI (bootstrap)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = x > 0
    x, y = x[ok], y[ok]
    if len(x) < 2:
        raise CalibrationError(f"pontos insuficientes para ajuste proporcional (n={len(x)})")
    ratios = y / x
    k = float(np.median(ratios))
    rng = np.random.default_rng(seed)
    boot = np.median(rng.choice(ratios, size=(n_boot, len(ratios)), replace=True), axis=1)
    r = y - k * x
    ss = np.sum((y - y.mean()) ** 2)
    r2 = float(1 - np.sum(r ** 2) / ss) if ss > 0 else None
    sd = float(np.sqrt(np.sum(r ** 2) / (len(x) - 1)))
    return k, r2, sd, [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]


def loo_mape(x, y, w, model: str) -> float | None:
    """Leave-one-out MAPE (%) predicting y from x with `model` fitted on the other pairs.
    model "constante" ignores x and predicts the mean of the other y (the no-skill baseline)."""
    e = loo_errors(x, y, w, model)
    return None if e is None or not len(e) else float(np.mean(e) * 100)


def loo_errors(x, y, w, model: str) -> np.ndarray | None:
    """Per-pair leave-one-out absolute relative errors (NaN where y == 0)."""
    x, y, w = (np.asarray(v, float) for v in (x, y, w))
    errs = []
    for i in range(len(x)):
        m = np.arange(len(x)) != i
        try:
            if model == "linear":
                a, b, _, _ = wlinfit(x[m], y[m], w[m])
                pred = a + b * x[i]
            elif model == "proporcional":
                pos = x[m] > 0
                if not pos.any():
                    return None
                pred = np.median(y[m][pos] / x[m][pos]) * x[i]
            else:
                pred = y[m].mean()
        except CalibrationError:
            return None
        errs.append(abs(pred - y[i]) / abs(y[i]) if y[i] != 0 else np.nan)
    errs = np.array(errs)
    return errs[~np.isnan(errs)] if len(errs) else None


def skill_ci(e_model, e_const, n_boot: int = 1000, seed: int = 0) -> list | None:
    """Bootstrap 95% CI of skill = 1 - mean(e_model) / mean(e_const), resampling pairs (paired errors)."""
    if e_model is None or e_const is None or len(e_model) != len(e_const) or len(e_model) < 3:
        return None
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(e_model), size=(n_boot, len(e_model)))
    num, den = e_model[idx].mean(axis=1), e_const[idx].mean(axis=1)
    sk = 1 - num / np.where(den == 0, np.nan, den)
    sk = sk[np.isfinite(sk)]
    return [float(np.percentile(sk, 2.5)), float(np.percentile(sk, 97.5))] if len(sk) else None


def fit_pairs(x, y, w, gate: dict) -> dict:
    """Pick the calibration model for one set of pairs and check it against the gate."""
    gate = {**DEFAULT_GATE, **gate}
    n = len(x)
    cv = float(np.std(y) / np.mean(y)) if np.mean(y) else None
    e_const = loo_errors(x, y, w, "constante") if n >= 2 else None
    const = float(np.mean(e_const) * 100) if e_const is not None and len(e_const) else None
    out = {"n": n, "cv_target": cv, "loo_const": const}

    def check(f):
        why = []
        if n < gate["min_n"]:
            why.append(f"n={n} < {gate['min_n']}")
        if not f["b"] > 0:
            why.append(f"coeficiente {f['b']:.3g} <= 0")
        if f["loo"] is None or f["loo"] > gate["max_loo_mape_pct"]:
            loo = "indefinido" if f["loo"] is None else f"{f['loo']:.0f}%"
            why.append(f"LOO MAPE {loo} > {gate['max_loo_mape_pct']:g}%")
        if f["skill"] is None or f["skill"] < gate["min_skill"]:
            sk = "indefinido" if f["skill"] is None else f"{f['skill']:.2f}"
            why.append(f"skill {sk} < {gate['min_skill']:g} (LOO constante "
                       f"{'-' if const is None else f'{const:.0f}%'})")
        ci = f["skill_ci"]
        if ci is None or not ci[0] > gate["skill_ci_lo_min"]:
            txt = "indefinido" if ci is None else f"[{ci[0]:.2f}, {ci[1]:.2f}]"
            why.append(f"IC95 do skill {txt} nao exclui {gate['skill_ci_lo_min']:g}")
        return why

    tries = []
    narrow = cv is not None and cv < gate["narrow_cv"]
    for model in (["proporcional", "linear"] if narrow else ["linear", "proporcional"]):
        try:
            if model == "linear":
                a, b, r2, sd = wlinfit(x, y, w)
                ci = None
            else:
                b, r2, sd, ci = propfit(x, y, gate["bootstrap"])
                a = 0.0
        except CalibrationError as e:
            tries.append({"model": model, "fail": [str(e)]})
            continue
        e_model = loo_errors(x, y, w, model)
        loo = float(np.mean(e_model) * 100) if e_model is not None and len(e_model) else None
        skill = (1 - loo / const) if (loo is not None and const) else None
        f = {"model": model, "a": a, "b": b, "r2": r2, "sd": sd, "ci": ci, "loo": loo, "skill": skill,
             "skill_ci": skill_ci(e_model, e_const, gate["bootstrap"])}
        f["fail"] = check(f)
        tries.append(f)
        if not f["fail"]:
            return {**out, **f, "ok": True, "tries": tries}
    prop = next((t for t in tries if t["model"] == "proporcional" and "b" in t), None)
    best = prop or next((t for t in tries if "b" in t), tries[0])
    return {**out, **best, "ok": False, "tries": tries}


def _fail_text(f: dict) -> str:
    return "; ".join(f"{t['model']}: {', '.join(t['fail'])}" for t in f["tries"])


def _test_record(f: dict, pairing: str, via: str | None, passed: bool, reason: str | None = None) -> dict:
    return {"passed": passed, "model": f.get("model"), "coef": f.get("b"), "a": f.get("a"),
            "k_ci95": f.get("ci"), "loo_mape_pct": f.get("loo"), "loo_const_pct": f.get("loo_const"),
            "skill": f.get("skill"), "skill_ci95": f.get("skill_ci"), "n": f.get("n"), "cv_target": f.get("cv_target"),
            "pairing": pairing, "via": via, "reason": reason}


def calibrate_all(frames: dict, reference: str, window: int = 4, gate: dict | None = None):
    """Returns ({source: Cal} for sources that passed, {source: reason left out}, {source: test record})."""
    gate = {**DEFAULT_GATE, **(gate or {})}
    if reference not in frames:
        raise CalibrationError(f"fonte de referencia '{reference}' ausente")
    ref = frames[reference]
    cals = {reference: Cal(0.0, 1.0, 1.0, int(len(ref)), 0.0, "referencia", None)}
    scaled = {reference: ref.assign(value=ref["water_km2"].astype(float))}
    reasons, tests = {}, {}

    def attempt(s, candidates):
        best, failed = None, None
        for c in candidates:
            x, y, w, pairing = pair(frames[s], scaled[c], window)
            if len(x) < 2 or np.ptp(x) == 0:
                continue
            f = fit_pairs(x, y, w, gate)
            via = None if c == reference else c
            if not f["ok"]:
                failed = failed or (via, pairing, f)
                continue
            key = (pairing != "mensal", c == reference, len(x))   # prefer day pairs, then direct
            if best is None or key > best[0]:
                best = (key, c, pairing, f)
        if best is None:
            if failed:
                via, pairing, f = failed
                reasons[s] = f"reprovada no portao ({pairing}, n={f['n']}): {_fail_text(f)}"
                tests[s] = _test_record(f, pairing, via, False, reasons[s])
            return False
        _, c, pairing, f = best
        sd = float(math.sqrt(f["sd"] ** 2 + cals[c].sd_km2 ** 2))
        cals[s] = Cal(f["a"], f["b"], f["r2"], int(f["n"]), sd, pairing, None if c == reference else c,
                      f["model"], f["loo"], f["loo_const"], f["skill"], f["skill_ci"], f["cv_target"], f["ci"])
        scaled[s] = frames[s].assign(value=cals[s].apply(frames[s]["water_km2"]))
        tests[s] = _test_record(f, pairing, cals[s].via, True)
        reasons.pop(s, None)
        return True

    # direct to the reference first, then chains through already calibrated sources
    pending = [s for s in frames if s != reference and not attempt(s, [reference])]
    progress = True
    while pending and progress:
        progress = False
        for s in list(pending):
            if attempt(s, [c for c in cals if c != reference]):
                pending.remove(s)
                progress = True
    for s in pending:
        if s not in reasons:
            reasons[s] = f"menos de {MIN_PAIRS} pares (+-{window} d ou mensal) com a referencia ou outra fonte"
            tests[s] = {"passed": False, "reason": reasons[s]}
    return cals, reasons, tests


def observations(frames: dict, cals: dict) -> pd.DataFrame:
    """All sources, long format. water_km2 in NISAR scale only for calibrated sources (else null)."""
    rows = []
    for s, df in frames.items():
        c = cals.get(s)
        rows.append(pd.DataFrame({
            "date": df["date"], "source": s, "water_km2_raw": df["water_km2"].astype(float),
            "water_km2": c.apply(df["water_km2"]) if c else np.nan,
            "water_km2_sd": c.sd_km2 if c else np.nan, "calibrated": c is not None,
            "quality": df["quality"], "weight": df["weight"]}))
    return pd.concat(rows, ignore_index=True).sort_values(["date", "source"]).reset_index(drop=True)


# ---------------------------------------------------------------- Prophet

def _span_years(dates) -> float:
    dates = pd.to_datetime(pd.Series(dates))
    return (dates.max() - dates.min()).days / 365.25 if len(dates) else 0.0


def _fit_predict(train: pd.DataFrame, ds, seasonal: bool, interval: float) -> pd.DataFrame:
    from prophet import Prophet

    np.random.seed(0)
    kw = dict(growth="linear", yearly_seasonality=YEARLY_ORDER if seasonal else False,
              weekly_seasonality=False, daily_seasonality=False, interval_width=interval,
              uncertainty_samples=1000)
    if not seasonal:  # short series: few changepoints, else the trend interpolates the points
        kw.update(n_changepoints=max(0, min(3, train["date"].nunique() - 3)), changepoint_range=0.9)
    m = Prophet(**kw)
    m.fit(pd.DataFrame({"ds": train["date"], "y": train["water_km2"]}))
    return m.predict(pd.DataFrame({"ds": pd.to_datetime(pd.Series(list(ds)))}))


def _metrics(obs, pred) -> dict:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    if not len(obs):
        return {"mae_km2": None, "mape_pct": None, "n": 0}
    err = np.abs(pred - obs)
    nz = obs != 0
    return {"mae_km2": float(err.mean()),
            "mape_pct": float(np.mean(err[nz] / np.abs(obs[nz])) * 100) if nz.any() else None,
            "n": int(len(obs))}


def _detect_one(daily: pd.DataFrame, interval: float):
    det = _fit_predict(daily, daily["date"], False, interval)
    o, exp = daily["water_km2"].to_numpy(float), det["yhat"].to_numpy()
    lo, hi = det["yhat_lower"].to_numpy(), det["yhat_upper"].to_numpy()
    days = max((daily["date"].iloc[-1] - daily["date"].iloc[0]).days, 1)
    trend = float((det["trend"].iloc[-1] - det["trend"].iloc[0]) / days)
    return o, exp, lo, hi, (o < lo) | (o > hi), trend


def p_at_least(k: int, n: int, p: float) -> float:
    """Binomial P(X >= k), X ~ Bin(n, p): chance of k or more points outside the band by chance."""
    from math import comb
    return float(sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def detect(ref: pd.DataFrame, dcfg: dict) -> tuple[pd.DataFrame, dict]:
    """A. NISAR alone: trend + changepoints, in sample, band = dcfg.interval (95%).
    Also re-run on the method-sensitivity columns (threshold -1/+1 dB) when present."""
    interval = float(dcfg["interval"])
    sens_cols = {k: c for k, c in (dcfg.get("sensitivity_columns") or {}).items() if c in ref}
    cols = ["water_km2", *sens_cols.values()]
    daily = ref.groupby("date", as_index=False)[cols].mean()
    o, exp, lo, hi, out, trend = _detect_one(daily[["date", "water_km2"]], interval)
    fit = pd.DataFrame({
        "date": daily["date"].dt.strftime("%Y-%m-%d"), "kind": "fit", "observed_km2": o,
        "expected_km2": exp, "lo95_km2": lo, "hi95_km2": hi, "anomaly": out,
        "anomaly_km2": o - exp, "anomaly_pct": (o - exp) / np.where(exp == 0, np.nan, exp) * 100,
        "method_lo_km2": daily[sens_cols["lo"]].to_numpy(float) if "lo" in sens_cols else np.nan,
        "method_hi_km2": daily[sens_cols["hi"]].to_numpy(float) if "hi" in sens_cols else np.nan,
    })
    fit["label_pt"] = np.where(fit["anomaly"], LABEL_PT["anomaly"], LABEL_PT["fit"])
    n, k, p_out = len(fit), int(out.sum()), 1 - interval
    info = {
        "detection_interval": interval,
        "detection_chance": {"n": n, "k_outside": k, "p_outside_each": round(p_out, 4),
                             "expected_outside": round(n * p_out, 2), "p_at_least_k": p_at_least(k, n, p_out),
                             "note_pt": (f"Com {n} pontos e faixa de {interval:.0%}, espera-se {n * p_out:.1f} fora "
                                         "por acaso; " + (f"P(>= {k} fora) = {p_at_least(k, n, p_out):.2f}." if k
                                                          else "nenhum ponto ficou fora."))},
        "trend_km2_per_day": trend,
    }
    sens = {"central": {"column": "water_km2", "trend_km2_per_day": trend,
                        "outside": fit.loc[out, "date"].tolist()}}
    for key, col in sens_cols.items():
        d = daily[["date", col]].rename(columns={col: "water_km2"})
        _, _, _, _, out_s, tr_s = _detect_one(d, interval)
        sens[key] = {"column": col, "trend_km2_per_day": tr_s, "outside": fit.loc[out_s, "date"].tolist()}
    trends = [v["trend_km2_per_day"] for v in sens.values()]
    info["detection_sensitivity"] = sens
    info["trend_range_km2_per_day"] = {"min": min(trends), "central": trend, "max": max(trends),
                                       "available": bool(sens_cols)}
    robust = set(sens["central"]["outside"])
    for v in sens.values():
        robust &= set(v["outside"])
    info["outside_all_thresholds"] = sorted(robust) if sens_cols else None
    if len(daily) >= 5:
        tr, te = daily.iloc[:-2], daily.iloc[-2:]
        info["holdout"] = {"desc": "ultimas 2 datas NISAR",
                           **_metrics(te["water_km2"], _fit_predict(tr[["date", "water_km2"]], te["date"],
                                                                    False, interval)["yhat"])}
    else:
        info["holdout"] = {"desc": "insuficiente", "mae_km2": None, "mape_pct": None, "n": 0}
    return fit, info


def seasonal_comparison(frames: dict, ids: list, fcfg: dict | None = None) -> dict:
    """Shape of the annual cycle of each pair of candidate sources: Pearson correlation of the monthly
    means over common year-months, and of the month-of-year climatologies; plus each source's
    relative amplitude (max - min of the climatology / its median)."""
    ids = [i for i in ids if i in frames]
    monthly = {i: frames[i].groupby(frames[i]["date"].dt.to_period("M"))["water_km2"].median() for i in ids}
    clim = {i: m.groupby(m.index.month).mean() for i, m in monthly.items()}
    out = {"amplitude_rel": {i: (float((c.max() - c.min()) / c.median()) if len(c) > 1 else None)
                             for i, c in clim.items()},
           "months_covered": {i: sorted(int(x) for x in c.index) for i, c in clim.items()}, "pairs": {}}

    def corr(a, b):
        j = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner").dropna()
        r = float(j["a"].corr(j["b"])) if len(j) >= 3 and j["a"].std() > 0 and j["b"].std() > 0 else None
        return r, int(len(j))
    for k, a in enumerate(ids):
        for b in ids[k + 1:]:
            r_ym, n_ym = corr(monthly[a], monthly[b])
            r_cl, n_cl = corr(clim[a], clim[b])
            out["pairs"][f"{a}~{b}"] = {"corr_monthly": r_ym, "n_months": n_ym,
                                        "corr_climatology": r_cl, "n_months_of_year": n_cl}
    fcfg = {**DEFAULT_FORECAST, **(fcfg or {})}
    out["coverage"] = {i: coverage(frames[i], fcfg) for i in ids}
    out["criteria"] = {"min_months_covered": fcfg["min_months_covered"], "min_years": fcfg["min_years"]}
    for pid, v in out["pairs"].items():
        a, b = pid.split("~")
        inc = [i for i in (a, b) if not out["coverage"][i]["complete"]]
        v["conclusive"] = not inc
        v["incomplete_sources"] = inc
    return out


def coverage(df: pd.DataFrame | None, fcfg: dict) -> dict:
    """Completeness of a source for seasonal use: calendar months with usable rows (any year)."""
    if df is None or not len(df):
        return {"complete": False, "months": [], "n_months": 0, "n_obs": 0, "years": 0.0}
    months = sorted(int(m) for m in df["date"].dt.month.unique())
    yrs = _span_years(df["date"])
    return {"complete": len(months) >= fcfg["min_months_covered"] and yrs >= fcfg["min_years"],
            "months": months, "n_months": len(months), "n_obs": int(len(df)), "years": round(yrs, 1)}


def _cov_txt(sid: str, c: dict, fcfg: dict) -> str:
    return (f"{sid}: {c['n_obs']} obs, {c['n_months']}/12 meses cobertos em {c['years']:.1f} anos "
            f"(minimo {fcfg['min_months_covered']} meses e {fcfg['min_years']:g} anos)")


def pick_forecast_source(frames: dict, fcfg: dict, reference: str) -> tuple[str | None, str]:
    """First source in forecast.sources that is complete (month coverage); returns (id, reason)."""
    notes = []
    for sid in fcfg["sources"]:
        df = frames.get(sid)
        if df is None:
            notes.append(f"{sid}: sem CSV")
            continue
        c = coverage(df, fcfg)
        if c["complete"]:
            return sid, "; ".join(notes + [f"{_cov_txt(sid, c, fcfg)} (escolhida)"])
        notes.append(f"{_cov_txt(sid, c, fcfg)}: incompleta")
    return None, "; ".join(notes) or "nenhuma fonte de previsao configurada"


def _wmedian(v, w) -> float:
    o = np.argsort(v)
    v, cw = np.asarray(v, float)[o], np.cumsum(np.asarray(w, float)[o])
    return float(v[np.searchsorted(cw, cw[-1] / 2)])


def composite(df: pd.DataFrame, days: int = 15, anchor: pd.Timestamp | None = None) -> pd.DataFrame:
    """Non-overlapping `days` windows from `anchor`: median of the ok/low rows (weighted by quality),
    dated at the median date of the window; n = rows in the window (kept as weight)."""
    anchor = df["date"].min() if anchor is None else anchor
    b = ((df["date"] - anchor).dt.days // days).rename("bin")
    rows = []
    for _, g in df.groupby(b):
        rows.append({"date": g["date"].iloc[len(g) // 2], "water_km2": _wmedian(g["water_km2"], g["weight"]),
                     "n": len(g), "weight": float(len(g)), "quality": "ok"})
    return pd.DataFrame(rows)


def trailing_composite(df: pd.DataFrame, days: int = 15) -> pd.Series:
    """Weighted median of the rows in (last date - days, last date]; dated at the last date."""
    end = df["date"].max()
    g = df[df["date"] > end - pd.Timedelta(days=days)]
    return pd.Series({"date": end, "water_km2": _wmedian(g["water_km2"], g["weight"]), "n": len(g)})


def _eval(pred: pd.DataFrame, target: pd.DataFrame) -> dict:
    y = target["water_km2"].to_numpy(float)
    lo, hi = pred["yhat_lower"].to_numpy(), pred["yhat_upper"].to_numpy()
    m = _metrics(y, pred["yhat"])
    m["coverage80"] = float(np.mean((y >= lo) & (y <= hi))) if len(y) else None
    return m


def compare_variants(df: pd.DataFrame, fcfg: dict, interval: float) -> dict:
    """Holdout of the last holdout_days: Prophet on individual rows vs on composites of composite_days.
    Both are scored on the same targets (test composites, and test individual rows)."""
    days = int(fcfg["composite_days"])
    cut = df["date"].max() - pd.Timedelta(days=int(fcfg["holdout_days"]))
    tr, te = df[df["date"] <= cut], df[df["date"] > cut]
    if len(te) < 2 or len(tr) <= 10:
        return {}
    te_comp = composite(te, days, anchor=df["date"].min())
    out = {}
    for name, train in (("obs", tr), (f"composto{days}", composite(tr, days))):
        seasonal = _span_years(train["date"]) >= 2.0
        p_obs = _fit_predict(train, te["date"], seasonal, interval)
        # empirical width factor: |error| / half-width on the test rows, quantile = nominal level.
        # Multiplying the Prophet half-width by it gives an interval whose holdout coverage is the
        # nominal one (measured on this same holdout, so optimistic).
        half = ((p_obs["yhat_upper"] - p_obs["yhat_lower"]) / 2).to_numpy()
        r = np.abs(te["water_km2"].to_numpy(float) - p_obs["yhat"].to_numpy()) / np.where(half > 0, half, np.nan)
        r = r[np.isfinite(r)]
        out[name] = {"n_train": int(len(train)),
                     "alvo_composto": _eval(_fit_predict(train, te_comp["date"], seasonal, interval), te_comp),
                     "alvo_obs": _eval(p_obs, te),
                     "interval_scale": float(np.quantile(r, interval, method="higher")) if len(r) else None}
    return out


def choose_variant(cmp: dict, min_cov: float) -> tuple[str, str]:
    """Lowest MAPE on the composite target among variants whose IC80 covers >= min_cov; else lowest MAPE."""
    if not cmp:
        return "obs", "holdout insuficiente; usando observacoes individuais"
    score = {k: v["alvo_composto"] for k, v in cmp.items()}
    ok = [k for k, v in score.items() if v["coverage80"] is not None and v["coverage80"] >= min_cov]
    pool = ok or list(score)
    best = min(pool, key=lambda k: score[k]["mape_pct"] if score[k]["mape_pct"] is not None else np.inf)
    txt = "; ".join(f"{k}: MAPE {v['mape_pct']:.1f}%, cobertura IC80 {v['coverage80']:.0%} (n={v['n']})"
                    for k, v in score.items())
    rule = f"menor MAPE com cobertura >= {min_cov:.0%}" if ok else "nenhuma com cobertura minima; menor MAPE"
    return best, f"{txt} -> {best} ({rule})"


def _trajectory(train: pd.DataFrame, last_date, fdates, seasonal: bool, interval: float):
    """Prophet on train; % change of yhat (and its IC80) at fdates against yhat at last_date."""
    p = _fit_predict(train, [last_date, *fdates], seasonal, interval)
    base = float(p["yhat"].iloc[0])
    f = p.iloc[1:]
    pct = lambda v: (np.asarray(v, float) / base - 1) * 100 if base else np.full(len(v), np.nan)  # noqa: E731
    return f, base, pct(f["yhat"]), pct(f["yhat_lower"]), pct(f["yhat_upper"])


def forecast_check(frames: dict, fcfg: dict, main: str, fdates, main_pct, seasonal_cmp: dict,
                   interval: float) -> dict:
    """Independent check: the same Prophet (annual seasonality, individual rows, % trajectory of the
    model) on the first available check source, at the same forecast dates. Valid only if the check
    source has observations in every month of the horizon in at least one year; otherwise
    same_direction is null with the reason. same_direction[i] = sign(check %) == sign(main %)."""
    for cid in fcfg.get("check_sources") or []:
        df = frames.get(cid)
        if df is None or cid == main:
            continue
        if len(df) < 10:
            return {"source": cid, "valid": False, "skipped": f"{len(df)} obs (< 10)", "same_direction": None}
        horizon_months = sorted({d.month for d in fdates})
        have = set(df["date"].dt.month)
        missing = [m for m in horizon_months if m not in have]
        cov = coverage(df, fcfg)
        f, base, cp, clo, chi = _trajectory(df, df["date"].max(), fdates, _span_years(df["date"]) >= 2.0, interval)
        valid = not missing and cov["complete"]
        why = []
        if not cov["complete"]:
            why.append(f"serie incompleta ({_cov_txt(cid, cov, fcfg)})")
        if missing:
            why.append(f"sem observacoes nos meses do horizonte {missing} em nenhum ano; "
                       "sazonalidade nesses meses seria extrapolada")
        same = [bool(np.sign(a) == np.sign(b)) for a, b in zip(main_pct, cp)] if valid else None
        pair_ = (seasonal_cmp.get("pairs", {}).get(f"{main}~{cid}")
                 or seasonal_cmp.get("pairs", {}).get(f"{cid}~{main}") or {})
        return {"source": cid, "valid": valid,
                "skipped": None if valid else "; ".join(why), "coverage": cov,
                "n_obs": int(len(df)), "last_obs": df["date"].max().strftime("%Y-%m-%d"),
                "base_yhat_src": base, "horizon_months": horizon_months,
                # values only when the check is valid (an invalid one extrapolates, e.g. negative area)
                "weeks": ([{"date": d.strftime("%Y-%m-%d"), "forecast_pct": float(a), "lo80_pct": float(lo),
                            "hi80_pct": float(hi), "main_pct": float(m), "same_direction": same[k]}
                           for k, (d, a, lo, hi, m) in enumerate(zip(fdates, cp, clo, chi, main_pct))]
                          if valid else None),
                "forecast_pct": [float(a) for a in cp] if valid else None, "same_direction": same,
                "r_seasonal": pair_.get("corr_monthly"), "r_seasonal_n_months": pair_.get("n_months")}
    return {"source": None, "valid": False, "skipped": "nenhuma fonte de checagem disponivel", "same_direction": None}


def forecast(frames: dict, cals: dict, tests: dict, scfg: dict) -> tuple[pd.DataFrame, dict]:
    """B. Prophet with annual seasonality on the forecast source, in its own scale, trained on
    individual rows or on composites, whichever wins the 90-day holdout."""
    fcfg, interval = scfg["forecast"], float(scfg["interval"])
    ref_id = scfg["reference"]
    seasonal_cmp = seasonal_comparison(frames, list(fcfg["sources"]) + list(fcfg.get("check_sources") or []), fcfg)
    sid, why = pick_forecast_source(frames, fcfg, ref_id)
    info = {"forecast_source": sid, "forecast_source_reason": why, "seasonal_comparison": seasonal_cmp,
            "level_calibrated": False,
            "forecast_base": None, "forecast_holdout": None, "forecast_variant": None,
            "forecast_variants": None}
    if sid is None:
        return pd.DataFrame(), info
    df = frames[sid]
    cmp = compare_variants(df, fcfg, interval)
    variant, vwhy = choose_variant(cmp, float(fcfg["min_coverage"]))
    info.update(forecast_variants=cmp, forecast_variant=variant, forecast_variant_reason=vwhy,
                forecast_holdout=cmp.get(variant))
    train = df if variant == "obs" else composite(df, int(fcfg["composite_days"]))
    seasonal = _span_years(train["date"]) >= 2.0
    # forecast_pct = trajectory of the model itself: yhat(week k) / yhat(last observation date) - 1,
    # IC80 the same way (no noisy observed base)
    last_date = df["date"].iloc[-1]
    fdates = pd.date_range(last_date, periods=int(fcfg["horizon"]) + 1, freq=fcfg["step"])[1:]
    p, base, fpct, fpct_lo, fpct_hi = _trajectory(train, last_date, fdates, seasonal, interval)
    yhat, ylo, yhi = (p[c].to_numpy() for c in ("yhat", "yhat_lower", "yhat_upper"))
    hv = cmp.get(variant) or {}
    scale = hv.get("interval_scale")
    raw_cov = (hv.get("alvo_obs") or {}).get("coverage80")
    if scale:
        ylo, yhi = yhat - scale * (yhat - ylo), yhat + scale * (yhi - yhat)
        fpct_lo, fpct_hi = (ylo / base - 1) * 100, (yhi / base - 1) * 100
    info["forecast_interval"] = {
        "nominal": interval, "coverage_holdout_prophet": raw_cov,
        "n_holdout": (hv.get("alvo_obs") or {}).get("n"), "scale": scale,
        "note_pt": (f"Faixa do Prophet ajustada pela cobertura medida no holdout de {fcfg['holdout_days']} d: "
                    f"cobertura original {raw_cov:.0%} em n={(hv.get('alvo_obs') or {}).get('n')}; "
                    f"meia-largura x {scale:.2f} para cobrir {interval:.0%} no mesmo holdout (otimista: "
                    "medido nos dados usados para ajustar)") if scale and raw_cov is not None else
                   "Faixa do Prophet sem ajuste (holdout insuficiente)"}

    # level in NISAR scale
    cal = cals.get(sid)
    z = norm.ppf(0.5 + interval / 2)
    if cal is not None:
        info["level_calibrated"] = True
        km2 = cal.apply(yhat)
        half = np.sqrt(((cal.apply(yhi) - cal.apply(ylo)) / 2) ** 2 + (z * cal.sd_km2) ** 2)
        lo_km2, hi_km2 = km2 - half, km2 + half
        info["level_method"] = f"calibracao {cal.model} aprovada no portao"
    else:
        x, y, w, _ = pair(df, frames[ref_id].assign(value=frames[ref_id]["water_km2"]), int(scfg["pair_window_days"]))
        try:
            k, _, _, ci = propfit(x, y, scfg["calibration_gate"]["bootstrap"])
            info["level_method"] = (f"nivel em km2 NAO publicado (expected/lo/hi_km2 = null): fonte reprovada no "
                                    f"portao; k proporcional indicativo {k:.3f} (IC95 {ci[0]:.3f}-{ci[1]:.3f})")
            info["level_k"], info["level_k_ci95"] = k, ci
        except CalibrationError:
            info["level_method"] = "nivel em km2 NAO publicado: sem pares com NISAR"
        km2 = lo_km2 = hi_km2 = np.full_like(yhat, np.nan)
    rows = pd.DataFrame({
        "date": fdates.strftime("%Y-%m-%d"), "kind": "forecast", "observed_km2": np.nan,
        "expected_km2": km2, "lo80_km2": lo_km2, "hi80_km2": hi_km2,
        "anomaly": False, "anomaly_km2": np.nan, "anomaly_pct": np.nan,
        "label_pt": LABEL_PT["forecast"],
        "forecast_pct": fpct, "lo80_pct": fpct_lo, "hi80_pct": fpct_hi,
        "expected_src_km2": yhat, "lo80_src_km2": ylo, "hi80_src_km2": yhi,
        "forecast_source": sid, "level_calibrated": info["level_calibrated"],
    })
    check = forecast_check(frames, fcfg, sid, fdates, fpct, seasonal_cmp, interval)
    info["forecast_check"] = check
    rows["check_same_direction"] = (pd.Series(check["same_direction"], dtype="object")
                                    if check.get("same_direction") is not None else None)
    obs_med = trailing_composite(df, int(fcfg["composite_days"]))
    info["forecast_base"] = {"date": last_date.strftime("%Y-%m-%d"), "water_km2_src": base,
                             "kind": "modelo (yhat na data da ultima observacao)", "variant": variant,
                             "observed_median_15d": float(obs_med["water_km2"]), "observed_n_15d": int(obs_med["n"])}
    info["forecast_seasonal"] = seasonal
    return rows, info


def run_model(frames: dict, scfg: dict | None = None, data_notes: dict | None = None) -> dict:
    scfg = {**DEFAULTS, **(scfg or {})}
    scfg["calibration_gate"] = {**DEFAULT_GATE, **(scfg.get("calibration_gate") or {})}
    scfg["forecast"] = {**DEFAULT_FORECAST, **(scfg.get("forecast") or {})}
    ref_id, interval = scfg["reference"], float(scfg["interval"])
    cals, skipped, tests = calibrate_all(frames, ref_id, int(scfg["pair_window_days"]), scfg["calibration_gate"])
    obs = observations(frames, cals)

    dcfg = {**DEFAULT_DETECTION, **(scfg.get("detection") or {})}
    fit, dinfo = detect(frames[ref_id], dcfg)
    fc, finfo = forecast(frames, cals, tests, scfg)
    model = pd.concat([fit, fc], ignore_index=True) if len(fc) else fit
    for c in ("lo95_km2", "hi95_km2", "method_lo_km2", "method_hi_km2", "lo80_km2", "hi80_km2",
              "forecast_pct", "lo80_pct", "hi80_pct", "expected_src_km2", "lo80_src_km2", "hi80_src_km2",
              "forecast_source", "level_calibrated", "check_same_direction"):
        if c not in model:
            model[c] = np.nan

    metrics = {
        "phase": 1, "reference": ref_id, "interval": interval,
        "detection": "so NISAR, dentro da amostra (tendencia + changepoints, sem sazonalidade anual), faixa de 95%",
        "calibration": {s: asdict(c) for s, c in cals.items()},
        "calibration_tests": tests,
        "skill": {s: t.get("skill") for s, t in tests.items()},
        "sources_skipped": skipped, "sources_missing": [],
        **dinfo,
        "n_anomalies": int(fit["anomaly"].sum()), "n_reference_dates": int(len(fit)),
        **finfo,
    }
    metrics["data_notes"] = data_notes or {}
    notes = {s["id"]: s.get("notes_pt") or [] for s in scfg.get("sources", []) if s.get("notes_pt")}
    metrics["limitations_pt"] = limitations(cals, skipped, frames, ref_id, finfo, notes, metrics)
    return {"observations": obs, "model": model, "metrics": metrics}


def limitations(cals: dict, skipped: dict, frames: dict, ref_id: str, finfo: dict,
                notes: dict | None = None, m: dict | None = None) -> list[str]:
    ref = frames[ref_id]
    out = [
        f"O NISAR so cobre {ref['date'].min():%d/%m/%Y} a {ref['date'].max():%d/%m/%Y} (estacao seca): a deteccao "
        "compara cada data com a propria serie NISAR (tendencia), sem sazonalidade anual, e a faixa de "
        f"{ref['water_km2'].min():.0f}-{ref['water_km2'].max():.0f} km2 e estreita demais para calibrar bem outras fontes.",
    ]
    for s, c in cals.items():
        if s == ref_id:
            continue
        if c.via:
            out.append(f"{s}: calibrada em cadeia via {c.via}; incerteza propagada (sd {c.sd_km2:.0f} km2).")
        if c.pairing == "mensal":
            out.append(f"{s}: calibrada por medias mensais, sem pares de poucos dias.")
    m = m or {}
    if m.get("detection_chance"):
        out.append("Deteccao: " + m["detection_chance"]["note_pt"] + " Pontos fora da faixa sao 'fora da faixa "
                   "esperada', nao prova de mudanca.")
    tr = m.get("trend_range_km2_per_day") or {}
    if tr.get("available"):
        sens = m.get("detection_sensitivity", {})
        cols = ", ".join(f"{k}={v['column']}" for k, v in sens.items() if k != "central")
        rob = m.get("outside_all_thresholds")
        out.append(f"Sensibilidade ao limiar do NISAR ({cols}): tendencia de {tr['min']:+.2f} a {tr['max']:+.2f} "
                   f"km2/dia (central {tr['central']:+.2f}); fora da faixa em todos os limiares: "
                   f"{', '.join(rob) if rob else 'nenhuma data'}. A area em km2 depende do limiar; leia valores relativos.")
    elif m:
        out.append("Sensibilidade ao limiar do NISAR ainda nao calculada (faltam colunas water_km2_lo/hi).")
    for s, n in (m.get("data_notes") or {}).items():
        if "normalize_coverage" in n:
            out.append(f"{s}: area normalizada pela cobertura valida (fracao de agua x {n['normalize_coverage']['full_area_km2']:.0f} "
                       "km2), para tirar o vies de nuvem/cobertura parcial.")
        if n.get("outliers_dropped", {}).get("dates"):
            od = n["outliers_dropped"]
            out.append(f"{s}: {len(od['dates'])} linhas descartadas ({od['rule']}; ex.: fumaca lida como terra): "
                       f"{', '.join(od['dates'])}.")
    for s, why in skipped.items():
        out.append(f"{s}: sem nivel em escala NISAR ({why}).")
    for s, ns in (notes or {}).items():
        if s in frames:
            out.extend(f"{s}: {n}" for n in ns)
    sc = finfo.get("seasonal_comparison") or {}
    for pair_id, v in sc.get("pairs", {}).items():
        a, b = pair_id.split("~")
        if not v.get("conclusive", True):
            out.append(f"Comparacao da forma sazonal {a} x {b} adiada: serie incompleta "
                       f"({', '.join(_cov_txt(i, sc['coverage'][i], sc.get('criteria', DEFAULT_FORECAST)) for i in v['incomplete_sources'])}).")
            continue
        amp = sc["amplitude_rel"]
        fmt = lambda x: "-" if x is None else f"{x:.2f}"  # noqa: E731
        out.append(f"Forma sazonal {a} x {b}: correlacao das medias mensais {fmt(v['corr_monthly'])} "
                   f"(n={v['n_months']} meses), da climatologia {fmt(v['corr_climatology'])} "
                   f"(n={v['n_months_of_year']}); amplitude relativa {a} {fmt(amp.get(a))}, {b} {fmt(amp.get(b))}.")
    if finfo["forecast_source"] is None:
        out.append(f"Sem previsao: nenhuma serie historica completa ({finfo['forecast_source_reason']}).")
    else:
        src = finfo["forecast_source"]
        out.append(f"A previsao usa {src} na escala da propria fonte; a saida principal e a variacao relativa "
                   f"(%) da trajetoria do proprio modelo, frente ao valor previsto na data da ultima observacao "
                   f"({finfo['forecast_base']['date']}).")
        if not finfo["level_calibrated"]:
            out.append(f"Previsao so em %: {finfo['level_method']}.")
        if finfo.get("forecast_interval"):
            out.append(finfo["forecast_interval"]["note_pt"] + ".")
        out.append(f"Escolha da fonte de previsao: {finfo['forecast_source_reason']}.")
        chk = finfo.get("forecast_check") or {}
        if chk.get("same_direction"):
            r = chk.get("r_seasonal")
            out.append(f"Checagem independente com {chk['source']} (mesmo Prophet, em %): mesma direcao em "
                       f"{sum(chk['same_direction'])}/{len(chk['same_direction'])} semanas; correlacao sazonal "
                       f"{'-' if r is None else f'{r:.2f}'} (n={chk.get('r_seasonal_n_months')} meses).")
        elif chk.get("skipped"):
            out.append(f"Sem checagem independente valida ({chk.get('source') or '-'}: {chk['skipped']}).")
        if finfo.get("forecast_variant_reason"):
            out.append(f"Treino da previsao (holdout {finfo['forecast_variant']}): {finfo['forecast_variant_reason']}.")
        if str(finfo.get("forecast_variant", "")).startswith("composto"):
            out.append("Compostos: mediana das observacoes ok/low na janela (low com peso menor); o numero de "
                       "observacoes por composto fica registrado, mas o Prophet nao aceita pesos.")
    if any((df["quality"] == "low").any() for df in frames.values()):
        out.append("Linhas de qualidade 'low' tem peso menor so na calibracao; o Prophet nao aceita pesos.")
    out.append("A projecao extrapola o modelo; nao e medicao.")
    return out


# ---------------------------------------------------------------- export

def _records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    return json.loads(df.to_json(orient="records", double_precision=6))


def _flat(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flat(v, key + "."))
        elif isinstance(v, list):
            out[key] = " | ".join(map(str, v))
        else:
            out[key] = v
    return out


def aoi_area_km2(bbox) -> float:
    w, s, e, n = bbox
    r = 6371.0088
    return float(r ** 2 * math.radians(e - w) * (math.sin(math.radians(n)) - math.sin(math.radians(s))))


def _kept_layers(prev: dict, web_dir: Path) -> list[dict]:
    """Layers whose PNG lives under web/data/layers/ (v2). v1 layers at the root are dropped."""
    return [l for l in prev.get("layers", [])
            if str(l.get("file", "")).startswith("layers/") and (web_dir / l["file"]).exists()]


def export(res: dict, frames: dict, scfg: dict, cfg: dict, demo: bool, web_dir: Path = WEB_DATA) -> Path:
    sdir = web_dir / "series"
    sdir.mkdir(parents=True, exist_ok=True)
    obs = res["observations"].drop(columns=["weight"])
    obs.assign(date=obs["date"].dt.strftime("%Y-%m-%d")).to_csv(sdir / "observations.csv", index=False)
    (sdir / "observations.json").write_text(json.dumps(_records(obs), ensure_ascii=False))
    res["model"].to_csv(sdir / "model.csv", index=False)
    (sdir / "model.json").write_text(json.dumps(_records(res["model"]), ensure_ascii=False, indent=1))
    m = res["metrics"]
    (sdir / "metrics.json").write_text(json.dumps(m, ensure_ascii=False, indent=1))
    flat = _flat(m)
    pd.DataFrame({"key": list(flat), "value": list(flat.values())}).to_csv(sdir / "metrics.csv", index=False)

    mpath = web_dir / "manifest.json"
    try:
        prev = json.loads(mpath.read_text()) if mpath.exists() else {}
    except json.JSONDecodeError:
        prev = {}
    layers = _kept_layers(prev, web_dir)
    demo = bool(demo or any(l.get("demo") for l in layers))
    meta = {s["id"]: s for s in scfg["sources"]}
    order = [s["id"] for s in scfg["sources"] if s["id"] in frames] + [s for s in frames if s not in meta]
    sources = []
    for sid in order:
        df, mt = frames[sid], meta.get(sid, {})

        def first(c):
            return str(df[c].dropna().iloc[0]) if c in df and df[c].notna().any() else None
        sources.append({"id": sid, "label_pt": mt.get("label_pt", f"Observado ({sid})"),
                        "sensor": mt.get("sensor") or first("sensor"),
                        "product": mt.get("product") or first("product"),
                        "citation": mt.get("citation"), "n_obs": int(len(df)),
                        "first": df["date"].min().strftime("%Y-%m-%d"),
                        "last": df["date"].max().strftime("%Y-%m-%d"),
                        "calibrated": sid in m["calibration"], "skill": m["skill"].get(sid)})
    keep = {k: v for k, v in prev.items() if prev.get("schema_version") == 2 and k not in V1_KEYS}
    manifest = {
        **keep,
        "schema_version": 2, "demo": demo,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "aoi": {"name": cfg.get("name"), "bbox": cfg.get("bbox"), "area_km2": round(aoi_area_km2(cfg["bbox"]), 1)},
        "sources": sources,
        "series": {"observations": "observations.json", "model": "model.json", "metrics": "metrics.json"},
        "forecast": {"source": m["forecast_source"], "level_calibrated": m["level_calibrated"]},
        "layers": layers,
        "dates": sorted({l["date"] for l in layers if l.get("date")}),
    }
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    return mpath


# ---------------------------------------------------------------- synthetic (demo only)

def _truth(dates) -> np.ndarray:
    """SYNTHETIC 'true' open-water km2 in NISAR scale: trend + annual cycle + dip on 2026-09-03."""
    dates = pd.DatetimeIndex(dates)
    yrs = (dates - pd.Timestamp("2023-01-01")).days.to_numpy() / 365.25
    seas = 120 * np.cos(2 * np.pi * (dates.day_of_year.to_numpy() - 150) / 365.25)
    dip = -90 * np.exp(-0.5 * ((dates - pd.Timestamp("2026-09-03")).days.to_numpy() / 4.0) ** 2)
    return 300 - 10 * yrs + seas + dip


SYNTH = {  # id: (start, end, step, gain, offset, noise, sensor); raw = (truth - offset) / gain + noise
    "nisar": ("2026-07-17", "2026-10-21", "12D", 1.0, 0.0, 8.0, "NISAR L-band"),
    "opera_dswx_hls": ("2023-01-03", "2025-01-10", "5D", 0.8, 40.0, 15.0, "HLS optical"),
    "s1_rtc": ("2023-01-07", "2026-11-12", "12D", 1.3, -20.0, 10.0, "Sentinel-1 C-band"),
}


def synthetic(ids=("nisar", "opera_dswx_hls", "s1_rtc"), seed: int = 0) -> dict:
    """SYNTHETIC sources in contract format (product = SYNTHETIC). Never a result.
    opera_dswx_hls only covers 2023-2024, so it is calibrated in chain via s1_rtc."""
    rng = np.random.default_rng(seed)
    out = {}
    for sid in ids:
        start, end, step, gain, off, noise, sensor = SYNTH[sid]
        d = pd.date_range(start, end, freq=step)
        raw = ((_truth(d) - off) / gain + rng.normal(0, noise, len(d))).clip(5)
        q = np.where(rng.random(len(d)) < 0.05, "low", "ok")
        out[sid] = clean(pd.DataFrame({
            "date": d, "source": sid, "sensor": sensor, "water_km2": raw, "water_partial_km2": np.nan,
            "valid_km2": 11800.0, "valid_frac": 1.0, "method": "SYNTHETIC", "quality": q,
            "product": "SYNTHETIC"}), sid)
    return out


# ---------------------------------------------------------------- entry points

def run(demo: bool = False, web_dir: Path | None = None, horizon: int | None = None) -> dict:
    cfg = load_config()
    scfg = series_config(cfg)
    if horizon:
        scfg["forecast"]["horizon"] = horizon
    if demo:
        frames, missing, data_notes = synthetic(), [], {}
        scfg = {**scfg, "sources": [{"id": s} for s in frames]}
        web_dir = web_dir or DEMO_WEB
        print(f"ATENCAO: dados SINTETICOS (demo: true). Saida em {web_dir}, nao em web/data.")
    else:
        frames, missing, data_notes = load_sources(scfg)
        web_dir = web_dir or WEB_DATA
        if scfg["reference"] not in frames:
            raise SystemExit(f"Falta data/series/{scfg['reference']}.csv (referencia). Use --demo para testar.")
    res = run_model(frames, scfg, data_notes)
    res["metrics"]["sources_missing"] = missing
    demo = demo or is_synthetic(frames)
    path = export(res, frames, scfg, cfg, demo, web_dir)
    m = res["metrics"]
    tr = m["trend_range_km2_per_day"]
    print(f"deteccao (so {m['reference']}, faixa {m['detection_interval']:.0%}): fora {m['n_anomalies']}/"
          f"{m['n_reference_dates']} ({m['detection_chance']['note_pt']}); tendencia {m['trend_km2_per_day']:+.2f} "
          f"km2/dia (faixa {tr['min']:+.2f}..{tr['max']:+.2f}, sensibilidade={tr['available']}); holdout {m['holdout']}")
    print(f"previsao: fonte {m['forecast_source']} ({m['forecast_source_reason']}); "
          f"level_calibrated={m['level_calibrated']}; holdout {m['forecast_holdout']}")
    for s, t in m["calibration_tests"].items():
        fmt = lambda v, f: "-" if v is None else format(v, f)  # noqa: E731
        print(f"  {s}: {'APROVADA' if t['passed'] else 'reprovada'} {t.get('model')} coef={fmt(t.get('coef'), '.3f')} "
              f"LOO={fmt(t.get('loo_mape_pct'), '.1f')}% const={fmt(t.get('loo_const_pct'), '.1f')}% "
              f"skill={fmt(t.get('skill'), '.2f')} n={t.get('n')} {t.get('pairing') or ''}"
              f"{' via ' + t['via'] if t.get('via') else ''}")
    if missing:
        print(f"  sem CSV: {', '.join(missing)}")
    print(f"demo={demo} -> {path}")
    return res


def calibration_only() -> dict:
    """Calibration fits on the real CSVs, without Prophet."""
    scfg = series_config()
    frames, missing, _ = load_sources(scfg)
    _, _, tests = calibrate_all(frames, scfg["reference"], int(scfg["pair_window_days"]), scfg["calibration_gate"])
    for s, t in tests.items():
        print(f"{s}: {t}")
    if missing:
        print(f"sem CSV: {', '.join(missing)}")
    return tests

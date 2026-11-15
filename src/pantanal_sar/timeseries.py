"""Open-water area time series modelled with Prophet (detection first, projection second).

Inputs (contract in data/series/, CSV UTF-8, ISO dates):
  nisar_water.csv       date,water_km2,water_frac,valid_km2,threshold_db,track,source        (Lagoa)
  mapbiomas_water.csv   date(1st of month),water_km2,source,collection                      (Baia)
  opera_dswx_water.csv  date,water_km2,water_partial_km2,clear_frac,n_scenes,source         (Baia)

Phases
  1  NISAR 2026 only (track 132, ~12-day revisit, < 1 year). Annual seasonality cannot
     be estimated, so the model is trend + changepoints only. "Expected" is the in-sample
     fit; an anomaly is an observation outside the uncertainty interval.
  2  MapBiomas history + NISAR brought to MapBiomas units. Annual seasonality on.
     "Expected" for the NISAR dates comes from a model trained on history only
     (out-of-sample), so anomalies are departures from what the past predicts.

Calibration path (recorded in metrics and in web/data/manifest.json):
  direto  MapBiomas = a + b * NISAR on overlapping months.
  ponte   MapBiomas and NISAR do not overlap (MapBiomas ends 2025). OPERA DSWx-HLS bridges:
          (a) MapBiomas = a1 + b1 * DSWx on the months of BRIDGE_YEAR;
          (b) DSWx = a2 + b2 * NISAR on DSWx dates within +-PAIR_WINDOW_DAYS of each NISAR
              date (monthly means if fewer than 3 pairs);
          composed: MapBiomas = (a1 + b1*a2) + (b1*b2) * NISAR,
          residual sd = sqrt(sd1^2 + b1^2 * sd2^2) (independent residuals).
  fase1   no calibration possible.
The calibration sd is added in quadrature to the model interval when flagging anomalies.

Outputs: data/series/model_fit.csv, model_components.csv, model_metrics.csv,
web/data/water_series.json and the "water_series" entry of web/data/manifest.json.
Rows after the last observation are a PROJECTION (kind="projecao"), never a measurement.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from .config import ROOT, WEB_DATA

SERIES = ROOT / "data" / "series"
NISAR_CSV = SERIES / "nisar_water.csv"
MAPBIOMAS_CSV = SERIES / "mapbiomas_water.csv"
DSWX_CSV = SERIES / "opera_dswx_water.csv"
INTERVAL = 0.80           # width of the uncertainty interval
MIN_YEARS_SEASONAL = 2.0  # annual seasonality only with >= 2 years of data
YEARLY_ORDER = 3          # low Fourier order: monthly data, order 10 wiggles between months
MONTH_MID_SHIFT = pd.Timedelta(days=14)  # MapBiomas monthly value sits mid-month
BRIDGE_YEAR = 2025        # MapBiomas <-> DSWx fit year
PAIR_WINDOW_DAYS = 4      # DSWx <-> NISAR pairing window
MIN_SCENES = 3            # DSWx monthly composites with fewer valid scenes are discarded
MIN_PAIRS = 3
DSWX_COL = "water_km2"    # open water (class 1): same physical target as MapBiomas and the NISAR dark mask
DSWX_SENS_COLS = ("water_km2", "water_partial_km2")  # sensitivity: open + partial surface water

for _name in ("prophet", "cmdstanpy"):
    logging.getLogger(_name).setLevel(logging.WARNING)


class CalibrationError(ValueError):
    """Not enough overlap to calibrate."""


@dataclass
class LinFit:
    a: float
    b: float
    n: int
    r2: float | None
    sd: float      # residual standard deviation (km2)
    method: str    # linear | ratio


@dataclass
class Calibration:
    """Maps NISAR km2 to MapBiomas-equivalent km2."""
    path: str      # direto | ponte
    a: float
    b: float
    sd: float      # residual sd of the full chain (km2)
    steps: dict = field(default_factory=dict)  # name -> LinFit as dict (+ pairing info)

    def apply(self, x):
        return self.a + self.b * np.asarray(x, dtype=float)

    def flat(self) -> dict:
        out = {"path": self.path, "a": self.a, "b": self.b, "sd_km2": self.sd}
        for name, st in self.steps.items():
            out.update({f"{name}_{k}": v for k, v in st.items()})
        return out


# ---------------------------------------------------------------- loading

def _load(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["date"]).sort_values("date").reset_index(drop=True)


NISAR_COL = "water_km2_fixed"  # fixed -16.75 dB threshold; per-date Otsu hit its bound on 08-22 and 09-03


def load_nisar(path: Path = NISAR_CSV, col: str = NISAR_COL) -> pd.DataFrame:
    """NISAR series with `col` as water_km2 (original kept as water_km2_otsu)."""
    df = _load(path)
    if col in df and col != "water_km2":
        df = df.assign(water_km2_otsu=df["water_km2"], water_km2=df[col])
    df.attrs["nisar_column"] = col if col in df else "water_km2"
    return df


load_mapbiomas = lambda path=MAPBIOMAS_CSV: _load(path)  # noqa: E731
load_dswx = lambda path=DSWX_CSV: _load(path)            # noqa: E731


# ---------------------------------------------------------------- calibration

def linfit(x, y, allow_ratio: bool = False) -> LinFit:
    """OLS y = a + b x, with R2 and residual sd. n<3: ratio through origin if allowed."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n >= 3 and np.ptp(x) > 0:
        b, a = np.polyfit(x, y, 1)
        res = y - (a + b * x)
        ss = np.sum((y - y.mean()) ** 2)
        r2 = float(1 - np.sum(res ** 2) / ss) if ss > 0 else None
        sd = float(np.sqrt(np.sum(res ** 2) / (n - 2))) if n > 2 else 0.0
        return LinFit(float(a), float(b), n, r2, sd, "linear")
    if allow_ratio and n >= 1 and x.sum() > 0:
        b = float(y.sum() / x.sum())
        sd = float(np.std(y - b * x, ddof=1)) if n > 1 else float("nan")
        return LinFit(0.0, b, n, None, sd, "ratio")
    raise CalibrationError(f"pontos insuficientes para ajuste linear (n={n})")


def _monthly(df: pd.DataFrame, col: str = "water_km2") -> pd.Series:
    return df.assign(month=df["date"].dt.to_period("M")).groupby("month")[col].mean()


def _clear(dswx: pd.DataFrame, cols=(DSWX_COL,)) -> pd.DataFrame:
    """Rows with >= MIN_SCENES valid scenes; column "water_km2" replaced by the sum of cols."""
    d = dswx
    if "n_scenes" in d:
        d = d[d["n_scenes"].fillna(0) >= MIN_SCENES]
    return d.assign(water_km2=d[list(cols)].sum(axis=1, min_count=len(cols)))


def _is_monthly(dswx: pd.DataFrame) -> bool:
    """Monthly composites (dated on the 1st): pairing by day window is meaningless."""
    gaps = dswx["date"].sort_values().diff().dt.days.dropna()
    return bool((dswx["date"].dt.day == 1).all() and (gaps.empty or gaps.median() >= 25))


def calibrate_direct(nisar: pd.DataFrame, mapbiomas: pd.DataFrame) -> Calibration:
    both = pd.concat([_monthly(nisar).rename("x"), _monthly(mapbiomas).rename("y")],
                     axis=1, join="inner").dropna()
    if both.empty:
        raise CalibrationError(
            f"Sem sobreposicao NISAR {nisar['date'].min():%Y-%m}..{nisar['date'].max():%Y-%m} x "
            f"MapBiomas {mapbiomas['date'].min():%Y-%m}..{mapbiomas['date'].max():%Y-%m}")
    f = linfit(both["x"], both["y"], allow_ratio=True)
    return Calibration("direto", f.a, f.b, f.sd, {"direto": asdict(f)})


def pair_dswx_nisar(nisar: pd.DataFrame, dswx: pd.DataFrame, window: int = PAIR_WINDOW_DAYS,
                    cols=(DSWX_COL,)):
    """(x=NISAR, y=DSWx, pairing). DSWx rows within +-window days of a NISAR date are
    averaged; monthly DSWx composites, or fewer than MIN_PAIRS pairs, use monthly means."""
    d = _clear(dswx, cols)
    xs, ys = [], []
    for date, val in ([] if _is_monthly(d) else zip(nisar["date"], nisar["water_km2"])):
        near = d[(d["date"] - date).abs() <= pd.Timedelta(days=window)]
        if len(near):
            xs.append(val)
            ys.append(near["water_km2"].mean())
    if len(xs) >= MIN_PAIRS:
        return np.array(xs), np.array(ys), f"janela +-{window} d"
    both = pd.concat([_monthly(nisar).rename("x"), _monthly(d).rename("y")], axis=1, join="inner").dropna()
    return both["x"].to_numpy(), both["y"].to_numpy(), "mensal"


def bridge_step_a(mapbiomas: pd.DataFrame, dswx: pd.DataFrame, bridge_year: int = BRIDGE_YEAR,
                  cols=(DSWX_COL,)) -> LinFit:
    """MapBiomas = a1 + b1 * DSWx on the months of bridge_year (DSWx months with n_scenes >= 3)."""
    both = pd.concat([_monthly(_clear(dswx, cols)).rename("x"), _monthly(mapbiomas).rename("y")],
                     axis=1, join="inner").dropna()
    yr = both[both.index.year == bridge_year]
    if len(yr) < MIN_PAIRS:
        raise CalibrationError(f"ponte (a): {len(yr)} meses MapBiomas x DSWx em {bridge_year} (minimo {MIN_PAIRS})")
    return linfit(yr["x"], yr["y"])


def bridge_step_b(nisar: pd.DataFrame, dswx: pd.DataFrame, cols=(DSWX_COL,)) -> tuple[LinFit, str]:
    """DSWx = a2 + b2 * NISAR."""
    x, y, pairing = pair_dswx_nisar(nisar, dswx, cols=cols)
    if len(x) < MIN_PAIRS:
        raise CalibrationError(f"ponte (b): {len(x)} pares DSWx x NISAR (minimo {MIN_PAIRS})")
    return linfit(x, y), pairing


def calibrate_bridge(nisar: pd.DataFrame, mapbiomas: pd.DataFrame, dswx: pd.DataFrame,
                     bridge_year: int = BRIDGE_YEAR, cols=(DSWX_COL,)) -> Calibration:
    """Two linear steps through OPERA DSWx-HLS, composed (see module docstring)."""
    f1 = bridge_step_a(mapbiomas, dswx, bridge_year, cols)
    f2, pairing = bridge_step_b(nisar, dswx, cols)
    a = f1.a + f1.b * f2.a
    b = f1.b * f2.b
    sd = float(np.sqrt(f1.sd ** 2 + (f1.b * f2.sd) ** 2))
    return Calibration("ponte", a, b, sd, {
        "a_mapbiomas_dswx": {**asdict(f1), "year": bridge_year},
        "b_dswx_nisar": {**asdict(f2), "pairing": pairing},
    })


def bridge_sensitivity(mapbiomas: pd.DataFrame | None, dswx: pd.DataFrame, nisar: pd.DataFrame | None = None,
                       bridge_year: int = BRIDGE_YEAR) -> dict:
    """Open water only (used) vs open + partial (sensitivity): a, b, R2, n of each step and
    of the composition, plus the deltas (partial - open). Steps that cannot run are skipped."""
    out = {}
    for tag, cols in (("aberta", (DSWX_COL,)), ("aberta_parcial", DSWX_SENS_COLS)):
        if mapbiomas is not None:
            try:
                f1 = bridge_step_a(mapbiomas, dswx, bridge_year, cols)
                out.update({f"{tag}_a_{k}": getattr(f1, k) for k in ("a", "b", "r2", "n")})
            except CalibrationError:
                pass
        if nisar is not None:
            try:
                f2, pairing = bridge_step_b(nisar, dswx, cols)
                out.update({f"{tag}_b_{k}": getattr(f2, k) for k in ("a", "b", "r2", "n", "sd")})
                out[f"{tag}_b_pairing"] = pairing
                if mapbiomas is None:
                    continue
                c = calibrate_bridge(nisar, mapbiomas, dswx, bridge_year, cols)
                out.update({f"{tag}_comp_a": c.a, f"{tag}_comp_b": c.b, f"{tag}_comp_sd": c.sd})
            except CalibrationError:
                pass
    for k in [k for k in out if k.startswith("aberta_") and not k.startswith("aberta_parcial")]:
        alt = "aberta_parcial_" + k[len("aberta_"):]
        if (alt in out and isinstance(out[k], float) and isinstance(out[alt], float)
                and not k.endswith("_n")):
            out["delta_" + k[len("aberta_"):]] = out[alt] - out[k]
    return out


def calibrate(nisar, mapbiomas, dswx=None) -> Calibration:
    """Direct if MapBiomas overlaps NISAR, else bridge through DSWx, else CalibrationError."""
    try:
        return calibrate_direct(nisar, mapbiomas)
    except CalibrationError as e:
        if dswx is None or not len(dswx):
            raise CalibrationError(f"{e}; sem DSWx para ponte") from e
        try:
            return calibrate_bridge(nisar, mapbiomas, dswx)
        except CalibrationError as e2:
            raise CalibrationError(f"{e}; {e2}") from e2


def harmonize(nisar: pd.DataFrame, mapbiomas: pd.DataFrame | None = None,
              cal: Calibration | None = None) -> pd.DataFrame:
    """Single tabular series: ds, y (km2), source. MapBiomas months that overlap the
    NISAR period are dropped (NISAR is kept as the 2026 observation)."""
    nis = pd.DataFrame({
        "ds": nisar["date"],
        "y": cal.apply(nisar["water_km2"]) if cal else nisar["water_km2"].astype(float),
        "y_raw": nisar["water_km2"].astype(float),
        "source": "NISAR",
    })
    if mapbiomas is None:
        return nis.reset_index(drop=True)
    first = nisar["date"].min().to_period("M").to_timestamp()
    hist = mapbiomas[mapbiomas["date"] < first]
    mb = pd.DataFrame({
        "ds": hist["date"] + MONTH_MID_SHIFT,
        "y": hist["water_km2"].astype(float),
        "y_raw": hist["water_km2"].astype(float),
        "source": "MapBiomas",
    })
    return pd.concat([mb, nis], ignore_index=True).sort_values("ds").reset_index(drop=True)


# ---------------------------------------------------------------- model

def make_model(train: pd.DataFrame, seasonal: bool | None = None):
    from prophet import Prophet

    span_years = (train["ds"].max() - train["ds"].min()).days / 365.25
    if seasonal is None:
        seasonal = span_years >= MIN_YEARS_SEASONAL
    n = len(train)
    kw = dict(growth="linear", yearly_seasonality=YEARLY_ORDER if seasonal else False, weekly_seasonality=False,
              daily_seasonality=False, interval_width=INTERVAL, uncertainty_samples=1000)
    if not seasonal:
        # Short series: few changepoints, otherwise the trend just interpolates the points.
        kw.update(n_changepoints=max(0, min(3, n - 3)), changepoint_range=0.9,
                  changepoint_prior_scale=0.05)
    return Prophet(**kw)


def _fit_predict(train: pd.DataFrame, ds: pd.Series, seasonal: bool | None = None) -> pd.DataFrame:
    np.random.seed(0)
    m = make_model(train, seasonal)
    m.fit(train[["ds", "y"]])
    return m.predict(pd.DataFrame({"ds": pd.to_datetime(ds)}))


def _future_dates(last: pd.Timestamp, step: str, horizon: int) -> pd.DatetimeIndex:
    return pd.date_range(last, periods=horizon + 1, freq=step)[1:]


def _metrics(obs, pred) -> dict:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    err = pred - obs
    nz = obs != 0
    return {"mae_km2": float(np.mean(np.abs(err))),
            "mape_pct": float(np.mean(np.abs(err[nz] / obs[nz])) * 100) if nz.any() else None,
            "n": int(len(obs))}


def holdout(series: pd.DataFrame, phase: int, k: int | None = None) -> dict:
    """Phase 2: last 2 years of MapBiomas. Phase 1: last 2 NISAR dates (weak, n=2)."""
    if phase == 2:
        hist = series[series["source"] == "MapBiomas"]
        cut = hist["ds"].max() - pd.DateOffset(years=2)
        tr, te = hist[hist["ds"] <= cut], hist[hist["ds"] > cut]
        desc = "ultimos 2 anos do MapBiomas"
    else:
        k = k or 2
        if len(series) < k + 3:
            return {"holdout": "insuficiente", "n": 0}
        tr, te = series.iloc[:-k], series.iloc[-k:]
        desc = f"ultimas {k} datas NISAR"
    fc = _fit_predict(tr, te["ds"], seasonal=None if phase == 2 else False)
    return {"holdout": desc, **_metrics(te["y"], fc["yhat"])}


def run_model(nisar: pd.DataFrame, mapbiomas: pd.DataFrame | None = None,
              dswx: pd.DataFrame | None = None, phase: str | int = "auto", horizon: int = 3) -> dict:
    """Returns dict(fit, components, metrics, meta)."""
    cal, reason = None, None
    if phase in ("auto", 2) and mapbiomas is not None and len(mapbiomas):
        try:
            cal = calibrate(nisar, mapbiomas, dswx)
            phase = 2
        except CalibrationError as e:
            if phase == 2:
                raise
            reason, phase = str(e), 1
    else:
        reason = None if phase == 1 and mapbiomas is not None else "MapBiomas indisponivel"
        phase = 1

    series = harmonize(nisar, mapbiomas if phase == 2 else None, cal)
    obs = series[series["source"] == "NISAR"]

    if phase == 2:
        hist = series[series["source"] == "MapBiomas"]
        detect = _fit_predict(hist, obs["ds"])                 # out-of-sample expectation
        step = "MS"
        future = _future_dates(obs["ds"].max().to_period("M").to_timestamp(), step, horizon) + MONTH_MID_SHIFT
        proj = _fit_predict(series, future)                    # history + NISAR
        comp_src = _fit_predict(series, series["ds"])
    else:
        detect = _fit_predict(series, obs["ds"], seasonal=False)  # in-sample
        step = "12D"
        proj = _fit_predict(series, _future_dates(obs["ds"].max(), step, horizon), seasonal=False)
        comp_src = detect

    exp = detect["yhat"].to_numpy()
    o = obs["y"].to_numpy()
    # interval = model interval (+) calibration residual sd, in quadrature
    z = norm.ppf(0.5 + INTERVAL / 2)
    cal_sd = cal.sd if cal else 0.0
    half = np.sqrt(((detect["yhat_upper"] - detect["yhat_lower"]).to_numpy() / 2) ** 2 + (z * cal_sd) ** 2)
    fit_obs = pd.DataFrame({
        "ds": obs["ds"].dt.date, "kind": "observado", "source": "NISAR",
        "observed_km2": o, "observed_raw_km2": obs["y_raw"].to_numpy(),
        "expected_km2": exp, "lower_km2": exp - half, "upper_km2": exp + half,
        "cal_sd_km2": cal_sd,
        "anomaly_km2": o - exp, "anomaly_pct": np.where(exp != 0, (o - exp) / exp * 100, np.nan),
    })
    fit_obs["is_anomaly"] = (o < fit_obs["lower_km2"]) | (o > fit_obs["upper_km2"])
    fit_proj = pd.DataFrame({
        "ds": proj["ds"].dt.date, "kind": "projecao", "source": "Prophet",
        "expected_km2": proj["yhat"], "lower_km2": proj["yhat_lower"], "upper_km2": proj["yhat_upper"],
    })
    fit = pd.concat([fit_obs, fit_proj], ignore_index=True)

    comp_cols = [c for c in ("trend", "yearly") if c in comp_src]
    components = comp_src[["ds", *comp_cols]].assign(ds=lambda d: d["ds"].dt.date)

    metrics = holdout(series, phase)
    sens = bridge_sensitivity(mapbiomas, dswx, nisar) if cal and cal.path == "ponte" else None
    meta = {
        "phase": phase, "phase_reason": reason, "interval": INTERVAL,
        "calibration_path": cal.path if cal else "fase1",
        "yearly_seasonality": "yearly" in comp_cols,
        "detection": "fora da amostra (treino so historico)" if phase == 2 else "dentro da amostra (tendencia+changepoints)",
        "calibration": cal.flat() if cal else None,
        "sensitivity_partial": sens,
        "projection_step": step, "horizon": horizon,
        "nisar_column": nisar.attrs.get("nisar_column", "water_km2"),
        "n_nisar": int(len(obs)), "n_mapbiomas": int((series["source"] == "MapBiomas").sum()),
    }
    return {"fit": fit, "components": components, "metrics": metrics, "meta": meta}


# ---------------------------------------------------------------- output

def _update_manifest(web_dir: Path, entry: dict) -> None:
    """Add/replace the "water_series" key; other keys (export_web) are kept."""
    p = web_dir / "manifest.json"
    try:
        man = json.loads(p.read_text()) if p.exists() else {}
    except json.JSONDecodeError:
        man = {}
    man["water_series"] = entry
    p.write_text(json.dumps(man, indent=1, ensure_ascii=False))


def write_outputs(res: dict, demo: bool, out_dir: Path = SERIES, web_dir: Path = WEB_DATA) -> None:
    meta = res["meta"]
    out_dir.mkdir(parents=True, exist_ok=True)
    res["fit"].assign(phase=meta["phase"], calibration_path=meta["calibration_path"], demo=demo).to_csv(
        out_dir / "model_fit.csv", index=False)
    res["components"].assign(demo=demo).to_csv(out_dir / "model_components.csv", index=False)
    rows = {**res["metrics"], **{k: v for k, v in meta.items() if not isinstance(v, dict)}}
    if meta["calibration"]:
        rows.update({f"cal_{k}": v for k, v in meta["calibration"].items()})
    if meta.get("sensitivity_partial"):
        rows.update({f"sens_{k}": v for k, v in meta["sensitivity_partial"].items()})
    rows["demo"] = demo
    pd.DataFrame({"key": list(rows), "value": list(rows.values())}).to_csv(out_dir / "model_metrics.csv", index=False)

    web_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fit = res["fit"].astype(object).where(res["fit"].notna(), None)
    fit["ds"] = fit["ds"].astype(str)
    payload = {
        "demo": demo, "generated": generated,
        "meta": meta, "metrics": res["metrics"],
        "labels_pt": {"observado": "Medido (NISAR)", "esperado": "Esperado (modelo Prophet)",
                      "projecao": "Projecao (nao e medicao)", "intervalo": f"Intervalo de incerteza {int(INTERVAL*100)}%"},
        "points": fit.to_dict(orient="records"),
        "components": res["components"].assign(ds=lambda d: d["ds"].astype(str)).to_dict(orient="records"),
    }
    (web_dir / "water_series.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=float))
    _update_manifest(web_dir, {"file": "water_series.json", "demo": demo, "generated": generated,
                               "phase": meta["phase"], "calibration_path": meta["calibration_path"]})


# ---------------------------------------------------------------- synthetic (demo: true)

def _truth(dates: pd.DatetimeIndex) -> np.ndarray:
    """SYNTHETIC 'true' open-water km2: trend + annual cycle + a dip around 2026-09-03."""
    yrs = (dates - pd.Timestamp("2000-01-01")).days.to_numpy() / 365.25
    seas = 900 * np.cos(2 * np.pi * (dates.day_of_year.to_numpy() - 150) / 365.25)   # peak ~ late May
    dip = -330 * np.exp(-0.5 * ((dates - pd.Timestamp("2026-09-03")).days.to_numpy() / 4.0) ** 2)
    return 1500 - 15 * yrs + seas + dip


def synthetic(seed: int = 0, scenario: str = "ponte", dswx_monthly: bool = False) -> dict:
    """SYNTHETIC inputs, never a result. scenario: direto (MapBiomas up to 2026-10),
    ponte (MapBiomas up to 2025-12 + DSWx 2025-2026), fase1 (MapBiomas up to 2024, no DSWx).
    Sensor models: MapBiomas = truth; DSWx = 0.9 truth + 40; NISAR = (truth - 80) / 1.1."""
    rng = np.random.default_rng(seed)
    end = {"direto": "2026-10-01", "ponte": "2025-12-01", "fase1": "2024-12-01"}[scenario]
    months = pd.date_range("2000-01-01", end, freq="MS")
    mapbiomas = pd.DataFrame({"date": months,
                              "water_km2": (_truth(months + MONTH_MID_SHIFT) + rng.normal(0, 60, len(months))).clip(50),
                              "source": "SYNTHETIC", "collection": "demo"})
    dates = pd.date_range("2026-07-05", "2026-10-21", freq="12D")
    nisar = pd.DataFrame({"date": dates,
                          "water_km2": ((_truth(dates) - 80) / 1.1 + rng.normal(0, 30, len(dates))).clip(10),
                          "water_frac": np.nan, "valid_km2": 11800.0, "threshold_db": -18.0,
                          "track": 132, "source": "SYNTHETIC"})
    dswx = None
    if scenario == "ponte":
        if dswx_monthly:   # same format as the real OPERA CSV: monthly composites on the 1st
            dd = pd.DatetimeIndex([*pd.date_range("2025-01-01", "2025-12-01", freq="MS"),
                                   *pd.date_range("2026-06-01", "2026-10-01", freq="MS")])
            w = (0.9 * _truth(dd + MONTH_MID_SHIFT) + 40 + rng.normal(0, 25, len(dd))).clip(10)
            scenes = rng.integers(3, 9, len(dd))
            scenes[dd == pd.Timestamp("2025-12-01")] = 1        # like the real Dec/2025
        else:
            dd = pd.date_range("2025-01-02", "2026-11-12", freq="3D")
            w = (0.9 * _truth(dd) + 40 + rng.normal(0, 40, len(dd))).clip(10)
            scenes = rng.integers(3, 9, len(dd))
        partial = w * (0.5 + 2.0 * np.clip(_truth(dd) / 2000, 0, 1.5))   # 2-4x larger in the flood
        dswx = pd.DataFrame({"date": dd, "water_km2": w, "water_partial_km2": partial,
                             "clear_frac": rng.uniform(0.6, 1.0, len(dd)),
                             "n_scenes": scenes, "source": "SYNTHETIC"})
    return {"nisar": nisar, "mapbiomas": mapbiomas, "dswx": dswx}


def bridge_check() -> dict:
    """Calibration only, on the real CSVs available (step a needs MapBiomas, step b NISAR)."""
    if not DSWX_CSV.exists():
        raise SystemExit(f"Falta {DSWX_CSV} (Baia).")
    dswx = load_dswx()
    used = _clear(dswx)
    print(f"DSWx: {len(dswx)} meses, {len(used)} com n_scenes>={MIN_SCENES}; "
          f"descartados: {', '.join(dswx.loc[~dswx.index.isin(used.index), 'date'].dt.strftime('%Y-%m'))}")
    mapbiomas = load_mapbiomas() if MAPBIOMAS_CSV.exists() else None
    nisar = load_nisar() if NISAR_CSV.exists() else None
    if mapbiomas is None:
        print(f"Falta {MAPBIOMAS_CSV} (Baia): passo a nao testavel.")
    if nisar is None:
        print(f"Falta {NISAR_CSV} (Lagoa): passo b nao testavel.")
    else:
        print(f"NISAR: {len(nisar)} datas, coluna {nisar.attrs['nisar_column']}")
    sens = bridge_sensitivity(mapbiomas, dswx, nisar)
    for k, v in sens.items():
        print(f"  {k} = {v:.4g}" if isinstance(v, float) else f"  {k} = {v}")
    return sens


def run(demo: bool = False, phase: str | int = "auto", horizon: int = 3) -> dict:
    if demo:
        d = synthetic()
        nisar, mapbiomas, dswx = d["nisar"], d["mapbiomas"], d["dswx"]
        print("ATENCAO: dados SINTETICOS (demo: true). Nao e resultado.")
    else:
        if not NISAR_CSV.exists():
            raise SystemExit(f"Falta {NISAR_CSV} (Lagoa). Use --demo para testar.")
        nisar = load_nisar()
        mapbiomas = load_mapbiomas() if MAPBIOMAS_CSV.exists() else None
        dswx = load_dswx() if DSWX_CSV.exists() else None
        demo = any(df is not None and (df["source"].astype(str) == "SYNTHETIC").any()
                   for df in (nisar, mapbiomas, dswx))
    res = run_model(nisar, mapbiomas, dswx, phase, horizon)
    write_outputs(res, demo)
    m, mt = res["meta"], res["metrics"]
    cal = m["calibration"] or {}
    print(f"fase {m['phase']} via {m['calibration_path']} ({m['phase_reason'] or 'ok'}); "
          f"sazonalidade anual={m['yearly_seasonality']}; "
          f"anomalias={int(res['fit']['is_anomaly'].fillna(False).sum())}/{m['n_nisar']}; holdout={mt}")
    for k in ("a", "b", "sd_km2", "a_mapbiomas_dswx_r2", "a_mapbiomas_dswx_n",
              "b_dswx_nisar_r2", "b_dswx_nisar_n", "b_dswx_nisar_pairing", "direto_r2", "direto_n"):
        if k in cal:
            print(f"  cal_{k} = {cal[k]}")
    return res

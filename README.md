# Pantanal SAR

**NASA Space Apps Challenge 2026 · Dancing with the SARs**

Surface water in the northern Pantanal (Brazil) tracked with **NISAR L-band radar**, put in a
3-year context with NASA OPERA products and Sentinel-1, and modeled as a time series with
**Prophet**. The main result is **detection** (what NISAR measured in 2026 and whether it is
within the expected range); a short **projection** is a secondary, clearly labeled output.

> **Status (15/11/2026):** real data processed end to end. NISAR GCOV is a *provisional*
> product; results are exploratory, not validated science. Independent data review in
> [docs/DATA_REVIEW.md](docs/DATA_REVIEW.md).

## Results

Area of interest: bbox `[-58.3, -17.5, -57.3, -16.5]` (Paraguay River floodplain, Mato Grosso),
NISAR track 132 ascending, frame 169.

- **Detection (NISAR only, 8 dates, 17/07–21/10/2026).** Open water fell during the dry
  season: trend **-1.0 km²/day**, between -1.7 and -0.3 km²/day when the water threshold
  moves ±1 dB. The sign is robust; the magnitude is not. **No date falls outside the 95%
  expected range** (0.4 expected by chance), so we report a recession, not anomalies.
- **Map agreement.** NISAR water vs Sentinel-1 water on dates 2–3 days apart: median F1 0.74,
  kappa 0.73 (16 pairs). NISAR vs OPERA DSWx-HLS (1 date): F1 0.66, kappa 0.65.
- **Projection (next 4 weeks, % change).** Prophet with yearly seasonality on 3.8 years of
  OPERA DSWx-HLS: -1.1% to +1.5% with an 80% band of about ±43%, i.e. **stable, high
  uncertainty**. Sentinel-1 run as an independent check is also stable (-0.2% to -1.8%).
  The projection is shown only in %, because no source passed the gate to convert it to
  NISAR km².

## Data

| Source | Role | Coverage used |
|---|---|---|
| NISAR L2 GCOV provisional (ASF) | Core: open water per date (HH < -16.75 dB) | 8 dates, 2026-07-17 to 2026-10-21 (07-05 dropped: zeroed data) |
| OPERA DSWx-HLS v1 (NASA/JPL) | 3-year optical history; source of the projection | 731 dates 2023-01 to 2026-11 (169 used after cloud and smoke filters) |
| OPERA RTC-S1 v1 (Sentinel-1, NASA/JPL) | Radar history without cloud gaps; independent check | 246 dates downloaded 2023-01 to 2026-11; 109 used (track T039, VH < -22.95 dB) |
| OPERA DSWx-S1 v1 (NASA/JPL) | Check of the Sentinel-1 water map | 140 dates 2024-08 to 2026-11 |
| MapBiomas Água, Collection 5 (CC BY 4.0) | Optional 1985–2025 history | Loader ready; needs Google Earth Engine access, not used in results |

Each source is converted to the same per-date table (`data/series/<source>.csv`). Sources
are compared, not mixed: detection uses NISAR alone.

## Method (short)

1. **Water per date.** NISAR HH in dB after a Lee filter; open water = pixels darker than a
   fixed threshold (-16.75 dB, from the valley of the histogram), area in km² inside the AOI.
   The same approach is applied to Sentinel-1 VH. OPERA products are ready-made water maps
   (open-water class only).
2. **Quality.** Cloudy or partial scenes are dropped; smoke (2024) and burned land read as
   water in Sentinel-1 (Aug–Oct 2024) are flagged and removed.
3. **Detection.** Prophet trend on the NISAR series with a 95% band; also run with the
   threshold at ±1 dB to show method uncertainty.
4. **Projection.** Prophet with yearly seasonality on OPERA DSWx-HLS (water fraction of the
   valid area), output as % change, band scaled to the coverage measured on a 90-day holdout.
5. **Calibration gate.** A source is converted to NISAR km² only if it beats a constant
   predictor (n ≥ 8, skill ≥ 0.10, lower 95% bound > 0). None passed.

Details in [docs/METHOD.md](docs/METHOD.md).

## Limitations

- The method measures **open water only** (dark HH). It does not map water under vegetation:
  agreement with DSWx-HLS drops to F1 0.27 when its partial-water class is included.
- NISAR is provisional and only covers the 2026 dry season: no flood season, no yearly cycle.
- Water area depends on the threshold: ±1 dB changes it by -37% to +56%.
- The NISAR dips on 22/08 and 27/09 are not confirmed by Sentinel-1 (it sees ~115 km² more).
- Detection holdout error is high (MAPE 44% on the last 2 dates); forecast metrics reuse the
  holdout used to scale the band, so they are optimistic.
- Sentinel-1 C-band misses shallow water under vegetation (seasonal amplitude 0.14 vs 0.85
  in DSWx-HLS); DSWx-S1 is not fully independent from our Sentinel-1 map.
- No source calibrates to NISAR km², so the projection is relative (%) only.
- The projection extrapolates a model; it is not a measurement.

## Data for the frontend

The site reads only `web/data/`: `manifest.json` (index, `schema_version` 2, `demo: false`),
`series/observations|model|metrics` (JSON and CSV) and `layers/` (PNG overlays per NISAR date).
Contract: [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env                       # Earthdata login (EARTHDATA_TOKEN)

python -m pantanal_sar.cli search          # NISAR granules over the AOI
python -m pantanal_sar.cli fetch-nisar     # cut the AOI from each date
python -m pantanal_sar.cli water-series    # NISAR water per date -> data/series/nisar.csv
python -m pantanal_sar.cli fetch-opera     # OPERA DSWx-HLS / DSWx-S1 water per date
python -m pantanal_sar.cli fetch-rtc       # Sentinel-1 RTC cut to the AOI
python -m pantanal_sar.cli timeseries      # detection, projection, web/data package
python -m http.server -d web 8000          # open http://localhost:8000
pytest
```

Sentinel-1 downloads need the "Alaska Satellite Facility Data Access" app authorized in the
Earthdata profile. Setup details in [docs/SETUP.md](docs/SETUP.md).

## Layout

```
config/aoi.yaml       area, thresholds, sources, calibration gate (change region = edit this file)
src/pantanal_sar/     one module per source (gcov, opera, s1_rtc, mapbiomas), water_series, timeseries
data/series/          per-source tables (committed, small)
data/qc/              quality-control plots
web/data/             package read by the frontend
docs/                 method, data contract, data review, setup
```

## Use of AI

AI assistants (Claude Code, by Anthropic, coordinating several agents) helped plan the
project, write code, process data and draft documentation. An AI data auditor reviewed the
results ([docs/DATA_REVIEW.md](docs/DATA_REVIEW.md)). The team reviewed all outputs and
made the scope and method decisions.

## Data citations

NISAR L2 GCOV Provisional V1 (NASA/JPL, ISRO; ASF DAAC; doi:10.5067/NIL2GCOV-P1) · OPERA DSWx-HLS V1
(doi:10.5067/OPDSW-PL3V1), OPERA DSWx-S1 V1 (doi:10.5067/OPDSWS1-L3V1), OPERA RTC-S1 V1
(doi:10.5067/SNWG/OPERA_L2_RTC-S1_V1) (NASA/JPL OPERA project; PO.DAAC and ASF DAAC; derived from
Copernicus Sentinel-1 and Harmonized Landsat Sentinel-2) (alterado) · MapBiomas Água Collection 5 (CC BY 4.0).
Full citations in [NOTICE](NOTICE) and [docs/HACKATHON.md](docs/HACKATHON.md).
Libraries: Prophet, pandas, numpy, scipy, h5py, rasterio, earthaccess, requests, Leaflet.

## License

Apache-2.0 (see [LICENSE](LICENSE) and [NOTICE](NOTICE)). Third-party terms in
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

---

**Português:** área de água superficial no norte do Pantanal medida com o radar NISAR (banda L),
comparada com 3 anos de OPERA e Sentinel-1 e modelada com Prophet. Resultado principal:
detecção da recessão da água na seca de 2026 (sem datas fora da faixa esperada de 95%).
Diferencial: projeção de curto prazo em %, estável e com alta incerteza. Configuração em
[docs/SETUP.md](docs/SETUP.md).

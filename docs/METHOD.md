# Method

1. **Subset.** Cut the AOI from each GCOV granule of one track/direction/frame (same viewing geometry), average 2×2 blocks on linear power.
2. **Speckle.** Lee filter (5×5) on linear gamma0, then dB.
3. **Water per date.** Open water: HH below an Otsu threshold computed per date and clipped to [-24, -14] dB. Flooded vegetation (experimental): HH > -2 dB and HH − HV > 8 dB (double bounce).
4. **Dry-down.** Water at date *t−1* and not water at *t*.
5. **Burn scars.** HV log-ratio between consecutive dates on pixels that are land in both dates; threshold = mean − 2σ of that stable-land log-ratio. A candidate patch is kept only if a FIRMS hotspot (750 m buffer) touches it in that interval. Without FIRMS, patches are reported as unconfirmed.
6. **Relationship test.** Groups by state at first and last date: *dried*, *stayed wet*, *always dry*. Burn rate per group on pixels sampled every 1 km (limits spatial autocorrelation); odds ratio with 95% CI and chi-square. Fire reference: MCD64A1 when available, otherwise NISAR scars confirmed by FIRMS. *Stayed wet* cannot burn by construction; the meaningful comparison is *dried vs always dry*. This is an observed association, not causation.
7. **Validation.** Water vs HLS MNDWI > 0 (clouds removed with Fmask); burn vs MCD64A1. Precision, recall, F1, kappa.

## Known limitations

- NISAR GCOV is a **provisional** product (partially validated).
- Short series (June–October 2026, 12-day repeat): seasonal recession, not long-term trends.
- Wind roughens water (missed water); wet soil can look like shallow water; burn and flooding both lower backscatter (handled by excluding water and requiring FIRMS).
- MCD64A1 latency: October 2026 not yet available on 2026-11-14.
- Thresholds were not tuned on real data yet.
- (alterado) **Granule with zeroed data, 2026-07-05, track 132 frame 169** (`NISAR_L2_PR_GCOV_024_132_A_169_2005_DHDH_A_20260705T094227_..._P05023_N_F_J_001`): HHHH and HVHV are exactly 0 over about two thirds of the frame (rows 0 to ~12000 of 16200), including the whole AOI, while the `mask` layer marks those pixels as valid (value 1). Checked against the ASF copy with an HTTP range read: the bytes are identical, so the problem is in the provisional product itself, not in the download. The granule is also smaller than its neighbours (1267 MB vs ~1850 MB). Consequence: the water series starts on 2026-07-17. Guard in code: zero backscatter is treated as no data and a date with less than 50% of the AOI with valid HH (`water_series.MIN_VALID_FRAC`) is written to `data/series/nisar.csv` with `quality=drop` and gets no map layer.

## Open-water series (alterado)

- `cli water-series` uses the native 20 m grid (block-averaging to 40 m lost narrow channels and shorelines: 377 vs 289 km2 on 2026-07-17), Lee 5x5, HH in dB. `--stream` reads only the AOI window and caches it in `data/processed/nisar/`.
- Two areas per date: `water_km2` with the per-date threshold (valley between the water and land peaks of the histogram, Otsu as fallback, clipped to the bounds) and `water_km2_fixed` with a fixed -16.75 dB threshold (the 2026-07-17 valley), so dates are comparable. The absolute bias is corrected by the linear calibration against OPERA DSWx-HLS.
- QC against OPERA DSWx-HLS 2026-07-19 (Landsat 9 + Sentinel-2C, 99.6% clear; the same-day 2026-07-17 Sentinel-2B composite is only 26% clear): NISAR water vs DSWx class 1 (open water) F1 0.66, kappa 0.65. Against classes 1+2, F1 drops to 0.27, because DSWx class 2 (partial surface water) covers large wet, vegetated areas that L-band HH does not see as dark. Script: `scripts/qc_nisar_vs_dswx.py`.
- Dark south-west patches (lon -58.04 to -57.97, lat -17.38 to -17.33, ~18 km2 flagged as water): in DSWx 2026-07-19, 83% of those NISAR water pixels are class 2 (partial surface water), 12% class 1 and 4% class 0 (not water). HV is low (median -23.8 dB; reference lake -25.2 dB). Reading: shallow water with sparse emergent vegetation, not a burn scar or bare soil (optical would show class 0). Not confirmed with FIRMS (not downloaded yet).

## Sentinel-1 RTC water series (alterado, 15/11)

- `cli s1-water` (`src/pantanal_sar/s1_water.py`) reads `data/processed/s1_rtc/<date>_VV.tif` and `_VH.tif` (OPERA RTC-S1 gamma0, linear) and writes `data/series/s1_rtc.csv` (contract v2, `source=s1_rtc`).
- Same generic function as NISAR (`water_series.water_from_db`): Lee 5x5, dB, water = below threshold, 1-pixel opening, inside the AOI bbox.
- Threshold: valley of the histogram on calibration dates (2 per wet season Mar-May and 2 per dry season Aug-Oct of each year), for VV and VH. The polarization with a valley on more dates wins (tie: deeper valleys); **one fixed threshold** for the whole series = median of its valleys. Choice and histograms: `data/qc/s1_threshold.json`, `data/qc/s1/`. Starting bounds VV -24 to -13 dB, VH -30 to -18 dB (to confirm on real histograms).
- `valid_frac` uses the geodesic bbox area (11,824 km2), the same denominator for every source.
- Validation (`data/qc/s1_validation.csv`): F1/kappa on the 30 m OPERA grid against DSWx-S1 class 1 on the same date (from 2024-08; input `data/processed/opera_dswx_s1/<date>_WTR.tif`) and against NISAR (HH < -16.75 dB) for S1 dates within 3 days of a NISAR pass.
- Fix: the histogram valley used to assume that the highest peak is land; in a flood-season scene water can be the highest peak. Now land = highest peak to the right of the lowest-dB peak (NISAR thresholds unchanged).
- (alterado, 15/11) Result on the full set (246 dates, 2023-01 to 2026-11-12): VH wins (valley on 16/16 calibration dates, -22.4 to -24.4 dB; VV splits into two groups near -20.5 and -14.5 dB), **fixed threshold VH < -22.95 dB**. Lote 3 months (Jan-Feb, Jun-Jul, Nov-Dec) are not calibration dates by design.
- Footprint: each date is one track. T039 covers ~85% of the bbox (comparable series), T141 ~51% (quality=drop, < 0.6). A date whose coverage is below 97% of its track's median (missing bursts, e.g. 2026-10-12, 10 of 14) is also drop. `track` and `water_frac` are extra columns.
- Validation: S1 vs DSWx-S1 same day, 140 pairs, median F1 0.77, kappa 0.76 (S1 misses some water: almost only false negatives). S1 vs NISAR (2-3 days apart), 16 pairs, F1 0.74, kappa 0.73.
- **Limitation, 2024 drought and fire season:** T039 water rises to 364-901 km2 from 2024-08-16 to 2024-10-15 (base ~210 km2), while DSWx-S1 stays at 300-411 km2 (F1 0.33-0.47, mostly false positives). Dry, smooth or burned ground is dark in both VH and VV, so a VH+VV rule does not separate it. These dates are set to quality=drop (not low: Prophet ignores weights) with a `flag` column when either (a) same-day DSWx-S1 F1 < 0.5 with more false positives than false negatives (only from 2024-08-23), or (b) the S1/DSWx-HLS ratio (optical, quality ok, within 3 days) is > 1.5x the track's median ratio and S1 water is > 1.3x the track's median water. Flagged: 2024-08-16, 08-28, 09-09, 09-21, 10-03, 10-15. Not confirmed with FIRMS/MCD64A1 yet.

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
- (alterado) **Granule with zeroed data, 2026-07-05, track 132 frame 169** (`NISAR_L2_PR_GCOV_024_132_A_169_2005_DHDH_A_20260705T094227_..._P05023_N_F_J_001`): HHHH and HVHV are exactly 0 over about two thirds of the frame (rows 0 to ~12000 of 16200), including the whole AOI, while the `mask` layer marks those pixels as valid (value 1). Checked against the ASF copy with an HTTP range read: the bytes are identical, so the problem is in the provisional product itself, not in the download. The granule is also smaller than its neighbours (1267 MB vs ~1850 MB). Consequence: the water series starts on 2026-07-17. Guard in code: zero backscatter is treated as no data and a date enters `data/series/nisar_water.csv` only if at least 50% of the AOI has valid HH (`water_series.MIN_VALID_FRAC`).

## Open-water series (alterado)

- `cli water-series` uses the native 20 m grid (block-averaging to 40 m lost narrow channels and shorelines: 377 vs 289 km2 on 2026-07-17), Lee 5x5, HH in dB. `--stream` reads only the AOI window and caches it in `data/processed/nisar/`.
- Two areas per date: `water_km2` with the per-date threshold (valley between the water and land peaks of the histogram, Otsu as fallback, clipped to the bounds) and `water_km2_fixed` with a fixed -16.75 dB threshold (the 2026-07-17 valley), so dates are comparable. The absolute bias is corrected by the linear calibration against OPERA DSWx-HLS.
- QC against OPERA DSWx-HLS 2026-07-19 (Landsat 9 + Sentinel-2C, 99.6% clear; the same-day 2026-07-17 Sentinel-2B composite is only 26% clear): NISAR water vs DSWx class 1 (open water) F1 0.66, kappa 0.65. Against classes 1+2, F1 drops to 0.27, because DSWx class 2 (partial surface water) covers large wet, vegetated areas that L-band HH does not see as dark. Script: `scripts/qc_nisar_vs_dswx.py`.
- Dark south-west patches (lon -58.04 to -57.97, lat -17.38 to -17.33, ~18 km2 flagged as water): in DSWx 2026-07-19, 83% of those NISAR water pixels are class 2 (partial surface water), 12% class 1 and 4% class 0 (not water). HV is low (median -23.8 dB; reference lake -25.2 dB). Reading: shallow water with sparse emergent vegetation, not a burn scar or bare soil (optical would show class 0). Not confirmed with FIRMS (not downloaded yet).

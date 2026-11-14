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

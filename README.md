# Pantanal SAR

**NASA Space Apps Challenge 2026 · Dancing with the SARs**

Interactive web map of **flood recession and fires in the Pantanal (Brazil)** built on
NISAR L-band radar. NISAR sees water under vegetation and keeps seeing through smoke and
clouds during the fire season, when optical satellites are blind.

> **Status:** repository scaffold. The pipeline runs end to end on *synthetic* demo data;
> real NISAR data has not been processed yet. See [docs/SETUP.md](docs/SETUP.md).

## Data (all NASA)

| Source | Role | Why |
|---|---|---|
| NISAR GCOV (ASF) | Core: water extent and burn scars per date | Required by the challenge; L-band sees water under vegetation and through smoke |
| FIRMS (MODIS + VIIRS) | When and where fire occurred | Dates the fires and separates fire from flooding |
| MCD64A1 | How much area burned (monthly) | Independent check of the NISAR burn scars |
| HLS (Landsat + Sentinel-2) | Optical validation of the water map | Only source that checks NISAR water on the same dates in 2026 |

NISAR observes; the three others check what it shows. No layer validates itself.

Real inventory (CMR, 2026-11-14): **185 GCOV granules** over the Pantanal from 2026-06-19
to 2026-10-21, 1.4–7.5 GB each (~489 GB total). Default AOI uses **track 132 ascending,
frame 169**: 9 dates, all dual-pol (HH + HV). See `data/inventory/`.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env            # fill in Earthdata login and FIRMS key

python -m pantanal_sar.cli demo          # synthetic test, no login needed
python -m pantanal_sar.cli search        # list NISAR granules over the AOI
python -m pantanal_sar.cli fetch-nisar   # cut the AOI from each date (streaming)
python -m pantanal_sar.cli fetch-firms
python -m pantanal_sar.cli fetch-hls
python -m pantanal_sar.cli process
python -m pantanal_sar.cli export
python -m http.server -d web 8000        # open http://localhost:8000
```

## Layout

```
config/aoi.yaml          area, dates, thresholds (change region = edit this file)
data/inventory/          NISAR granule inventory (committed)
data/raw/, processed/    downloads and outputs (git-ignored)
src/pantanal_sar/        search, fetch, change detection, validation, web export
web/                     static map (Leaflet), deployable on GitHub Pages
docs/                    setup, method, hackathon checklist
```

## Method (short)

Lee speckle filter → dB → per-date water (Otsu on HH; flooded vegetation by HH double
bounce, experimental) → dry-down between dates → burn scars (HV drop on stable land, kept
only when a FIRMS hotspot touches the patch) → comparison of burn rates in areas that
dried vs areas that stayed dry → validation against HLS (water) and MCD64A1 (burn).
Details in [docs/METHOD.md](docs/METHOD.md). We report **observed relationships, not
causation**.

## Use of AI

AI assistants (Claude, by Anthropic) helped plan the project, draft code and write
documentation. All outputs were reviewed by the team. Declared per Space Apps guidance.

## License

Apache-2.0. Data citations in [docs/HACKATHON.md](docs/HACKATHON.md).

---

**Português:** mapa web interativo de recuo das cheias e queimadas no Pantanal com radar
NISAR, validado com FIRMS, MCD64A1 e HLS. Passos de configuração e downloads manuais em
[docs/SETUP.md](docs/SETUP.md).

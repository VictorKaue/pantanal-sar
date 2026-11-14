# Third-party software and data

This project depends on the open-source packages below. They are installed
from PyPI (or loaded from a CDN for Leaflet) and are not copied into this
repository. Licenses are listed from each project's published metadata; check
the installed versions (`pip show <package>`) before final submission.

| Component | Use | License |
|---|---|---|
| NumPy | arrays | BSD-3-Clause |
| SciPy | filters, statistics | BSD-3-Clause |
| scikit-image | Otsu, morphology | BSD-3-Clause |
| scikit-learn | utilities | BSD-3-Clause |
| h5py | NISAR GCOV (HDF5) | BSD-3-Clause |
| Rasterio (GDAL) | GeoTIFF I/O | BSD-3-Clause (GDAL: MIT) |
| PyYAML | config | MIT |
| Requests | HTTP | Apache-2.0 |
| python-dotenv | .env loading | BSD-3-Clause |
| earthaccess | Earthdata access | MIT |
| asf_search | ASF search | BSD-3-Clause |
| Pillow | PNG export | MIT-CMU (HPND) |
| pytest | tests | MIT |
| Leaflet | web map | BSD-2-Clause |

## Data and terms of use

- **NISAR GCOV (provisional)**: NASA open data policy; provisional and only
  partially validated. Results are not final science products.
- **MCD64A1, HLS**: NASA LP DAAC, open and free; cite the DOIs in
  `docs/HACKATHON.md`.
- **FIRMS**: free with a MAP_KEY; acknowledge NASA LANCE/FIRMS.
- **OpenStreetMap**: ODbL, attribution "(c) OpenStreetMap contributors" shown on the map.
- Earthdata credentials and the FIRMS key are personal; never commit them.

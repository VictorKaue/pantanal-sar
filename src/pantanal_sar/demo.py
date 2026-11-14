"""SYNTHETIC demo data so the pipeline and the web map can be tested before real
NISAR data arrives. Every output is flagged demo=true and the map shows a banner.
Never present these numbers as results.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

import numpy as np
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from . import export_web, pipeline
from .config import PROCESSED, ROOT, WEB_DATA, load_config
from .gcov import write_tif

DEMO_DIR = PROCESSED / "demo"


def _scene(rng, shape, water, burned):
    """Gamma0 (linear) for HH and HV with gamma-distributed speckle."""
    hh_db = np.full(shape, -8.0) + rng.normal(0, 1.0, shape)
    hv_db = np.full(shape, -14.0) + rng.normal(0, 1.0, shape)
    hh_db[water], hv_db[water] = -20.0, -27.0
    hv_db[burned & ~water] -= 5.0
    hh_db[burned & ~water] -= 2.0
    looks = 8
    speckle = lambda: rng.gamma(looks, 1 / looks, shape)
    return (10 ** (hh_db / 10) * speckle()).astype("float32"), (10 ** (hv_db / 10) * speckle()).astype("float32")


def make(seed: int = 7) -> None:
    cfg = load_config()
    rng = np.random.default_rng(seed)
    shape, res = (400, 400), 250.0
    w, s, e, n = cfg["bbox"]
    crs = "EPSG:32721"
    xs, ys = warp_transform("EPSG:4326", crs, [w, e], [n, s])
    transform = from_origin(xs[0], ys[0], (xs[1] - xs[0]) / shape[1], (ys[0] - ys[1]) / shape[0])
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    river = np.abs(xx - 200 - 40 * np.sin(yy / 40)) < 8
    lake = ((yy - 150) ** 2 + (xx - 120) ** 2) < 70 ** 2
    radius = {0: 70, 1: 45, 2: 30, 3: 25}
    fire_zone = ((yy - 150) ** 2 + (xx - 175) ** 2) < 45 ** 2
    other_fire = ((yy - 320) ** 2 + (xx - 320) ** 2) < 30 ** 2
    dates = cfg["nisar"]["dates"]
    folder = DEMO_DIR / "nisar"
    if folder.exists():
        shutil.rmtree(folder)
    burned = np.zeros(shape, bool)
    for i, d in enumerate(dates):
        water = river | (((yy - 150) ** 2 + (xx - 120) ** 2) < radius[min(i, 3)] ** 2)
        if i >= 2:
            burned |= fire_zone & ~water
        if i >= 3:
            burned |= other_fire
        hh, hv = _scene(rng, shape, water, burned)
        write_tif(folder / f"{d}_HHHH.tif", hh, transform, crs)
        write_tif(folder / f"{d}_HVHV.tif", hv, transform, crs)
    # synthetic hotspots inside the fire zones, dated between pairs
    rows = []
    for (zy, zx, r, d) in [(150, 175, 40, dates[2]), (320, 320, 25, dates[3])]:
        for _ in range(25):
            py, px = zy + rng.uniform(-r, r) * 0.7, zx + rng.uniform(-r, r) * 0.7
            x, y = transform * (px, py)
            lon, lat = warp_transform(crs, "EPSG:4326", [x], [y])
            rows.append({"latitude": lat[0], "longitude": lon[0], "acq_date": d, "acq_time": "1700",
                         "source": "DEMO", "frp": round(rng.uniform(5, 60), 1)})
    with open(folder / "firms_demo.csv", "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print(f"synthetic scenes for {dates} -> {folder}")


def run() -> None:
    make()
    pipeline.run(folder=DEMO_DIR / "nisar", out_dir=DEMO_DIR, demo=True)
    export_web.run(processed=DEMO_DIR, web_data=WEB_DATA, firms_csv=DEMO_DIR / "nisar" / "firms_demo.csv")

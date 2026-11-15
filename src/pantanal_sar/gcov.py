"""Read NISAR GCOV (HDF5), cut the AOI and save GeoTIFFs.

Two ways to get the data (both need Earthdata Login):
  * stream (default): open the remote .h5 with earthaccess and read only the AOI
    window. Avoids downloading ~1.9 GB per scene.
  * download: fetch the whole .h5 to data/raw/nisar/ and cut locally. Use it if
    streaming is slow or fails.

Internal layout (confirmed with `cli inspect` on a real granule, 14/11/2026, (alterado)):
  science/LSAR/GCOV/grids/frequencyA/{HHHH,HVHV}  linear gamma0 backscatter, 20 m, NaN fill
  .../xCoordinates, .../yCoordinates              pixel-centre coordinates (m), attribute
                                                  pixel_coordinate_convention = "center"
  .../projection                                  scalar EPSG + attribute epsg_code (e.g. 32721)
  .../mask                                        subswath number; 0 = partially focused
                                                  (invalid), 255 = outside the swath
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform_bounds

from .config import PROCESSED, RAW, load_config, load_env
from .nisar_search import parse_title

GRID = "science/LSAR/GCOV/grids/{freq}"


def find_epsg(grid: h5py.Group) -> int:
    if "projection" in grid:
        proj = grid["projection"]
        for key in ("epsg_code", "epsg"):
            if key in proj.attrs:
                return int(np.squeeze(proj.attrs[key]))
        val = np.squeeze(proj[()])
        if np.issubdtype(np.asarray(val).dtype, np.integer):
            return int(val)
    raise ValueError("EPSG not found in GCOV grid; run `cli inspect` and adjust find_epsg().")


def read_subset(h5: h5py.File, bbox, freq="frequencyA", pols=("HHHH", "HVHV")):
    """Return ({pol: array}, transform, crs) for the AOI window."""
    g = h5[GRID.format(freq=freq)]
    x = g["xCoordinates"][:]
    y = g["yCoordinates"][:]
    epsg = find_epsg(g)
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", f"EPSG:{epsg}", *bbox)
    ix = np.where((x >= minx) & (x <= maxx))[0]
    iy = np.where((y >= miny) & (y <= maxy))[0]
    if ix.size == 0 or iy.size == 0:
        raise ValueError("AOI does not intersect this granule.")
    x0, x1, y0, y1 = ix.min(), ix.max() + 1, iy.min(), iy.max() + 1
    dx, dy = float(x[1] - x[0]), float(y[1] - y[0])
    transform = Affine(dx, 0, float(x[x0]) - dx / 2, 0, dy, float(y[y0]) - dy / 2)
    bad = None
    if "mask" in g:
        m = g["mask"][y0:y1, x0:x1]
        bad = (m == 0) | (m == 255)
    arrays = {}
    for p in pols:
        if p not in g:
            print(f"  {p} not in granule (single-pol?), skipped")
            continue
        a = g[p][y0:y1, x0:x1].astype("float32")
        a[~np.isfinite(a) | (a <= 0)] = np.nan
        if bad is not None:
            a[bad] = np.nan
        arrays[p] = a
    return arrays, transform, f"EPSG:{epsg}"


def block_mean(a: np.ndarray, k: int) -> np.ndarray:
    """Average k x k blocks (on linear power, which is the correct domain)."""
    if k <= 1:
        return a
    h, w = (a.shape[0] // k) * k, (a.shape[1] // k) * k
    b = a[:h, :w].reshape(h // k, k, w // k, k)
    with np.errstate(invalid="ignore"):
        return np.nanmean(b, axis=(1, 3)).astype("float32")


def write_tif(path: Path, array: np.ndarray, transform, crs, nodata=np.nan) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
                   dtype=array.dtype, crs=crs, transform=transform, nodata=nodata,
                   compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array, 1)


def _find_granules(cfg):
    import earthaccess

    n = cfg["nisar"]
    w, s, e, nn = cfg["bbox"]
    out = {}
    for d in n["dates"]:
        res = earthaccess.search_data(short_name=n["short_name"], temporal=(d, d),
                                      bounding_box=(w, s, e, nn))
        match = []
        for g in res:
            title = g["umm"]["GranuleUR"]
            info = parse_title(title)
            if (info["track"] == n["track"] and info["direction"] == n["direction"]
                    and info["frame"] == n["frame"]):
                match.append(g)
        if not match:
            print(f"  {d}: no granule for track {n['track']} frame {n['frame']}")
            continue
        out[d] = match[0]
    return out


def fetch(mode: str = "stream") -> None:
    """Cut the AOI from each configured date and save to data/processed/nisar/."""
    import earthaccess

    load_env()
    earthaccess.login(strategy="environment" if _has_env() else "interactive")
    cfg = load_config()
    n, k = cfg["nisar"], cfg["processing"]["downsample"]
    granules = _find_granules(cfg)
    for d, g in granules.items():
        print(f"{d}: {g['umm']['GranuleUR']}")
        if mode == "download":
            paths = earthaccess.download([g], local_path=str(RAW / "nisar"))
            src = h5py.File(paths[0], "r")
        else:
            fobj = earthaccess.open([g])[0]
            src = h5py.File(fobj, "r")
        with src as h5:
            arrays, transform, crs = read_subset(h5, cfg["bbox"], n["frequency"], n["polarizations"])
        for pol, a in arrays.items():
            a = block_mean(a, k)
            t = transform * Affine.scale(k)
            write_tif(PROCESSED / "nisar" / f"{d}_{pol}.tif", a, t, crs)
            print(f"  saved {d}_{pol}.tif {a.shape}")


def inspect(path: str) -> None:
    """Print the HDF5 tree of a local GCOV file (to confirm dataset names)."""
    with h5py.File(path, "r") as h5:
        def show(name, obj):
            if isinstance(obj, h5py.Dataset):
                print(f"{name}  {obj.shape} {obj.dtype}")
        h5.visititems(show)


def _has_env() -> bool:
    import os
    return bool(os.environ.get("EARTHDATA_TOKEN")
                or (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")))

"""Turn processed masks into PNG overlays + manifest.json for the web map."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject

from .ancillary import load_firms
from .config import PROCESSED, WEB_DATA, load_config

# type -> (RGBA colour, source tag, PT label, EN label)
STYLE = {
    "open_water": ((30, 110, 230, 190), "measured", "Água aberta", "Open water"),
    "flooded_veg": ((0, 170, 160, 190), "measured", "Vegetação alagada (experimental)", "Flooded vegetation (experimental)"),
    "dried": ((240, 150, 30, 210), "measured", "Área que secou", "Area that dried"),
    "burn": ((220, 30, 30, 220), "measured", "Cicatriz de queimada", "Burn scar"),
    "dried_then_burned": ((200, 0, 200, 230), "derived", "Secou e depois queimou", "Dried, then burned"),
}


def _to_wgs84(path: Path, resampling):
    with rasterio.open(path) as src:
        t, w, h = calculate_default_transform(src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        dst = np.zeros((h, w), dtype=src.dtypes[0])
        if np.issubdtype(dst.dtype, np.floating):
            dst[:] = np.nan
        reproject(rasterio.band(src, 1), dst, dst_transform=t, dst_crs="EPSG:4326",
                  resampling=resampling, dst_nodata=src.nodata)
    west, north = t * (0, 0)
    east, south = t * (w, h)
    return dst, [[south, west], [north, east]]


def _mask_png(path: Path, rgba, out: Path):
    a, bounds = _to_wgs84(path, Resampling.nearest)
    img = np.zeros(a.shape + (4,), dtype="uint8")
    img[a == 1] = rgba
    Image.fromarray(img, "RGBA").save(out, optimize=True)
    return bounds


def _db_png(path: Path, out: Path, lo=-25.0, hi=0.0):
    a, bounds = _to_wgs84(path, Resampling.bilinear)
    g = np.clip((a - lo) / (hi - lo), 0, 1)
    img = np.zeros(a.shape + (4,), dtype="uint8")
    ok = np.isfinite(a)
    img[..., 0] = img[..., 1] = img[..., 2] = (np.nan_to_num(g) * 255).astype("uint8")
    img[..., 3] = np.where(ok, 255, 0)
    Image.fromarray(img, "RGBA").save(out, optimize=True)
    return bounds


def run(processed: Path | None = None, web_data: Path | None = None, firms_csv: Path | None = None) -> Path:
    cfg = load_config()
    processed = processed or PROCESSED
    web_data = web_data or WEB_DATA
    masks = processed / "masks"
    stats = json.loads((processed / "stats.json").read_text())
    web_data.mkdir(parents=True, exist_ok=True)
    layers = []

    for d in stats["dates"]:
        f = masks / f"{d}_HH_db.tif"
        if f.exists():
            b = _db_png(f, web_data / f"{d}_HH.png")
            layers.append({"id": f"{d}_HH", "type": "backscatter", "date": d, "source": "measured",
                           "label_pt": "Radar NISAR (HH, dB)", "label_en": "NISAR radar (HH, dB)",
                           "file": f"{d}_HH.png", "bounds": b})
        for t in ("open_water", "flooded_veg"):
            f = masks / f"{d}_{t}.tif"
            if f.exists():
                rgba, src, pt, en = STYLE[t]
                b = _mask_png(f, rgba, web_data / f"{d}_{t}.png")
                layers.append({"id": f"{d}_{t}", "type": t, "date": d, "source": src, "label_pt": pt,
                               "label_en": en, "color": "rgba(%d,%d,%d,%.2f)" % (*rgba[:3], rgba[3] / 255),
                               "file": f"{d}_{t}.png", "bounds": b})
    for key in stats["per_pair"]:
        d0, d1 = key.split("_")
        for t in ("dried", "burn"):
            f = masks / f"{key}_{t}.tif"
            if f.exists():
                rgba, src, pt, en = STYLE[t]
                b = _mask_png(f, rgba, web_data / f"{key}_{t}.png")
                layers.append({"id": f"{key}_{t}", "type": t, "date": d1, "date_from": d0, "source": src,
                               "label_pt": pt, "label_en": en,
                               "color": "rgba(%d,%d,%d,%.2f)" % (*rgba[:3], rgba[3] / 255),
                               "file": f"{key}_{t}.png", "bounds": b})
    f = masks / "dried_then_burned.tif"
    if f.exists():
        rgba, src, pt, en = STYLE["dried_then_burned"]
        b = _mask_png(f, rgba, web_data / "dried_then_burned.png")
        layers.append({"id": "dried_then_burned", "type": "dried_then_burned", "date": None, "source": src,
                       "label_pt": pt, "label_en": en, "color": "rgba(%d,%d,%d,%.2f)" % (*rgba[:3], rgba[3] / 255),
                       "file": "dried_then_burned.png", "bounds": b})

    pts = load_firms(firms_csv) if firms_csv else load_firms()
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
              "properties": {"date": p.get("acq_date"), "source": p.get("source", ""), "frp": p.get("frp")}}
             for p in pts]
    (web_data / "firms.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    manifest = {
        "name": cfg["name"], "bbox": cfg["bbox"], "demo": stats.get("demo", False),
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dates": stats["dates"], "layers": layers, "firms": "firms.geojson", "stats": stats,
    }
    out = web_data / "manifest.json"
    if out.exists():  # keep the entry written by timeseries.py
        try:
            prev = json.loads(out.read_text())
            if "water_series" in prev:
                manifest["water_series"] = prev["water_series"]
        except json.JSONDecodeError:
            pass
    out.write_text(json.dumps(manifest, indent=1))
    print(f"{len(layers)} layers, {len(feats)} hotspots -> {out}")
    return out

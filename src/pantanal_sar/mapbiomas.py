"""MapBiomas Agua: serie mensal de area de agua -> data/series/mapbiomas_water.csv.

A extracao (Google Earth Engine) esta em scripts/mapbiomas_water_gee.py. Este modulo
valida o CSV bruto (date,water_km2) e grava o contrato: date,water_km2,source,collection.
Dados: MapBiomas Agua, CC BY 4.0, https://plataforma.agua.mapbiomas.org/
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from .config import ROOT

SERIES_CSV = ROOT / "data" / "series" / "mapbiomas_water.csv"
FIELDS = ["date", "water_km2", "source", "collection"]
SOURCE = "MapBiomas Agua (Landsat 30 m), CC BY 4.0"


def normalize(rows, collection: str):
    """rows: iterable of (date_str, water_km2). Returns sorted contract rows.

    Dates are forced to day 1; missing/negative values are dropped; duplicates rejected.
    """
    out, seen = [], set()
    for d, v in rows:
        if v in (None, ""):
            continue
        v = float(v)
        if v < 0:
            continue
        dt = date.fromisoformat(str(d)[:10]).replace(day=1)
        if dt in seen:
            raise ValueError(f"mes duplicado: {dt}")
        seen.add(dt)
        out.append({"date": dt.isoformat(), "water_km2": round(v, 4),
                    "source": SOURCE, "collection": collection})
    return sorted(out, key=lambda r: r["date"])


def write(rows, path: Path = SERIES_CSV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_csv")
    ap.add_argument("--collection", required=True, help="ex.: 5")
    a = ap.parse_args()
    with open(a.raw_csv, encoding="utf-8") as f:
        raw = [(r["date"], r["water_km2"]) for r in csv.DictReader(f)]
    rows = normalize(raw, f"MapBiomas Agua Colecao {a.collection}")
    print("escrito", write(rows), f"({len(rows)} meses, {rows[0]['date']} a {rows[-1]['date']})")


if __name__ == "__main__":
    main()

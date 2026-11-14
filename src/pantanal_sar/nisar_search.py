"""Search NISAR GCOV granules over the AOI and write an inventory CSV.

Searching needs no login. Uses NASA CMR directly (same catalogue as ASF Vertex).
"""

from __future__ import annotations

import csv
from pathlib import Path

import requests

from .config import INVENTORY, load_config

CMR = "https://cmr.earthdata.nasa.gov/search/granules.json"


def parse_title(title: str) -> dict:
    """Split a NISAR GCOV granule name into its fields.

    Example: NISAR_L2_PR_GCOV_025_132_A_169_2005_DHDH_A_20260717T094227_..._P05023_N_F_J_001
    fields:  cycle=025 track=132 direction=A frame=169 mode=2005 pol=DHDH
    """
    p = title.split("_")
    return {
        "cycle": p[4],
        "track": int(p[5]),
        "direction": p[6],
        "frame": int(p[7]),
        "mode": p[8],
        "polarization": p[9],
        "start": p[11],
    }


def search(bbox, start, end, concept_id) -> list[dict]:
    w, s, e, n = bbox
    rows, page = [], 1
    while True:
        r = requests.get(
            CMR,
            params={
                "collection_concept_id": concept_id,
                "bounding_box": f"{w},{s},{e},{n}",
                "temporal": f"{start}T00:00:00Z,{end}T23:59:59Z",
                "page_size": 200,
                "page_num": page,
            },
            timeout=60,
        )
        r.raise_for_status()
        entries = r.json()["feed"]["entry"]
        for x in entries:
            info = parse_title(x["title"])
            url = next(
                (l["href"] for l in x.get("links", []) if l["href"].endswith(".h5")
                 and l["href"].startswith("https")), "")
            rows.append({
                "title": x["title"],
                "date": x["time_start"][:10],
                "size_mb": round(float(x.get("granule_size", 0))),
                "url": url,
                **info,
            })
        if len(entries) < 200:
            break
        page += 1
    return rows


def main() -> None:
    cfg = load_config()
    n = cfg["nisar"]
    rows = search(cfg["bbox"], n["start"], n["end"], n["collection_concept_id"])
    out = INVENTORY / f"nisar_gcov_{cfg['name']}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["track"], r["frame"], r["date"])))
    print(f"{len(rows)} granules -> {out}")
    by_track: dict = {}
    for r in rows:
        key = (r["track"], r["direction"], r["frame"])
        by_track.setdefault(key, []).append(f"{r['date']}({r['polarization']})")
    for k, v in sorted(by_track.items()):
        print(f"track {k[0]} {k[1]} frame {k[2]}: {len(v)} dates  {' '.join(v)}")


if __name__ == "__main__":
    main()

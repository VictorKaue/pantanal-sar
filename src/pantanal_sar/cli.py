"""Command line entry point.

  python -m pantanal_sar.cli search            # list NISAR granules over the AOI (no login)
  python -m pantanal_sar.cli fetch-nisar       # cut the AOI from each date (Earthdata Login)
  python -m pantanal_sar.cli fetch-nisar --download   # full download instead of streaming
  python -m pantanal_sar.cli inspect FILE.h5   # print HDF5 tree of a local GCOV file
  python -m pantanal_sar.cli water-series [FILE.h5 ...]  # open-water km2 per date -> data/series
  python -m pantanal_sar.cli fetch-firms       # FIRMS hotspots (FIRMS_MAP_KEY)
  python -m pantanal_sar.cli fetch-hls         # HLS bands for water validation (Earthdata Login)
  python -m pantanal_sar.cli fetch-opera       # OPERA DSWx-HLS water series (Earthdata Login)
  python -m pantanal_sar.cli process          # water, dry-down, burn, statistics, validation
  python -m pantanal_sar.cli export            # PNG layers + manifest for the web map
  python -m pantanal_sar.cli demo              # SYNTHETIC data end to end (testing only)
  python -m pantanal_sar.cli timeseries        # Prophet on data/series (add --demo for synthetic)
"""

from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser(prog="pantanal_sar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("search")
    f = sub.add_parser("fetch-nisar")
    f.add_argument("--download", action="store_true", help="download full .h5 instead of streaming")
    i = sub.add_parser("inspect")
    i.add_argument("path")
    ws = sub.add_parser("water-series")
    ws.add_argument("paths", nargs="*", help="local GCOV .h5 (default: data/raw/nisar/*.h5)")
    ws.add_argument("--stream", nargs="*", metavar="DATE",
                    help="read the AOI window remotely for these dates (default: nisar.dates)")
    sub.add_parser("fetch-firms")
    sub.add_parser("fetch-hls")
    sub.add_parser("process")
    sub.add_parser("export")
    sub.add_parser("demo")
    o = sub.add_parser("fetch-opera")
    o.add_argument("--start", help="YYYY-MM-DD (padrao: 2025 inteiro + 2026 jun-out)")
    o.add_argument("--end")
    o.add_argument("--search-only", action="store_true", help="so contar cenas no CMR")
    t = sub.add_parser("timeseries")
    t.add_argument("--demo", action="store_true", help="SYNTHETIC series (demo: true)")
    t.add_argument("--phase", default="auto", choices=["auto", "1", "2"])
    t.add_argument("--horizon", type=int, default=3, help="projection steps (12 days or 1 month)")
    t.add_argument("--bridge-check", action="store_true", help="only the DSWx bridge fits on real CSVs")
    a = ap.parse_args()

    if a.cmd == "search":
        from .nisar_search import main as m
        m()
    elif a.cmd == "fetch-nisar":
        from .gcov import fetch
        fetch("download" if a.download else "stream")
    elif a.cmd == "inspect":
        from .gcov import inspect
        inspect(a.path)
    elif a.cmd == "water-series":
        from .water_series import run as m
        m(a.paths, a.stream)
    elif a.cmd == "fetch-firms":
        from .ancillary import fetch_firms
        fetch_firms()
    elif a.cmd == "fetch-hls":
        from .ancillary import fetch_hls
        fetch_hls()
    elif a.cmd == "fetch-opera":
        from .opera import run
        run(a.start, a.end, a.search_only)
    elif a.cmd == "process":
        from .pipeline import run
        run()
    elif a.cmd == "export":
        from .export_web import run
        run()
    elif a.cmd == "demo":
        from .demo import run
        run()
    elif a.cmd == "timeseries":
        from .timeseries import bridge_check, run
        if a.bridge_check:
            bridge_check()
            return
        run(a.demo, a.phase if a.phase == "auto" else int(a.phase), a.horizon)


if __name__ == "__main__":
    main()

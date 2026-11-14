"""Command line entry point.

  python -m pantanal_sar.cli search            # list NISAR granules over the AOI (no login)
  python -m pantanal_sar.cli fetch-nisar       # cut the AOI from each date (Earthdata Login)
  python -m pantanal_sar.cli fetch-nisar --download   # full download instead of streaming
  python -m pantanal_sar.cli inspect FILE.h5   # print HDF5 tree of a local GCOV file
  python -m pantanal_sar.cli fetch-firms       # FIRMS hotspots (FIRMS_MAP_KEY)
  python -m pantanal_sar.cli fetch-hls         # HLS bands for water validation (Earthdata Login)
  python -m pantanal_sar.cli process           # water, dry-down, burn, statistics, validation
  python -m pantanal_sar.cli export            # PNG layers + manifest for the web map
  python -m pantanal_sar.cli demo              # SYNTHETIC data end to end (testing only)
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
    sub.add_parser("fetch-firms")
    sub.add_parser("fetch-hls")
    sub.add_parser("process")
    sub.add_parser("export")
    sub.add_parser("demo")
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
    elif a.cmd == "fetch-firms":
        from .ancillary import fetch_firms
        fetch_firms()
    elif a.cmd == "fetch-hls":
        from .ancillary import fetch_hls
        fetch_hls()
    elif a.cmd == "process":
        from .pipeline import run
        run()
    elif a.cmd == "export":
        from .export_web import run
        run()
    elif a.cmd == "demo":
        from .demo import run
        run()


if __name__ == "__main__":
    main()

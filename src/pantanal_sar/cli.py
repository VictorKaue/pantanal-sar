"""Command line entry point.

  python -m pantanal_sar.cli search            # list NISAR granules over the AOI (no login)
  python -m pantanal_sar.cli fetch-nisar       # cut the AOI from each date (Earthdata Login)
  python -m pantanal_sar.cli fetch-nisar --download   # full download instead of streaming
  python -m pantanal_sar.cli inspect FILE.h5   # print HDF5 tree of a local GCOV file
  python -m pantanal_sar.cli water-series [FILE.h5 ...]  # open-water km2 per date -> data/series
  python -m pantanal_sar.cli s1-water          # Sentinel-1 RTC water series + validation
  python -m pantanal_sar.cli fetch-firms       # FIRMS hotspots (FIRMS_MAP_KEY)
  python -m pantanal_sar.cli fetch-hls         # HLS bands for water validation (Earthdata Login)
  python -m pantanal_sar.cli fetch-opera       # OPERA DSWx-HLS water series (Earthdata Login)
  python -m pantanal_sar.cli fetch-dswx-s1    # OPERA DSWx-S1 water (Sentinel-1) per date
  python -m pantanal_sar.cli fetch-rtc         # OPERA RTC-S1 VV/VH clips -> data/processed/s1_rtc
  python -m pantanal_sar.cli process          # water, dry-down, burn, statistics, validation
  python -m pantanal_sar.cli export            # PNG layers + manifest for the web map
  python -m pantanal_sar.cli demo              # SYNTHETIC data end to end (testing only)
  python -m pantanal_sar.cli timeseries        # calibrate sources + Prophet -> web/data (contract v2)
  python -m pantanal_sar.cli timeseries --demo # SYNTHETIC, written to data/demo/web (never web/data)
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
    ws.add_argument("--cached", action="store_true",
                    help="reprocess cached AOI windows (series v2 + web layers), no network")
    ws.add_argument("--stream", nargs="*", metavar="DATE",
                    help="read the AOI window remotely for these dates (default: nisar.dates)")
    s1 = sub.add_parser("s1-water")
    s1.add_argument("--validate-only", action="store_true", help="only F1/kappa vs DSWx-S1 and NISAR")
    sub.add_parser("fetch-firms")
    sub.add_parser("fetch-hls")
    sub.add_parser("process")
    sub.add_parser("export")
    sub.add_parser("demo")
    o = sub.add_parser("fetch-opera")
    o.add_argument("--start", help="YYYY-MM-DD (padrao: 2025 inteiro + 2026 jun-out)")
    o.add_argument("--end")
    o.add_argument("--search-only", action="store_true", help="so contar cenas no CMR")
    sub.add_parser("fetch-dswx-s1")
    rt = sub.add_parser("fetch-rtc")
    rt.add_argument("--start", default="2023-01-01")
    rt.add_argument("--end", default="2026-11-14")
    rt.add_argument("--search-only", action="store_true")
    t = sub.add_parser("timeseries")
    t.add_argument("--demo", action="store_true", help="SYNTHETIC series, written to data/demo/web")
    t.add_argument("--horizon", type=int, default=None, help="forecast steps (default: config series.horizon)")
    t.add_argument("--calibration-only", action="store_true", help="only the calibration fits on real CSVs")
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
        from .water_series import run as m, run_cached
        if a.cached:
            run_cached()
        else:
            m(a.paths, a.stream)
    elif a.cmd == "s1-water":
        from .s1_water import run as s1run, validate
        if not a.validate_only:
            s1run()
        validate()
    elif a.cmd == "fetch-firms":
        from .ancillary import fetch_firms
        fetch_firms()
    elif a.cmd == "fetch-hls":
        from .ancillary import fetch_hls
        fetch_hls()
    elif a.cmd == "fetch-opera":
        from .opera import run
        run(a.start, a.end, a.search_only)
    elif a.cmd == "fetch-dswx-s1":
        from .opera_s1 import run as m
        m()
    elif a.cmd == "fetch-rtc":
        from .s1_rtc import run as m
        m(a.start, a.end, a.search_only)
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
        from .timeseries import calibration_only, run
        if a.calibration_only:
            calibration_only()
            return
        run(a.demo, horizon=a.horizon)


if __name__ == "__main__":
    main()

"""Load config/aoi.yaml and .env, and define the project paths."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "aoi.yaml"
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
INVENTORY = ROOT / "data" / "inventory"
WEB_DATA = ROOT / "web" / "data"


def load_config(path: Path | str = CONFIG) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_env() -> None:
    """Load .env if python-dotenv is installed (optional)."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def require_env(name: str, help_text: str) -> str:
    load_env()
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing {name}. {help_text} (see docs/SETUP.md)")
    return value

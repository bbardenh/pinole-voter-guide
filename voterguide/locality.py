"""The place this guide covers, loaded once from config/locality.yaml."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "config" / "locality.yaml"


@lru_cache(maxsize=1)
def load() -> dict:
    return yaml.safe_load(PATH.read_text(encoding="utf-8"))


def pattern(name: str) -> re.Pattern:
    """A case-insensitive regex from the config (area_regex, page_signal_regex, ...)."""
    return re.compile(load()[name], re.IGNORECASE)

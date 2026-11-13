"""Read module configuration relative to this file, independent of the working directory."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_ROOT = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def load_config(module: str) -> dict[str, Any]:
    path = CONFIG_ROOT / module / "config.yaml"
    with path.open(encoding="utf-8") as stream:
        values = yaml.safe_load(stream)
    if not isinstance(values, dict):
        raise ValueError(f"Configuration must be a YAML mapping: {path}")
    return values

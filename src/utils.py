"""Shared utilities: seeds, paths, config loading."""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else PROJECT_ROOT / "configs" / "default.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def set_seed(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    try:
        import tensorflow as tf

        tf.random.set_seed(seed)
    except ImportError:
        pass


def ensure_dirs(cfg: dict[str, Any] | None = None) -> dict[str, Path]:
    cfg = cfg or load_config()
    paths = {
        "raw": PROJECT_ROOT / cfg["data_raw"],
        "processed": PROJECT_ROOT / cfg["data_processed"],
        "outputs": PROJECT_ROOT / cfg["outputs"],
        "models": PROJECT_ROOT / cfg["outputs"] / "models",
        "figures": PROJECT_ROOT / cfg["outputs"] / "figures",
        "metrics": PROJECT_ROOT / cfg["outputs"] / "metrics",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths


def save_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, default=str)

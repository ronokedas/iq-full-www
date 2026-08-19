"""Identidade e caminhos isolados do Polarium Full."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Polarium Full"
APP_VERSION = "1.0.0"
EXECUTABLE_NAME = "PolariumFull.exe"
APP_USER_MODEL_ID = "PolariumFull.PerfectFirstRegister.1.0.0"


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def data_dir() -> Path:
    override = os.environ.get("POLARIUM_FULL_DATA_DIR")
    if override:
        root = Path(override).expanduser().resolve()
    elif frozen():
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "PolariumFull"
    else:
        root = Path(__file__).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_path(relative: str | Path, *, create_parent: bool = True) -> Path:
    path = data_dir() / Path(relative)
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path

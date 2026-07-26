"""Paths and isolation rules for one single-tenant installation."""
from __future__ import annotations

import os
from pathlib import Path


PRODUCT_ROOT = Path(__file__).resolve().parents[2]


def installation_root() -> Path:
    configured = os.environ.get("REPUTATION_INSTALLATION_ROOT", "").strip()
    return Path(configured).expanduser().resolve() if configured else PRODUCT_ROOT


def config_path(name: str) -> Path:
    return installation_root() / "config" / name


def data_path(name: str) -> Path:
    return installation_root() / "data" / name


def assert_isolated_installation() -> None:
    """Fail if an installation tries to hold more than one client profile."""
    profiles = list((installation_root() / "config").glob("client_profile*.json"))
    profiles = [path for path in profiles if ".template." not in path.name]
    if len(profiles) != 1 or profiles[0].name != "client_profile.json":
        raise ValueError(
            "single-tenant installation requires exactly config/client_profile.json"
        )

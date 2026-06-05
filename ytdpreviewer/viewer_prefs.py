"""Persistent YDD viewer preferences (colors)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

RgbColor = tuple[float, float, float]

PREFS_VERSION = 1


def _prefs_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "YTDPreviewer" / "viewer.json"
    return Path.home() / "AppData" / "Local" / "YTDPreviewer" / "viewer.json"


def _clamp_rgb(values: object, default: RgbColor) -> RgbColor:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return default
    try:
        rgb = tuple(max(0.0, min(1.0, float(v))) for v in values)
    except (TypeError, ValueError):
        return default
    return rgb  # type: ignore[return-value]


@dataclass
class ViewerColorPrefs:
    mesh_color: RgbColor
    edge_color: RgbColor
    vertex_color: RgbColor


def load_color_prefs(
    *,
    mesh_default: RgbColor,
    edge_default: RgbColor,
    vertex_default: RgbColor,
) -> ViewerColorPrefs:
    path = _prefs_path()
    if not path.is_file():
        return ViewerColorPrefs(mesh_default, edge_default, vertex_default)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ViewerColorPrefs(mesh_default, edge_default, vertex_default)

    if not isinstance(data, dict):
        return ViewerColorPrefs(mesh_default, edge_default, vertex_default)

    return ViewerColorPrefs(
        mesh_color=_clamp_rgb(data.get("mesh_color"), mesh_default),
        edge_color=_clamp_rgb(data.get("edge_color"), edge_default),
        vertex_color=_clamp_rgb(data.get("vertex_color"), vertex_default),
    )


def save_color_prefs(prefs: ViewerColorPrefs) -> None:
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": PREFS_VERSION,
        "mesh_color": list(prefs.mesh_color),
        "edge_color": list(prefs.edge_color),
        "vertex_color": list(prefs.vertex_color),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

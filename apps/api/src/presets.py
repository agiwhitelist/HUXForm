"""Saved presets — org-level visual defaults the Director respects.

A preset is a small JSON document that nudges the Director toward a
specific palette / typography / banned-pattern set without overriding the
per-task visual brief. The Director keeps full freedom to pick a metaphor;
presets just set the "house style" so an org's generated UIs share an
identity across sessions.

Stored at `${AGUI_DATA_DIR}/presets.json`:

  {
    "active": "default",
    "presets": {
      "default": {
        "name": "default",
        "palette":     { "bg": "#0b0d10", "ink": "#e7e9ee", "accent": "#7aa2ff" },
        "typography":  { "display": "Inter", "body": "Inter", "mono": "JetBrains Mono" },
        "banned_extra": ["pastel candy palettes"],
        "notes": "free-form note shown to the Director as house-style"
      }
    }
  }

The Director loads the active preset and injects it as an extra "house
style hint" line. Per-task brief still wins for that specific generation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


log = logging.getLogger("huxform.presets")


@dataclass
class Preset:
    name: str
    palette: dict[str, str] = field(default_factory=dict)
    typography: dict[str, str] = field(default_factory=dict)
    banned_extra: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PresetStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.active: str = "default"
        self.presets: dict[str, Preset] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.presets["default"] = Preset(name="default")
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except Exception as exc:
            log.warning("preset load failed: %s", exc)
            self.presets["default"] = Preset(name="default")
            return
        self.active = str(data.get("active") or "default")
        for name, raw in (data.get("presets") or {}).items():
            if not isinstance(raw, dict):
                continue
            self.presets[name] = Preset(
                name=str(name),
                palette=dict(raw.get("palette") or {}),
                typography=dict(raw.get("typography") or {}),
                banned_extra=[str(x) for x in (raw.get("banned_extra") or [])],
                notes=str(raw.get("notes") or ""),
            )
        if "default" not in self.presets:
            self.presets["default"] = Preset(name="default")

    def save(self) -> None:
        data = {
            "active": self.active,
            "presets": {n: p.to_dict() for n, p in self.presets.items()},
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def get_active(self) -> Preset:
        return self.presets.get(self.active) or self.presets["default"]

    def upsert(self, preset: Preset) -> None:
        self.presets[preset.name] = preset
        self.save()

    def delete(self, name: str) -> bool:
        if name == "default" or name not in self.presets:
            return False
        del self.presets[name]
        if self.active == name:
            self.active = "default"
        self.save()
        return True

    def set_active(self, name: str) -> bool:
        if name not in self.presets:
            return False
        self.active = name
        self.save()
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "presets": {n: p.to_dict() for n, p in self.presets.items()},
        }


def preset_hint(preset: Preset) -> str:
    """Render an active preset as a single-paragraph hint for the Director."""
    if not preset:
        return ""
    parts: list[str] = [f"House style preset '{preset.name}':"]
    if preset.palette:
        cols = ", ".join(f"{k}={v}" for k, v in preset.palette.items() if v)
        if cols:
            parts.append(f"  default palette anchors: {cols} (you may still deviate when the metaphor demands it)")
    if preset.typography:
        types = ", ".join(f"{k}={v}" for k, v in preset.typography.items() if v)
        if types:
            parts.append(f"  default type stacks: {types}")
    if preset.banned_extra:
        parts.append("  additional banned patterns: " + "; ".join(preset.banned_extra))
    if preset.notes:
        parts.append(f"  org notes: {preset.notes}")
    return "\n".join(parts) if len(parts) > 1 else ""

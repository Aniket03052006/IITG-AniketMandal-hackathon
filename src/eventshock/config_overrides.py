"""Apply user overrides to a raw YAML mapping *before* its strict model validates it.

An override is a dotted path to one leaf (``grouping.window_hours``) and a value. Because the patched mapping is validated by the same
pydantic model as the shipped file, a bad value is rejected by the same validators and a misspelt key by ``extra="forbid"``.
This module knows nothing about which settings may be adjusted (that whitelist is ``adjust.registry``); it only patches.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .config import ConfigError


def strip_prefix(overrides: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    """The overrides under ``prefix`` (``intelligence``), with the prefix removed from each path."""
    head = prefix + "."
    return {p[len(head):]: v for p, v in overrides.items() if p.startswith(head)}


def apply_overrides(raw: Mapping[str, Any], overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    """A deep copy of ``raw`` with each override set. An intermediate key must already exist; the last key may be new (an added edge, a new
    ticker). A value of ``None`` removes the last key. ``raw`` itself is never modified."""
    out = copy.deepcopy(dict(raw))
    for path, value in sorted((overrides or {}).items()):
        parts = path.split(".")
        node: Any = out
        for i, key in enumerate(parts[:-1]):
            if not isinstance(node, dict) or key not in node:
                raise ConfigError(f"override {path!r}: {'.'.join(parts[: i + 1])!r} does not exist in the configuration")
            node = node[key]
        if not isinstance(node, dict):
            raise ConfigError(f"override {path!r}: its parent is not a mapping")
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = copy.deepcopy(value)
    return out

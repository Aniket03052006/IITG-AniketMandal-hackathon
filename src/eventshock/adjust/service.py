"""``AdjustmentService``: list the adjustable settings, validate a change through the real config models, persist it, and hand the new overrides to whoever
rebuilds the side-cars. The shipped configs are never written."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ..config import ConfigError, _read_yaml
from ..config_overrides import strip_prefix
from ..domain import Scenario
from ..intelligence.config import IntelligenceConfig, load_intelligence_config
from ..portfolio.config import PortfolioConfig, load_portfolio_config
from ..propagation.config import PropagationConfig, load_propagation_config
from .models import AddedEdge, AdjustmentNotice, AdjustmentState, Knob, ValidationIssue, ValidationReport
from .registry import (
    _USER_EDGE,
    CONFIGS,
    SPECS,
    default_at,
    expand,
    shock_override_specs,
    spec_for,
    validate_path_value,
)
from .store import OverridesStore

NOTE = ("Adjusted values are your own assumptions. They change what the side-cars compute for everyone using this server; the shipped defaults in configs/ are "
        "unchanged and every adjusted value is shown against its default. Nothing here is validated.")


def build_effective(config_dir: Path, overrides: Mapping[str, Any]) -> tuple[IntelligenceConfig, PortfolioConfig, PropagationConfig]:
    """The three side-car configs with ``overrides`` applied. Raises ``ConfigError`` when the result is not valid."""
    return (load_intelligence_config(config_dir, strip_prefix(overrides, "intelligence")),
            load_portfolio_config(config_dir, strip_prefix(overrides, "portfolio")),
            load_propagation_config(config_dir, strip_prefix(overrides, "propagation")))


class AdjustmentService:
    def __init__(self, config_dir: Path, store: OverridesStore, scenarios: list[Scenario], default_by_category: Mapping[Any, str],
                 on_change: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._dir = config_dir
        self._store = store
        self._on_change = on_change
        self._lock = threading.RLock()
        self._defaults = {c: _read_yaml(config_dir / f"{c}.yaml") for c in CONFIGS}
        self._shock_specs = shock_override_specs(scenarios, default_by_category)
        self._shock_bounds = {p: b for p, _l, _v, b, _s in self._shock_specs}

    # ------------------------------------------------------------------------------------------------------------------ read
    def overrides(self) -> dict[str, Any]:
        return self._store.values()

    def version(self) -> str:
        return self._store.version()

    def notice(self) -> AdjustmentNotice | None:
        v = self._store.values()
        return AdjustmentNotice(count=len(v), paths=sorted(v)) if v else None

    def set_on_change(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self._on_change = fn

    def state(self) -> AdjustmentState:
        cur = self._store.values()
        knobs: list[Knob] = []
        for spec in SPECS:
            for path, caps, default in expand(spec, self._defaults):
                knobs.append(Knob(
                    path=path, group=spec.group, label=spec.label.format(*caps), description=spec.description, kind=spec.kind, unit=spec.unit,
                    min=spec.lo, max=spec.hi, choices=list(spec.choices), default=default, value=cur.get(path, default), adjusted=path in cur))
        for path, label, default, (lo, hi), _scn in self._shock_specs:
            knobs.append(Knob(path=path, group="scenario", label=label, description="Size of this base shock in the GENERATED scenario only; the catalog scenario is unchanged.",
                              kind="number", min=lo, max=hi, default=default, value=cur.get(path, default), adjusted=path in cur))
        # a user-added key of an open map (a ticker) is a knob too
        listed = {k.path for k in knobs}
        for path, value in sorted(cur.items()):
            spec = spec_for(path)
            if spec is not None and spec.open_key and path not in listed:
                knobs.append(Knob(path=path, group=spec.group, label=spec.label.format(path.rsplit(".", 1)[-1]), description=spec.description, kind=spec.kind,
                                  default=None, value=value, adjusted=True))
        added = [AddedEdge(path=p, risk_factor=m.group(1), edge_id=m.group(2), value=v) for p, v in sorted(cur.items()) if (m := _USER_EDGE.match(p))]
        return AdjustmentState(version=self._store.version(), count=len(cur), updated_at=self._store.updated_at, knobs=knobs, added_edges=added,
                               risk_factors=sorted(self._defaults['propagation'].get('risk_factors', {})), note=NOTE)

    # -------------------------------------------------------------------------------------------------------------- validate
    def validate(self, values: Mapping[str, Any], *, base: Mapping[str, Any] | None = None) -> ValidationReport:
        """Check each path against the whitelist and its bounds, then build the real configs with the change applied (cross-field rules live there)."""
        issues: list[ValidationIssue] = []
        for path, value in values.items():
            why = validate_path_value(path, value, self._defaults, self._shock_bounds)
            if why:
                issues.append(ValidationIssue(path=path, message=why))
        if issues:
            return ValidationReport(ok=False, issues=issues)
        merged = {**(base if base is not None else self._store.values()), **values}
        try:
            build_effective(self._dir, merged)
        except ConfigError as exc:
            # name the path(s) at fault: each new value on its own, over the current overrides
            current = dict(base if base is not None else self._store.values())
            for path, value in values.items():
                try:
                    build_effective(self._dir, {**current, path: value})
                except ConfigError as one:
                    issues.append(ValidationIssue(path=path, message=_short(one)))
            if not issues:
                issues.append(ValidationIssue(path=None, message=_short(exc)))
            return ValidationReport(ok=False, issues=issues)
        return ValidationReport(ok=True, issues=[])

    # ---------------------------------------------------------------------------------------------------------------- change
    def put(self, values: Mapping[str, Any]) -> ValidationReport:
        with self._lock:
            report = self.validate(values)
            if not report.ok:
                return report
            before = self._store.values()
            after = {**before, **values}
            # a value equal to its shipped default is no adjustment: drop it so "adjusted" always means "different"
            for p in list(after):
                same, dv = default_at(p, self._defaults)
                if same and not _USER_EDGE.match(p) and dv == after[p]:
                    del after[p]
            self._commit(before, after)
            return report

    def reset(self, path: str | None = None) -> None:
        with self._lock:
            before = self._store.values()
            after = {} if path is None else {k: v for k, v in before.items() if k != path}
            if path is not None and path not in before:
                raise KeyError(path)
            self._commit(before, after)

    def _commit(self, before: dict[str, Any], after: dict[str, Any]) -> None:
        self._store.replace(after)
        if self._on_change is not None:
            try:
                self._on_change(after)
            except Exception:
                self._store.replace(before)  # the side-cars could not be rebuilt on it: keep the file and the running state in agreement
                if self._on_change is not None:
                    self._on_change(before)
                raise


def _short(exc: Exception) -> str:
    """A validation error without pydantic's input echo and docs link."""
    text = re.sub(r"\s*\[type=.*?(?=\n|$)", "", str(exc))
    text = re.sub(r"^invalid [^:]*: \d+ validation errors? for \w+\s*", "", text.strip())
    msgs = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("For further information")]
    return " ".join(msgs[:3])[:400]

"""What EventShock knows about an instrument a user types: the 34 issuers, a short reference table, or nothing.

Three tiers, always reported as such (``FieldSource``): the entity master (sector, country; trailing beta from ``betas.json``), the
reference table in ``data/portfolio/instruments.json`` (index and bond funds, indicative durations), and "unknown" (no reference data:
the resolver then uses a labelled default or asks the user).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import ConfigError
from ..domain import Entity
from .betas import IssuerBetas

INSTRUMENTS_PATH = Path("data") / "portfolio" / "instruments.json"


@dataclass(frozen=True)
class Reference:
    ticker: str
    name: str
    asset_class: str
    sector: str
    region: str
    beta: float | None = None
    duration: float | None = None
    spread_sensitivity: float | None = None
    entity_id: str | None = None
    basis: str = ""
    kind: str = "REFERENCE"  # ISSUER | REFERENCE


class InstrumentCatalog:
    def __init__(self, entities: list[Entity], betas: IssuerBetas | None, reference: dict[str, Reference],
                 beta_floor: float = 0.0, beta_cap: float = 3.0) -> None:
        self._issuers: dict[str, Reference] = {}
        for e in entities:
            if not e.ticker:
                continue
            fit = betas.get(e.ticker) if betas else None
            beta = min(max(fit["beta"], beta_floor), beta_cap) if fit else None
            basis = "one of the 34 issuers EventShock can name"
            if fit and betas:
                basis += (f"; beta {beta:.2f} = OLS {fit['beta_ols']:.2f} (se {fit['se']:.2f}, R² {fit['r2']:.2f}) shrunk to {fit['beta']:.2f} over the "
                          f"{betas.data['window_sessions']} sessions to {betas.as_of}")
                if beta != fit["beta"]:
                    basis += f", then clipped to [{beta_floor:g}, {beta_cap:g}] (a stress does not carry a negative one-year co-movement into a sell-off)"
            self._issuers[e.ticker.upper()] = Reference(
                ticker=e.ticker.upper(), name=e.name, asset_class="EQUITY", sector=e.sector, region=e.country,
                beta=beta, entity_id=e.entity_id, basis=basis, kind="ISSUER")
        self._ref = reference

    @classmethod
    def load(cls, repo_root: Path, entities: list[Entity], betas: IssuerBetas | None, beta_floor: float = 0.0, beta_cap: float = 3.0) -> InstrumentCatalog:
        p = repo_root / INSTRUMENTS_PATH
        if not p.is_file():
            raise ConfigError(f"missing {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        ref = {}
        for r in data["instruments"]:
            t = r["ticker"].upper()
            ref[t] = Reference(ticker=t, name=r["name"], asset_class=r["asset_class"], sector=r["sector"], region=r["region"],
                               beta=r.get("beta"), duration=r.get("duration"), spread_sensitivity=r.get("spread_sensitivity"), basis=r.get("basis", ""))
        return cls(entities, betas, ref, beta_floor, beta_cap)

    def lookup(self, ticker: str) -> Reference | None:
        t = ticker.upper()
        return self._issuers.get(t) or self._ref.get(t)

    @property
    def issuer_tickers(self) -> list[str]:
        return sorted(self._issuers)

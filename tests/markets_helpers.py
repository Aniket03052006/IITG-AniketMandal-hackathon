"""Builders for the external-market tests: macro events with a resolved theme, the synthetic fixture provider, and a MarketService over real grouping/scope."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from eventshock.config import REPO_ROOT
from eventshock.domain import EventCategory
from eventshock.markets.config import load_markets_config
from eventshock.markets.provider import PointProvider, load_point_provider
from eventshock.markets.service import MarketService
from tests.intel_helpers import sig
from tests.monitor_helpers import FakeAssess, FakeProp, monitor

MCFG = load_markets_config(REPO_ROOT / "configs")
FIXTURE = REPO_ROOT / "data" / "fixtures" / "external_markets" / "markets.json"

FED = "Federal Reserve signals a rate cut as inflation cools and Powell hints at easing at the next FOMC meeting"
CPI = "US inflation surprises to the upside as consumer prices rise faster, CPI report shows"
JOBS = "US unemployment rises as payrolls disappoint, jobs report shows jobless claims climbing"
TARIFF = "US imposes new tariffs and tariff rates rise, escalating the trade war on imports"
DEFAULT = "Debt ceiling standoff raises fears of a US default on its debt, credit rating downgrade risk grows"
COMPANY = "JPMorgan Chase fined $920 million over spoofing by US regulators"


def macro(sid: str, text: str, *, minutes: int = 0, category: EventCategory = EventCategory.MACROECONOMIC, source: str = "Wire A"):  # noqa: ANN201
    return sig(sid, text, minutes=minutes, category=category, source=source, url=f"https://{source.lower().replace(' ', '')}.example/{sid}")


def fixture_provider(**kw) -> PointProvider:  # noqa: ANN003
    return load_point_provider(FIXTURE, name="kalshi", previous_gap_hours=kw.pop("gap", MCFG.providers.kalshi.previous_gap_hours), expect_synthetic=True)


def service(signals, *, provider=None, severity: float = 8.0, event_type: str = "MACROECONOMIC", prop=None, tmp: Path | None = None, as_of=None, **mcfg):  # noqa: ANN001, ANN003, ANN201
    """(MarketService, monitor) over real grouping and scope with chosen assessments."""
    from eventshock.markets.models import ProviderCategory, ProviderState
    end = max(s.document.published_at for s in signals) + timedelta(hours=12) if as_of is None else as_of      # the replay clock sits just after the latest report
    mon, repo, _ = monitor(signals, assess=FakeAssess(default=severity, event_type=event_type), prop=prop or FakeProp(level={s.id: "HIGH" for s in signals}, share={s.id: 0.3 for s in signals}),
                           tmp=tmp, as_of=end)
    cfg = MCFG if not mcfg else MCFG.model_copy(update=mcfg)
    state = ProviderState(provider="kalshi", category=ProviderCategory.PREDICTION_MARKET, state="UNAVAILABLE", mode="off", reason="test: no provider")
    svc = MarketService(cfg, provider, mon, clock=lambda: end, state=state)
    return svc, mon

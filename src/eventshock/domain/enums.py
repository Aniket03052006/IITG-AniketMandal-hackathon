"""Closed vocabularies shared by every layer (API, engine, fixtures, UI)."""

from enum import StrEnum


class EventCategory(StrEnum):
    """The PRD's eight-class event taxonomy (docs: PRD §11.2)."""

    GEOPOLITICAL = "GEOPOLITICAL"
    MACROECONOMIC = "MACROECONOMIC"
    CREDIT_FUNDING = "CREDIT_FUNDING"
    MA_CORPORATE_ACTION = "MA_CORPORATE_ACTION"
    REGULATORY_LEGAL = "REGULATORY_LEGAL"
    PRODUCT_OPERATIONS = "PRODUCT_OPERATIONS"
    EARNINGS_FINANCIAL_PERFORMANCE = "EARNINGS_FINANCIAL_PERFORMANCE"
    MARKET_VALUATION = "MARKET_VALUATION"


class EventStatus(StrEnum):
    """What the event stage is willing to claim about a document (the taxonomy itself is unchanged).

    CLASSIFIED: a market event of ``category``.
    NO_EVENT: the model judges the text is not a market event (chatter, promotion, opinion, a notice).
        ``category`` is then only its best guess *if* it were one, and must not be shown as a finding.
    UNCERTAIN: probably an event, but the model will not commit to a type (low confidence, or a class
        its model card flags unreliable).
    """

    CLASSIFIED = "CLASSIFIED"
    NO_EVENT = "NO_EVENT"
    UNCERTAIN = "UNCERTAIN"


class SourceType(StrEnum):
    NEWS = "NEWS"
    SOCIAL = "SOCIAL"


class SignalStatus(StrEnum):
    """COMPLETE: all stages produced output. PARTIAL: a stage failed; nothing is invented."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


class DataOrigin(StrEnum):
    """Whether a signal was computed by a model or comes from a pinned demo fixture."""

    DEMO_FIXTURE = "DEMO_FIXTURE"
    # Real documents run through the real ingestion pipeline; sentiment/event/impact are still
    # placeholder rules (see ``SignalProvenance.stage_origins``), not trained models.
    REAL_SOURCE_PLACEHOLDER_NLP = "REAL_SOURCE_PLACEHOLDER_NLP"
    # Real documents where at least one stage (sentiment, event type) is a trained model and the rest (impact)
    # are still placeholder rules. Which is which is recorded per signal in
    # ``SignalProvenance.stage_origins``.
    REAL_SOURCE_MIXED_NLP = "REAL_SOURCE_MIXED_NLP"
    MODEL_OUTPUT = "MODEL_OUTPUT"
    # a run of the scenario lab: no signal, no model; every shock is a value a person chose (a SCENARIO ASSUMPTION)
    USER_SCENARIO = "USER_SCENARIO"


class RunMode(StrEnum):
    REPLAY = "REPLAY"
    LIVE = "LIVE"


class AssetClass(StrEnum):
    EQUITY = "EQUITY"
    BOND = "BOND"
    LOAN = "LOAN"
    DERIVATIVE = "DERIVATIVE"
    # user-portfolio only (the synthetic wholesale book never holds them):
    CASH = "CASH"  # value is fixed by definition: no shock moves it, and it is not "uncovered"
    OTHER = "OTHER"  # no revaluation rule exists: held at its value, listed as not stressed


class RiskFactor(StrEnum):
    """Scenario risk factors. Units are fixed per factor (see ``FACTOR_UNITS``)."""

    EQUITY = "EQUITY"  # fractional return, e.g. -0.10
    RATES_BPS = "RATES_BPS"  # parallel yield shift, basis points
    CREDIT_SPREAD_BPS = "CREDIT_SPREAD_BPS"  # spread widening, basis points
    PD_MULTIPLIER = "PD_MULTIPLIER"  # probability-of-default multiplier (>= 1 is adverse)
    LGD_ADD = "LGD_ADD"  # additive loss-given-default, fraction
    # Scenario-lab factors. Exposure is data on the position (``PortfolioAsset.currency`` / ``commodity_sensitivity``), never a prior inside the engine; a position that carries none is not moved.
    FX_PCT = "FX_PCT"  # change in the value of a foreign currency against the portfolio's base currency, fraction (names its currency)
    COMMODITY_PCT = "COMMODITY_PCT"  # change in the price of crude oil, fraction


FACTOR_UNITS: dict[RiskFactor, str] = {
    RiskFactor.EQUITY: "%",
    RiskFactor.RATES_BPS: "bp",
    RiskFactor.CREDIT_SPREAD_BPS: "bp",
    RiskFactor.PD_MULTIPLIER: "x",
    RiskFactor.LGD_ADD: "pp",
    RiskFactor.FX_PCT: "%",
    RiskFactor.COMMODITY_PCT: "%",
}

# the factors only a user-built scenario applies (no catalog scenario and no propagation mapping uses them)
LAB_FACTORS = (RiskFactor.FX_PCT, RiskFactor.COMMODITY_PCT)


class ShockScope(StrEnum):
    """Who a shock applies to. Most specific applicable scope wins: ISSUER > SECTOR > MARKET."""

    MARKET = "MARKET"
    SECTOR = "SECTOR"  # the signal entity's sector
    ISSUER = "ISSUER"  # the signal entity itself


SCOPE_SPECIFICITY: dict[ShockScope, int] = {
    ShockScope.MARKET: 0,
    ShockScope.SECTOR: 1,
    ShockScope.ISSUER: 2,
}


class StressStatus(StrEnum):
    COMPLETED = "COMPLETED"
    NOT_TRIGGERED = "NOT_TRIGGERED"  # impact below threshold and not forced
    NO_SCENARIO = "NO_SCENARIO"  # no template maps to the event category
    UNAVAILABLE = "UNAVAILABLE"  # signal has no impact score (PARTIAL); never fabricated
    NOT_APPLICABLE = "NOT_APPLICABLE"  # the scenario has no shock that reaches what this event is about


UNKNOWN_ENTITY = "UNKNOWN_ENTITY"

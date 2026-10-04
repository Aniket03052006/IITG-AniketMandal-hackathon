"""A scripted language-model client: the real provider is never called from a test."""

from __future__ import annotations

from typing import Any

from eventshock.llm.client import LLMBadOutput, LLMError, LLMRateLimited, LLMTimeout


class FakeLLM:
    """Returns canned tool-call arguments, or raises a scripted error. Counts its calls so a test can prove a cache hit made none."""

    model_id = "fake-llm-1"

    def __init__(self, answer: dict[str, Any] | None = None, *, error: LLMError | None = None) -> None:
        self.answer, self.error, self.calls = answer, error, 0

    def extract(self, *, system: str, user: str, tool_name: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.answer is not None
        return dict(self.answer)


def timeout() -> LLMTimeout:
    return LLMTimeout("timed out")


def rate_limited() -> LLMRateLimited:
    return LLMRateLimited("HTTP 429")


def bad_output() -> LLMBadOutput:
    return LLMBadOutput("no tool call")


# The seven required cases (task brief). `answer` is what a well-behaved model would return for the text; `expect` is what must hold of the reading.
REGULATORY = "European regulators propose stricter capital requirements for major banks, potentially increasing funding costs."
MONETARY = "The Federal Reserve signals that interest rates may remain elevated for longer as inflation remains persistent."
GEOPOLITICAL = "Escalating tensions threaten oil supply routes, sending crude prices sharply higher."
EARNINGS = "A major technology company cuts its revenue outlook because of weaker cloud demand."
MNA = "A major semiconductor company agrees to acquire a software business in a multibillion-dollar transaction."
UNKNOWN = "Quantum Dynamics announces a major restructuring following weaker-than-expected demand."

CASES: dict[str, dict[str, Any]] = {
    "regulatory": dict(text=REGULATORY, event="REGULATORY_LEGAL", sectors=["Financials"], regions=["EU"],
                       answer=dict(event_type="REGULATORY_LEGAL", event_subtype="capital_requirements", event_confidence=0.9, sentiment=-0.3,
                                   sectors=["Financials"], regions=["EU"], affected_asset_classes=["EQUITY", "LOAN"],
                                   severity_indicators=["capital_requirement_change", "funding_cost_increase"], uncertainty=0.2,
                                   entities=[dict(surface="European regulators", kind="REGULATOR", role="subject")],
                                   evidence=[dict(quote="stricter capital requirements", supports="event_type"),
                                             dict(quote="increasing funding costs", supports="severity")])),
    "monetary": dict(text=MONETARY, event="MACROECONOMIC", sectors=[], regions=["US"],
                     answer=dict(event_type="MACROECONOMIC", event_subtype="monetary_policy", event_confidence=0.88, sentiment=-0.2,
                                 regions=["US"], affected_asset_classes=["BOND", "EQUITY"],
                                 severity_indicators=["policy_rate_path", "inflation_persistence"], uncertainty=0.25,
                                 entities=[dict(surface="Federal Reserve", kind="INSTITUTION", role="subject")],
                                 evidence=[dict(quote="interest rates may remain elevated", supports="event_type")])),
    "geopolitical": dict(text=GEOPOLITICAL, event="GEOPOLITICAL", sectors=["Energy"], regions=[],
                         answer=dict(event_type="GEOPOLITICAL", event_subtype="supply_route_disruption", event_confidence=0.9, sentiment=-0.6,
                                     sectors=["Energy"], affected_asset_classes=["COMMODITY", "EQUITY"],
                                     severity_indicators=["geopolitical_tension", "supply_disruption", "commodity_price_spike"],
                                     uncertainty=0.2, entities=[],
                                     evidence=[dict(quote="oil supply routes", supports="event_type"),
                                               dict(quote="crude prices sharply higher", supports="severity")])),
    "earnings": dict(text=EARNINGS, event="EARNINGS_FINANCIAL_PERFORMANCE", sectors=["Technology"], regions=[],
                     answer=dict(event_type="EARNINGS_FINANCIAL_PERFORMANCE", event_subtype="guidance_change", event_confidence=0.9,
                                 sentiment=-0.7, sectors=["Technology"], affected_asset_classes=["EQUITY"], severity_indicators=["guidance_cut"],
                                 uncertainty=0.2, entities=[],
                                 evidence=[dict(quote="cuts its revenue outlook", supports="event_type")])),
    "mna": dict(text=MNA, event="MA_CORPORATE_ACTION", sectors=["Technology"], regions=[],
                answer=dict(event_type="MA_CORPORATE_ACTION", event_subtype="acquisition", event_confidence=0.92, sentiment=0.1,
                            sectors=["Technology"], affected_asset_classes=["EQUITY", "BOND"], severity_indicators=["large_transaction"],
                            uncertainty=0.2, entities=[], evidence=[dict(quote="agrees to acquire a software business", supports="event_type")])),
    "unknown": dict(text=UNKNOWN, event="MA_CORPORATE_ACTION", sectors=[], regions=[],
                    answer=dict(event_type="MA_CORPORATE_ACTION", event_subtype="restructuring_divestiture", event_confidence=0.8, sentiment=-0.5,
                                affected_asset_classes=["EQUITY"], severity_indicators=["restructuring"], uncertainty=0.3,
                                entities=[dict(surface="Quantum Dynamics", kind="COMPANY", role="subject")],
                                evidence=[dict(quote="a major restructuring", supports="event_type")])),
}

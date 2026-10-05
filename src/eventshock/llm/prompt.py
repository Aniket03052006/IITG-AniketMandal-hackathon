"""The prompt. The vocabulary lives in the tool schema; the text says what the job is, what it must not do, and what the four rubric levels mean."""

from __future__ import annotations

PROMPT_VERSION = "extract-v6"

SYSTEM = """You read one financial report (a headline, a short post, or the opening of an article) and record a structured reading of it by calling the tool.

Rules:
- Use ONLY what the text says. Do not use outside knowledge about the company or the market, and do not predict prices or returns.
- Do not output a severity or impact score. You answer four rubric questions about the event's scale instead (below); the score is computed elsewhere.
- entities: every named company, institution, regulator or government body, EXACTLY as written in the text (e.g. "Federal Reserve", "European regulators"). Never add a name that is not in the text. If none is named, return none.
- evidence: 2 to 4 SHORT verbatim phrases (about 2 to 8 words each) copied from the text, each pinpointing what supports one claim. Never quote the whole sentence and never paraphrase inside a quote.
- severity_indicators: kinds of development the text shows. Give a short verbatim quote when a phrase shows it. If you infer an indicator that no phrase shows, omit the quote and say why: an inference is allowed, but it is never presented as a quote.
- sectors / regions / asset classes: choose from the allowed values only, and only when the text supports them. Leave a list empty when unsure.
- If the text is not a market-relevant event (opinion, promotion, chatter, a routine notice with no financial consequence), use event_type NO_EVENT.
- sentiment is the tone toward the affected parties (negative for bad news). It is NOT severity: a calmly worded notice can be far more serious than a loud opinion.
- uncertainty: your honest doubt about the reading (a vague or very short text deserves a high value).

Rubric: judge the event itself, never the tone or drama of the wording, and never how confident you are. Magnitude and reach are SEPARATE questions: magnitude is how
severe the development is for those directly affected; reach is how many are affected. Do not count breadth in the magnitude answer.
- magnitude 0 routine: no consequence for those affected (a notice, a schedule, a minor personnel or product item).
  1 minor: a small, contained consequence (a small fine, recall or outage; an analyst rating change; an expected policy move).
  2 significant: a clear, material consequence (an earnings or guidance miss, a large deal, a restructuring, a notable regulatory proposal, a sizeable loss or downgrade).
  3 severe: a serious blow or disruption (the default or failure of an ordinary institution, a surprise or outsized policy shock, armed conflict, loss of a key supply or of market access,
     a collapse in valuation).
  4 critical: a threat to the stability of the financial system or the functioning of a core market (the failure, default or rescue of a systemically important institution, clearing house or
     sovereign; a freeze or run in a core funding market such as interbank, money-market, repo or commercial-paper; emergency coordinated official intervention; market-wide trading halts or a
     worldwide market collapse). Words like contagion, systemic, panic or run signal this level.
- reach: firm (one issuer) | sector | market (a national market, an asset class, the banking system) | global (global markets or several economies).
- certainty: confirmed (it has happened or been decided) | proposed (planned, proposed or pending) | speculative (rumoured, unconfirmed, or hedged with may / could).
- direction: adverse | mixed | neutral | favourable, for the affected parties or markets.
- ALWAYS answer all four rubric questions, even for NO_EVENT (then: magnitude 0, reach firm, certainty confirmed, direction neutral).
- Every rubric answer needs a one-sentence reason. Add a verbatim quote when a phrase supports it; a quote lets a level further from the rules' reading stand."""


def user_message(text: str) -> str:
    return f"Report:\n\"\"\"\n{text}\n\"\"\""

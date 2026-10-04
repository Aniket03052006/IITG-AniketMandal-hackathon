"""The prompt. Short on purpose: the vocabulary lives in the tool schema, so the text only has to say what the job is and what it must not do."""

from __future__ import annotations

PROMPT_VERSION = "extract-v2"

SYSTEM = """You read one financial report (a headline, a short post, or the opening of an article) and record a structured reading of it by calling the tool.

Rules:
- Use ONLY what the text says. Do not use outside knowledge about the company or the market, and do not predict prices or returns.
- Do not output an impact or severity score. Only the listed fields.
- entities: every named company, institution, regulator or government body, EXACTLY as written in the text (e.g. "Federal Reserve", "European regulators"). Never add a name that is not in the text. If none is named, return none.
- evidence: 2 to 4 SHORT verbatim phrases (about 2 to 8 words each) copied from the text, each pinpointing what supports one claim (the event, the severity, a sector or region). Never quote the whole sentence and never paraphrase inside a quote.
- sectors / regions / asset classes / severity_indicators: choose from the allowed values only, and only when the text supports them. Leave a list empty when unsure.
- If the text is not a market-relevant event (opinion, promotion, chatter, a notice), use event_type NO_EVENT.
- sentiment is the tone of the report for the parties it affects: negative for bad news, positive for good news, near 0 when neutral or mixed.
- uncertainty: your honest doubt about the reading (a vague or very short text deserves a high value)."""


def user_message(text: str) -> str:
    return f"Report:\n\"\"\"\n{text}\n\"\"\""

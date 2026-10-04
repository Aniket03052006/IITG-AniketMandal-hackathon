"""The provider adapter: one ``LLMClient`` protocol, one Anthropic implementation over the standard library.

Network access for the LLM lives here and nowhere else. ``urllib`` keeps the dependency list unchanged and matches ``ingestion/fetch.py``.
Every failure becomes one of four typed errors; the extractor turns each into a labelled fallback to the rule extractor, so a provider outage can
never take the application down.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, Protocol

from .config import LLMConfig


class LLMError(RuntimeError):
    """Base for everything the adapter can raise. ``reason`` is the short, user-facing cause."""

    reason = "the language model could not be used"
    retry_after: float | None = None  # seconds the provider asked us to wait
    permanent: bool = False  # retrying cannot help (a rejected key)


class LLMUnavailable(LLMError):
    reason = "the language-model service is not available (no key, key rejected, or network down)"


class LLMTimeout(LLMError):
    reason = "the language-model call timed out"


class LLMRateLimited(LLMError):
    reason = "the language-model service is rate limiting requests"


class LLMBadOutput(LLMError):
    reason = "the language model returned an answer that does not match the schema"


class LLMRejected(LLMError):
    """The provider refused the request itself (unknown model, bad request, too large): a configuration problem, not a bad answer."""

    reason = "the language-model service rejected the request"
    permanent = True


class LLMClient(Protocol):
    model_id: str

    def extract(self, *, system: str, user: str, tool_name: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        """The tool-call arguments as a dict. Raises ``LLMError`` subclasses only."""


Opener = Callable[..., Any]


class _HttpClient:
    """The shared part of every provider: one POST per attempt, retries with back-off on 429 / 5xx / network errors (never on a malformed
    answer: that is a model problem, not a transient one), and every failure mapped to a typed ``LLMError``. Subclasses build the request and
    read the structured answer out of the response."""

    def __init__(self, api_key: str, cfg: LLMConfig, *, model: str | None = None, opener: Opener | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> None:
        if not api_key:
            raise LLMUnavailable("no API key")
        self._key, self._cfg = api_key, cfg
        self.model_id = model or cfg.model
        self._open = opener or urllib.request.urlopen
        self._sleep, self._clock = sleep, clock

    # -- provider hooks
    def _request(self, system: str, user: str, tool_name: str, tool_schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        raise NotImplementedError

    def _answer(self, payload: Any, tool_name: str) -> dict[str, Any]:
        raise NotImplementedError

    # -- shared
    def extract(self, *, system: str, user: str, tool_name: str, tool_schema: dict[str, Any]) -> dict[str, Any]:
        payload, headers = self._request(system, user, tool_name, tool_schema)
        body = json.dumps(payload).encode("utf-8")
        attempts = self._cfg.max_retries + 1
        started = self._clock()
        last: LLMError = LLMUnavailable("no attempt was made")
        for n in range(attempts):
            try:
                return self._once(body, headers, tool_name)
            except (LLMRateLimited, LLMTimeout, LLMUnavailable) as exc:
                last = exc
                if exc.permanent:
                    raise
                if n + 1 < attempts:
                    delay = (min(exc.retry_after, self._cfg.max_retry_after_seconds) if exc.retry_after
                             else self._cfg.retry_backoff_seconds * (2 ** n))
                    # a person is waiting on this call: stop retrying once another attempt could not finish inside the budget
                    if self._clock() - started + delay + self._cfg.timeout_seconds > self._cfg.max_total_seconds:
                        break
                    self._sleep(delay)
        raise last

    def _once(self, body: bytes, headers: dict[str, str], tool_name: str) -> dict[str, Any]:
        req = urllib.request.Request(self._cfg.api_url, data=body, headers=headers, method="POST")
        try:
            with self._open(req, timeout=self._cfg.timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except TimeoutError as exc:
            raise LLMTimeout(str(exc)) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMTimeout(str(exc.reason)) from exc
            raise LLMUnavailable(f"network error: {exc.reason}") from exc
        except (OSError, ValueError) as exc:
            raise LLMBadOutput(f"unreadable response: {exc}") from exc
        return self._answer(payload, tool_name)

    @staticmethod
    def _detail(exc: urllib.error.HTTPError) -> str:
        """What the provider said, short and free of anything secret (provider error bodies carry a code and a message, never the key)."""
        try:
            body = json.loads(exc.read().decode("utf-8", "replace"))
            err = body.get("error", body) if isinstance(body, dict) else {}
            msg = err.get("message") if isinstance(err, dict) else None
            code = err.get("code") or err.get("type") if isinstance(err, dict) else None
            return f"{code + ': ' if code else ''}{(msg or '')[:160]}".strip(": ")
        except (OSError, ValueError, AttributeError):
            return ""

    @classmethod
    def _http_error(cls, exc: urllib.error.HTTPError) -> LLMError:
        code = exc.code
        detail = cls._detail(exc)
        if code == 429:
            err: LLMError = LLMRateLimited("HTTP 429")
            try:
                err.retry_after = float(exc.headers.get("retry-after", "")) if exc.headers else None
            except ValueError:
                err.retry_after = None
            return err
        if code in (401, 403):
            err = LLMUnavailable(f"HTTP {code}: the key was rejected" + (f" ({detail})" if detail else ""))
            err.permanent = True
            return err
        if code in (408, 409) or code >= 500:  # 529 = overloaded
            return LLMUnavailable(f"HTTP {code}")
        if "tool_use_failed" in detail:  # the model could not produce a valid call: a bad answer, not a bad request
            return LLMBadOutput(f"HTTP {code}: {detail}")
        return LLMRejected(f"HTTP {code}{': ' + detail if detail else ''}")


class AnthropicClient(_HttpClient):
    """Anthropic Messages API with a forced tool call (structured output)."""

    def _request(self, system: str, user: str, tool_name: str, tool_schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        body = {
            "model": self.model_id, "max_tokens": self._cfg.max_output_tokens, "temperature": 0, "system": system,
            "messages": [{"role": "user", "content": user}],
            "tools": [{"name": tool_name, "description": "Record the structured reading of the report.", "input_schema": tool_schema}],
            "tool_choice": {"type": "tool", "name": tool_name}}
        return body, {"content-type": "application/json", "x-api-key": self._key, "anthropic-version": self._cfg.api_version}

    def _answer(self, payload: Any, tool_name: str) -> dict[str, Any]:
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(content, list):
            raise LLMBadOutput("no content in the response")
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == tool_name:
                data = block.get("input")
                if isinstance(data, dict):
                    return data
        raise LLMBadOutput("the response held no tool call")


class GroqClient(_HttpClient):
    """Groq's OpenAI-compatible chat-completions API with a forced function call (structured output). Works for any OpenAI-compatible endpoint."""

    def _request(self, system: str, user: str, tool_name: str, tool_schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
        body = {
            "model": self.model_id, "max_tokens": self._cfg.max_output_tokens, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "tools": [{"type": "function", "function": {"name": tool_name, "description": "Record the structured reading of the report.",
                                                          "parameters": tool_schema}}],
            "tool_choice": {"type": "function", "function": {"name": tool_name}}, **self._cfg.request_extra}
        # a browser-like User-Agent is not needed; an explicit one avoids Cloudflare rejecting urllib's default on some OpenAI-compatible hosts
        return body, {"content-type": "application/json", "authorization": f"Bearer {self._key}", "user-agent": "eventshock/0.1"}

    def _answer(self, payload: Any, tool_name: str) -> dict[str, Any]:
        choices = payload.get("choices") if isinstance(payload, dict) else None
        msg = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        calls = msg.get("tool_calls") if isinstance(msg, dict) else None
        if not isinstance(calls, list):
            raise LLMBadOutput("no tool call in the response")
        for call in calls:
            fn = call.get("function") if isinstance(call, dict) else None
            if isinstance(fn, dict) and fn.get("name") == tool_name:
                raw = fn.get("arguments")
                try:
                    data = json.loads(raw) if isinstance(raw, str) else raw
                except ValueError as exc:
                    raise LLMBadOutput(f"the tool arguments are not JSON: {exc}") from exc
                if isinstance(data, dict):
                    return data
        raise LLMBadOutput("the response held no matching tool call")


CLIENTS: dict[str, type[_HttpClient]] = {"anthropic": AnthropicClient, "groq": GroqClient}

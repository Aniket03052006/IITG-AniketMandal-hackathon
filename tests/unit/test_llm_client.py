"""The Anthropic adapter's HTTP handling, over a scripted opener: structured output, retries with backoff, and typed failures."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from eventshock.llm.client import AnthropicClient, LLMBadOutput, LLMRateLimited, LLMTimeout, LLMUnavailable
from tests.assess_helpers import LLM_CFG

TOOL = {"type": "object", "properties": {}}


class Resp:
    def __init__(self, payload) -> None:
        self._b = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        return None


def http_error(code: int, headers=None) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", headers or {}, io.BytesIO(b"{}"))


class Script:
    """An opener that returns / raises each scripted item in turn and records the requests."""

    def __init__(self, *items) -> None:
        self.items, self.requests = list(items), []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return Resp(item)


def client(script: Script, sleeps: list[float] | None = None) -> AnthropicClient:
    return AnthropicClient("key", LLM_CFG.for_provider("anthropic"), opener=script, sleep=(sleeps.append if sleeps is not None else lambda s: None))


OK = {"content": [{"type": "text", "text": "hi"}, {"type": "tool_use", "name": "record_assessment", "input": {"event_type": "X"}}]}


def call(c: AnthropicClient):
    return c.extract(system="s", user="u", tool_name="record_assessment", tool_schema=TOOL)


def test_a_forced_tool_call_is_sent_and_its_arguments_returned() -> None:
    s = Script(OK)
    assert call(client(s)) == {"event_type": "X"}
    req, timeout = s.requests[0]
    body = json.loads(req.data)
    assert body["tool_choice"] == {"type": "tool", "name": "record_assessment"} and body["temperature"] == 0
    assert req.get_header("X-api-key") == "key" and timeout == LLM_CFG.timeout_seconds
    assert body["messages"][0]["content"] == "u"


def test_rate_limit_is_retried_with_backoff_then_succeeds() -> None:
    sleeps: list[float] = []
    s = Script(http_error(429, {"retry-after": "2"}), http_error(529), OK)
    assert call(client(s, sleeps)) == {"event_type": "X"}
    assert len(s.requests) == 3 and sleeps[0] == 2.0 and sleeps[1] == LLM_CFG.retry_backoff_seconds * 2


def test_persistent_rate_limit_raises_a_typed_error_after_the_retries() -> None:
    s = Script(*[http_error(429)] * (LLM_CFG.max_retries + 1))
    with pytest.raises(LLMRateLimited):
        call(client(s))
    assert len(s.requests) == LLM_CFG.max_retries + 1


def test_a_rejected_key_is_not_retried() -> None:
    s = Script(http_error(401))
    with pytest.raises(LLMUnavailable) as e:
        call(client(s))
    assert len(s.requests) == 1 and e.value.permanent


def test_timeouts_are_typed() -> None:
    s = Script(*[TimeoutError("slow")] * (LLM_CFG.max_retries + 1))
    with pytest.raises(LLMTimeout):
        call(client(s))
    s2 = Script(*[urllib.error.URLError(TimeoutError("slow"))] * (LLM_CFG.max_retries + 1))
    with pytest.raises(LLMTimeout):
        call(client(s2))


def test_network_down_is_unavailable() -> None:
    s = Script(*[urllib.error.URLError("no route")] * (LLM_CFG.max_retries + 1))
    with pytest.raises(LLMUnavailable):
        call(client(s))


@pytest.mark.parametrize("payload", [{"content": []}, {"content": [{"type": "text", "text": "prose only"}]}, {"nope": 1}, ["x"],
                                     {"content": [{"type": "tool_use", "name": "other", "input": {}}]}])
def test_an_answer_without_the_tool_call_is_bad_output_and_not_retried(payload) -> None:
    s = Script(payload)
    with pytest.raises(LLMBadOutput):
        call(client(s))
    assert len(s.requests) == 1


def test_no_key_cannot_build_a_client() -> None:
    with pytest.raises(LLMUnavailable):
        AnthropicClient("", LLM_CFG.for_provider("anthropic"))


# ------------------------------------------------------------------------------------------------------------------------ Groq (OpenAI-compatible)
from eventshock.llm.client import GroqClient, LLMRejected  # noqa: E402

GROQ_OK = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
    {"id": "c1", "type": "function", "function": {"name": "record_assessment", "arguments": json.dumps({"event_type": "X"})}}]}}]}


def groq(script: Script, sleeps: list[float] | None = None) -> GroqClient:
    return GroqClient("gsk_test", LLM_CFG.for_provider("groq"), opener=script, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def err_body(code: int, error: dict) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(json.dumps({"error": error}).encode()))


def test_groq_sends_a_forced_function_call_with_bearer_auth_and_reads_its_arguments() -> None:
    s = Script(GROQ_OK)
    assert call(groq(s)) == {"event_type": "X"}
    req, _ = s.requests[0]
    body = json.loads(req.data)
    assert body["tool_choice"] == {"type": "function", "function": {"name": "record_assessment"}} and body["temperature"] == 0
    assert body["messages"][0] == {"role": "system", "content": "s"} and body["messages"][1] == {"role": "user", "content": "u"}
    assert req.get_header("Authorization") == "Bearer gsk_test" and req.full_url.endswith("/chat/completions")
    assert body["reasoning_effort"] == "low"  # the configured extra request fields for this model family are sent
    other = Script(GROQ_OK)
    call(GroqClient("gsk_test", LLM_CFG.for_provider("groq", "qwen/qwen3.8-27b"), opener=other, sleep=lambda x: None))
    assert "reasoning_effort" not in json.loads(other.requests[0][0].data)  # ...and not for a family that does not accept them


@pytest.mark.parametrize("payload", [{"choices": []}, {"choices": [{"message": {"content": "prose"}}]}, {"nope": 1}, [],
                                     {"choices": [{"message": {"tool_calls": [{"function": {"name": "other", "arguments": "{}"}}]}}]},
                                     {"choices": [{"message": {"tool_calls": [{"function": {"name": "record_assessment", "arguments": "{not json"}}]}}]}])
def test_groq_answers_without_a_usable_call_are_bad_output(payload) -> None:
    s = Script(payload)
    with pytest.raises(LLMBadOutput):
        call(groq(s))
    assert len(s.requests) == 1


def test_a_refused_request_says_what_the_provider_said_and_is_not_retried() -> None:
    s = Script(err_body(404, {"code": "model_not_found", "message": "The model `x` does not exist or you do not have access to it."}))
    with pytest.raises(LLMRejected) as e:
        call(groq(s))
    assert len(s.requests) == 1 and "model_not_found" in str(e.value) and "does not exist" in str(e.value)
    assert "gsk_test" not in str(e.value)


def test_a_failed_tool_generation_is_retried_within_the_budget_and_is_a_bad_answer_if_it_keeps_failing() -> None:
    fail = lambda: err_body(400, {"code": "tool_use_failed", "message": "Failed to call a function."})  # noqa: E731
    s = Script(fail(), GROQ_OK)  # a failed generation often succeeds on the next try
    assert call(groq(s)) == {"event_type": "X"} and len(s.requests) == 2
    s2 = Script(*[fail() for _ in range(LLM_CFG.max_retries + 1)])
    with pytest.raises(LLMBadOutput):
        call(groq(s2))
    assert len(s2.requests) == LLM_CFG.max_retries + 1


def test_groq_rate_limits_and_a_rejected_key_follow_the_shared_rules() -> None:
    sleeps: list[float] = []
    s = Script(http_error(429, {"retry-after": "3"}), GROQ_OK)
    assert call(groq(s, sleeps)) == {"event_type": "X"} and sleeps == [3.0]
    with pytest.raises(LLMUnavailable) as e:
        call(groq(Script(err_body(401, {"code": "invalid_api_key", "message": "Invalid API Key"}))))
    assert e.value.permanent and "invalid_api_key" in str(e.value)


def test_the_provider_is_chosen_by_config_and_unknown_ones_are_refused() -> None:
    from eventshock.config import ConfigError

    assert LLM_CFG.for_provider("anthropic").api_url.startswith("https://api.anthropic.com")
    assert LLM_CFG.for_provider("groq", "openai/gpt-oss-20b").model == "openai/gpt-oss-20b"
    with pytest.raises(ConfigError):
        LLM_CFG.for_provider("nope")


def test_retries_stop_when_another_attempt_could_not_finish_inside_the_total_budget() -> None:
    cfg = LLM_CFG.for_provider("groq").model_copy(update={"max_retries": 5, "timeout_seconds": 10.0, "max_total_seconds": 25.0, "retry_backoff_seconds": 1.0})
    now = [0.0]
    sleeps: list[float] = []

    def tick(s: float) -> None:
        sleeps.append(s)
        now[0] += s

    s = Script(*[http_error(429)] * 6)

    def opener(req, timeout=None):
        now[0] += 6.0  # each attempt "takes" 6 s
        return s(req, timeout)

    c = GroqClient("gsk_test", cfg, opener=opener, sleep=tick, clock=lambda: now[0])
    with pytest.raises(LLMRateLimited):
        call(c)
    assert len(s.requests) < 6 and now[0] <= 25.0 + 6.0  # gave up early instead of burning six attempts


def test_a_daily_quota_is_not_retried_because_waiting_cannot_help() -> None:
    msg = "Rate limit reached for model `x` on tokens per day (TPD): Limit 200000, Used 199000, Requested 3000. Please try again in 5m."
    s = Script(err_body(429, {"code": "rate_limit_exceeded", "message": msg}), GROQ_OK)
    with pytest.raises(LLMRateLimited) as e:
        call(groq(s, []))
    assert len(s.requests) == 1 and e.value.permanent and "daily quota exhausted" in str(e.value)
    # a per-minute limit is still retried
    assert call(groq(Script(http_error(429, {"retry-after": "1"}), GROQ_OK), [])) == {"event_type": "X"}

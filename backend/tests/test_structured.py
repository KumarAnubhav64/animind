import asyncio

import pytest
from pydantic import BaseModel

from app.agents.structured import _is_json_validation_error, structured_call


class _S(BaseModel):
    value: int


class _FakeClient:
    def __init__(self, handler, name):
        self._handler = handler
        self.name = name
        self.calls = 0
        self.seen_messages = []
        self.temperature = 0.6
        self.max_tokens = 1024
        self.model_name = name

    def with_structured_output(self, schema, method="json_schema"):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        self.seen_messages.append(messages)
        return await self._handler(self, messages)


def _json_validation_error() -> Exception:
    return RuntimeError(
        "BadRequestError: Error code: 400 - {'error': {'message': \"Failed to validate "
        "JSON. Please adjust your prompt. See 'failed_generation' for more details.\", "
        "'type': 'invalid_request_error', 'code': 'json_validate_failed', "
        "'failed_generation': ''}}"
    )


def test_json_validation_hint_detection():
    assert _is_json_validation_error("... code 'json_validate_failed' ...".lower())
    assert _is_json_validation_error("Failed to validate JSON".lower())
    assert not _is_json_validation_error("Rate limit reached on tokens per day".lower())


def test_validation_failure_escalates_to_backup_key(monkeypatch):
    async def primary_handler(_self, _messages):
        raise _json_validation_error()

    async def backup_handler(_self, _messages):
        return _S(value=2)

    async def fallback_handler(_self, _messages):
        return _S(value=3)

    primary = _FakeClient(primary_handler, "primary/model")
    monkeypatch.setattr("app.agents.llm._backup_groq", lambda *_a, **_k: _FakeClient(backup_handler, "backup"))
    monkeypatch.setattr("app.agents.llm.fallback_llm", lambda: _FakeClient(fallback_handler, "fallback"))

    result = asyncio.run(structured_call(primary, [("human", "topic")], _S, attempts=3))
    assert result.value == 2
    assert primary.calls == 1


def test_validation_retry_appends_remediation_then_primary_succeeds(monkeypatch):
    async def backup_handler(_self, _messages):
        raise RuntimeError("backup also fails")

    async def fallback_handler(_self, _messages):
        raise RuntimeError("fallback also fails")

    async def primary_handler(self, _messages):
        if self.calls == 1:
            raise _json_validation_error()
        return _S(value=1)

    primary = _FakeClient(primary_handler, "primary/model")
    monkeypatch.setattr("app.agents.llm._backup_groq", lambda *_a, **_k: _FakeClient(backup_handler, "backup"))
    monkeypatch.setattr("app.agents.llm.fallback_llm", lambda: _FakeClient(fallback_handler, "fallback"))

    result = asyncio.run(structured_call(primary, [("system", "x"), ("human", "topic")], _S, attempts=3))
    assert result.value == 1
    # The second (successful) primary attempt carried the remediation nudge.
    assert len(primary.seen_messages) == 2
    assert "REMINDER" in primary.seen_messages[1][-1][1]


def test_fallback_model_succeeds_when_backup_and_primary_fail(monkeypatch):
    async def primary_handler(_self, _messages):
        raise _json_validation_error()

    async def backup_handler(_self, _messages):
        raise RuntimeError("backup key failed")

    async def fallback_handler(_self, _messages):
        return _S(value=9)

    primary = _FakeClient(primary_handler, "primary/model")
    monkeypatch.setattr("app.agents.llm._backup_groq", lambda *_a, **_k: _FakeClient(backup_handler, "backup"))
    monkeypatch.setattr("app.agents.llm.fallback_llm", lambda: _FakeClient(fallback_handler, "fallback"))

    result = asyncio.run(structured_call(primary, [("human", "topic")], _S, attempts=3))
    assert result.value == 9


def test_all_paths_fail_raises_after_primary_exhausts_attempts(monkeypatch):
    async def primary_handler(_self, _messages):
        raise _json_validation_error()

    async def backup_handler(_self, _messages):
        raise RuntimeError("backup key failed")

    async def fallback_handler(_self, _messages):
        raise RuntimeError("fallback model failed")

    primary = _FakeClient(primary_handler, "primary/model")
    monkeypatch.setattr("app.agents.llm._backup_groq", lambda *_a, **_k: _FakeClient(backup_handler, "backup"))
    monkeypatch.setattr("app.agents.llm.fallback_llm", lambda: _FakeClient(fallback_handler, "fallback"))

    with pytest.raises(RuntimeError, match="json_validate_failed"):
        asyncio.run(structured_call(primary, [("human", "topic")], _S, attempts=3))
    # Every primary attempt was made (remediation after the first); escalation
    # ran once for backup + fallback and did not short-circuit remaining retries.
    assert primary.calls == 3


def test_tpd_still_escalates_to_backup_key(monkeypatch):
    async def primary_handler(_self, _messages):
        raise RuntimeError("Rate limit reached on tokens per day (TPD)")

    async def backup_handler(_self, _messages):
        return _S(value=7)

    primary = _FakeClient(primary_handler, "primary/model")
    monkeypatch.setattr("app.agents.llm._backup_groq", lambda *_a, **_k: _FakeClient(backup_handler, "backup"))
    monkeypatch.setattr("app.agents.llm.fallback_llm", lambda: _FakeClient(lambda _s, _m: _S(value=8), "fallback"))

    result = asyncio.run(structured_call(primary, [("human", "topic")], _S, attempts=3))
    assert result.value == 7

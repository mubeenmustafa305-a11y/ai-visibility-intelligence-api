"""Unit tests for LLM JSON parse / repair / retry helpers."""

from __future__ import annotations

from app.utils.json_parser import (
    parse_and_validate_llm_json,
    parse_json_text,
    parse_llm_json_with_retry,
)


def test_parses_plain_json_object() -> None:
    result = parse_json_text('{"queries": ["a", "b"]}')
    assert result.ok is True
    assert result.data == {"queries": ["a", "b"]}


def test_parses_fenced_json() -> None:
    text = """Here you go:
```json
{"queries": ["best seo tool"]}
```
"""
    result = parse_json_text(text)
    assert result.ok is True
    assert result.data["queries"] == ["best seo tool"]


def test_repairs_trailing_comma() -> None:
    result = parse_json_text('{"queries": ["a",],}')
    assert result.ok is True
    assert result.repaired is True
    assert result.data == {"queries": ["a"]}


def test_malformed_json_does_not_raise() -> None:
    result = parse_json_text("not json at all {{{")
    assert result.ok is False
    assert result.data is None
    assert result.error is not None


def test_validation_requires_keys() -> None:
    result = parse_and_validate_llm_json(
        '{"queries": []}',
        expect_type=dict,
        required_keys=("queries", "meta"),
        fallback={"queries": []},
    )
    assert result.ok is False
    assert result.data == {"queries": []}
    assert result.details.get("missing_keys") == ["meta"]


def test_retry_fetch_on_malformed_json() -> None:
    calls = {"count": 0}

    def retry_fetch(error: str) -> str:
        calls["count"] += 1
        assert "Malformed" in error or "JSON" in error
        return '{"queries": ["recovered"]}'

    result = parse_llm_json_with_retry(
        "totally broken",
        retry_fetch=retry_fetch,
        max_retries=1,
        expect_type=dict,
        required_keys=("queries",),
    )
    assert result.ok is True
    assert result.retried is True
    assert calls["count"] == 1
    assert result.data == {"queries": ["recovered"]}


def test_retry_exhausted_returns_fallback() -> None:
    result = parse_llm_json_with_retry(
        "still broken",
        retry_fetch=lambda _error: "also broken",
        max_retries=1,
        fallback=[],
        expect_type=list,
    )
    assert result.ok is False
    assert result.retried is True
    assert result.data == []


def test_max_retries_clamped_to_three() -> None:
    calls = {"count": 0}

    def retry_fetch(_error: str) -> str:
        calls["count"] += 1
        return "still not json"

    parse_llm_json_with_retry(
        "broken",
        retry_fetch=retry_fetch,
        max_retries=100,
        expect_type=dict,
        required_keys=("queries",),
    )
    assert calls["count"] == 3

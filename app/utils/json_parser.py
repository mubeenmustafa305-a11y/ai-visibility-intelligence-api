"""Safe LLM JSON extraction, repair, validation, and retry helpers."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(
    r"```(?:json)?\s*(.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


@dataclass(frozen=True)
class JsonParseResult:
    """Outcome of parsing and validating an LLM JSON response."""

    ok: bool
    data: Any | None
    error: str | None = None
    repaired: bool = False
    retried: bool = False
    raw_text: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.ok


def extract_json_candidate(text: str) -> str:
    """Pull the most likely JSON substring from an LLM response."""
    stripped = (text or "").strip()
    if not stripped:
        return ""

    fenced = _FENCE_RE.search(stripped)
    if fenced:
        return fenced.group(1).strip()

    if stripped[0] in "[{":
        return stripped

    # Prefer object, then array, by finding the outermost braces/brackets.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end != -1 and end > start:
            return stripped[start : end + 1].strip()

    return stripped


def repair_json_text(text: str) -> str:
    """Apply conservative repairs for common LLM JSON mistakes."""
    candidate = extract_json_candidate(text)
    candidate = candidate.replace("\ufeff", "").strip()
    candidate = _TRAILING_COMMA_RE.sub(r"\1", candidate)
    # Convert simple single-quoted keys/strings only when double quotes are absent.
    if "'" in candidate and '"' not in candidate:
        candidate = candidate.replace("'", '"')
    return candidate


def parse_json_text(text: str) -> JsonParseResult:
    """Parse JSON without raising — attempts a single light repair pass."""
    raw = text or ""
    candidate = extract_json_candidate(raw)
    if not candidate:
        return JsonParseResult(
            ok=False,
            data=None,
            error="Empty LLM response.",
            raw_text=raw,
        )

    try:
        return JsonParseResult(
            ok=True,
            data=json.loads(candidate),
            raw_text=raw,
        )
    except json.JSONDecodeError as first_error:
        repaired = repair_json_text(raw)
        if repaired == candidate:
            return JsonParseResult(
                ok=False,
                data=None,
                error=f"Malformed JSON: {first_error.msg}",
                raw_text=raw,
                details={"position": first_error.pos},
            )
        try:
            return JsonParseResult(
                ok=True,
                data=json.loads(repaired),
                repaired=True,
                raw_text=raw,
            )
        except json.JSONDecodeError as second_error:
            logger.warning("JSON repair failed: %s", second_error.msg)
            return JsonParseResult(
                ok=False,
                data=None,
                error=f"Malformed JSON after repair: {second_error.msg}",
                repaired=True,
                raw_text=raw,
                details={"position": second_error.pos},
            )


def validate_json_schema(
    data: Any,
    *,
    expect_type: type | tuple[type, ...] | None = None,
    required_keys: Sequence[str] | None = None,
) -> JsonParseResult:
    """Validate parsed JSON against a minimal structural schema."""
    if expect_type is not None and not isinstance(data, expect_type):
        expected = (
            ", ".join(t.__name__ for t in expect_type)
            if isinstance(expect_type, tuple)
            else expect_type.__name__
        )
        return JsonParseResult(
            ok=False,
            data=data,
            error=f"Expected JSON type {expected}.",
        )

    if required_keys:
        if not isinstance(data, Mapping):
            return JsonParseResult(
                ok=False,
                data=data,
                error="Expected a JSON object with required keys.",
            )
        missing = [key for key in required_keys if key not in data]
        if missing:
            return JsonParseResult(
                ok=False,
                data=data,
                error="Missing required keys.",
                details={"missing_keys": missing},
            )

    return JsonParseResult(ok=True, data=data)


def parse_and_validate_llm_json(
    text: str,
    *,
    expect_type: type | tuple[type, ...] | None = None,
    required_keys: Sequence[str] | None = None,
    fallback: Any = None,
) -> JsonParseResult:
    """Parse + validate LLM JSON; never raises; may return fallback data."""
    parsed = parse_json_text(text)
    if not parsed.ok:
        return JsonParseResult(
            ok=False,
            data=fallback,
            error=parsed.error,
            repaired=parsed.repaired,
            raw_text=parsed.raw_text,
            details=parsed.details,
        )

    validated = validate_json_schema(
        parsed.data,
        expect_type=expect_type,
        required_keys=required_keys,
    )
    if validated.ok:
        return JsonParseResult(
            ok=True,
            data=validated.data,
            repaired=parsed.repaired,
            raw_text=parsed.raw_text,
        )

    return JsonParseResult(
        ok=False,
        data=fallback,
        error=validated.error,
        repaired=parsed.repaired,
        raw_text=parsed.raw_text,
        details=validated.details,
    )


def parse_llm_json_with_retry(
    text: str,
    *,
    retry_fetch: Callable[[str], str] | None = None,
    max_retries: int = 1,
    expect_type: type | tuple[type, ...] | None = None,
    required_keys: Sequence[str] | None = None,
    fallback: Any = None,
) -> JsonParseResult:
    """Parse/validate JSON; optionally re-fetch from the LLM on failure.

    ``retry_fetch`` receives the previous parse error message and must return
    a new raw LLM content string. Failures never raise to callers.

    ``max_retries`` is clamped to ``[0, 3]`` to prevent runaway retry loops.
    """
    retries_allowed = max(0, min(int(max_retries), 3))
    attempt = parse_and_validate_llm_json(
        text,
        expect_type=expect_type,
        required_keys=required_keys,
        fallback=fallback,
    )
    if attempt.ok or retry_fetch is None or retries_allowed <= 0:
        return attempt

    retries_left = retries_allowed
    last = attempt
    while retries_left > 0 and not last.ok:
        retries_left -= 1
        error_message = last.error or "Invalid JSON"
        try:
            retried_text = retry_fetch(error_message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM JSON retry_fetch failed: %s", exc)
            return JsonParseResult(
                ok=False,
                data=fallback,
                error=f"Retry fetch failed: {exc}",
                repaired=last.repaired,
                retried=True,
                raw_text=last.raw_text,
                details=last.details,
            )

        last = parse_and_validate_llm_json(
            retried_text,
            expect_type=expect_type,
            required_keys=required_keys,
            fallback=fallback,
        )
        last = JsonParseResult(
            ok=last.ok,
            data=last.data,
            error=last.error,
            repaired=last.repaired,
            retried=True,
            raw_text=last.raw_text,
            details=last.details,
        )

    return last

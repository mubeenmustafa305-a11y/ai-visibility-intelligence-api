"""Shared base for LLM-backed agents."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.services.llm_client import LLMClient, LLMError
from app.utils.json_parser import JsonParseResult, parse_llm_json_with_retry

logger = logging.getLogger(__name__)


class BaseAgent:
    """Common LLM JSON completion helper for independently testable agents."""

    name: str = "base_agent"

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_json_retries: int = 1,
        temperature: float = 0.2,
    ) -> None:
        self._llm = llm
        self._max_json_retries = max(0, min(int(max_json_retries), 3))
        self._temperature = temperature

    def _complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        repair_prompt_template: str,
        required_keys: Sequence[str],
        expect_type: type | tuple[type, ...] = dict,
    ) -> tuple[JsonParseResult, int]:
        """Call the LLM and parse/validate JSON with bounded retries.

        Never raises on malformed JSON. Provider failures are converted into a
        failed ``JsonParseResult`` so callers can return typed error results.
        """
        tokens_used = 0

        try:
            first = self._llm.complete(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=self._temperature,
            )
        except LLMError as exc:
            logger.exception("%s LLM call failed: %s", self.name, exc)
            return (
                JsonParseResult(ok=False, data=None, error=str(exc)),
                tokens_used,
            )

        tokens_used += first.tokens_used or 0

        def retry_fetch(error: str) -> str:
            nonlocal tokens_used
            repair_prompt = repair_prompt_template.format(
                error=error,
                original_user_prompt=user_prompt,
            )
            retry_response = self._llm.complete(
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                temperature=self._temperature,
            )
            tokens_used += retry_response.tokens_used or 0
            return retry_response.content

        parsed = parse_llm_json_with_retry(
            first.content,
            retry_fetch=retry_fetch,
            max_retries=self._max_json_retries,
            expect_type=expect_type,
            required_keys=required_keys,
            fallback=None,
        )
        return parsed, tokens_used

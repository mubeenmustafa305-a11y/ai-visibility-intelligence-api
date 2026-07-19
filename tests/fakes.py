"""Shared fake LLM client for agent unit tests."""

from __future__ import annotations

from collections.abc import Callable

from app.services.llm_client import LLMResponse


class FakeLLMClient:
    """Deterministic LLM stub with scripted responses."""

    provider = "fake"
    model = "fake-model"

    def __init__(
        self,
        responses: list[str] | None = None,
        *,
        handler: Callable[[str, str], str] | None = None,
        tokens_per_call: int = 10,
    ) -> None:
        self._responses = list(responses or [])
        self._handler = handler
        self._tokens_per_call = tokens_per_call
        self.calls: list[dict[str, str]] = []

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> LLMResponse:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": str(temperature),
            }
        )
        if self._handler is not None:
            content = self._handler(system_prompt, user_prompt)
        elif self._responses:
            content = self._responses.pop(0)
        else:
            content = "{}"

        return LLMResponse(
            content=content,
            tokens_used=self._tokens_per_call,
            model=self.model,
            provider=self.provider,
        )

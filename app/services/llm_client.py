"""LLM client abstractions for OpenAI and Anthropic providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class LLMError(Exception):
    """Raised when an LLM provider call fails."""


@dataclass(frozen=True)
class LLMResponse:
    """Normalized completion result across providers."""

    content: str
    tokens_used: int | None
    model: str
    provider: str
    raw: Any = None


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic chat completion interface."""

    provider: str
    model: str

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> LLMResponse:
        """Return assistant text for the given prompts."""


class OpenAIClient:
    """OpenAI Chat Completions adapter."""

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIClient.")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise LLMError("openai package is not installed.") from exc

        self.model = model
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> LLMResponse:
        try:
            completion = self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        if not completion.choices:
            raise LLMError("OpenAI returned no completion choices.")

        choice = completion.choices[0].message.content
        content = choice or ""
        tokens_used = None
        usage = getattr(completion, "usage", None)
        if usage is not None:
            total = getattr(usage, "total_tokens", None)
            if isinstance(total, int):
                tokens_used = total

        return LLMResponse(
            content=content,
            tokens_used=tokens_used,
            model=self.model,
            provider=self.provider,
            raw=completion,
        )


class AnthropicClient:
    """Anthropic Messages API adapter."""

    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        timeout_seconds: float = 60.0,
        max_tokens: int = 4096,
    ) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required for AnthropicClient.")
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("anthropic package is not installed.") from exc

        self.model = model
        self._max_tokens = max_tokens
        self._client = Anthropic(api_key=api_key, timeout=timeout_seconds)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> LLMResponse:
        try:
            message = self._client.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"Anthropic request failed: {exc}") from exc

        chunks: list[str] = []
        for block in message.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                chunks.append(text)
        content = "".join(chunks)

        tokens_used = None
        usage = getattr(message, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            tokens_used = int(input_tokens) + int(output_tokens)

        return LLMResponse(
            content=content,
            tokens_used=tokens_used,
            model=self.model,
            provider=self.provider,
            raw=message,
        )


def build_llm_client_from_config(config: Any) -> LLMClient:
    """Build an LLM client from Flask config attributes."""
    provider = str(getattr(config, "LLM_PROVIDER", "openai")).strip().lower()
    model = str(getattr(config, "LLM_MODEL", "gpt-4o"))
    timeout = float(getattr(config, "LLM_TIMEOUT_SECONDS", 60.0))

    if provider == "openai":
        api_key = getattr(config, "OPENAI_API_KEY", None)
        if not api_key:
            raise ValueError("OPENAI_API_KEY must be set when LLM_PROVIDER=openai.")
        return OpenAIClient(api_key=api_key, model=model, timeout_seconds=timeout)

    if provider == "anthropic":
        api_key = getattr(config, "ANTHROPIC_API_KEY", None)
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY must be set when LLM_PROVIDER=anthropic.")
        return AnthropicClient(api_key=api_key, model=model, timeout_seconds=timeout)

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider!r}")

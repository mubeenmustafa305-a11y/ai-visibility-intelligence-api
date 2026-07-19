"""Agent 1 — Query Discovery."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import (
    DISCOVERY_REPAIR_PROMPT_TEMPLATE,
    DISCOVERY_SYSTEM_PROMPT,
    DISCOVERY_USER_PROMPT_TEMPLATE,
)
from app.agents.types import (
    BusinessProfileInput,
    DiscoveredQueryDraft,
    DiscoveryAgentResult,
)
from app.services.llm_client import LLMClient

_MIN_QUERIES = 10
_MAX_QUERIES = 20


class QueryDiscoveryAgent(BaseAgent):
    """Generate 10–20 commercially relevant AI-assistant queries for a profile."""

    name = "query_discovery_agent"

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_json_retries: int = 1,
        temperature: float = 0.3,
        min_queries: int = _MIN_QUERIES,
        max_queries: int = _MAX_QUERIES,
    ) -> None:
        super().__init__(llm, max_json_retries=max_json_retries, temperature=temperature)
        if min_queries < 1 or max_queries < min_queries:
            raise ValueError("Invalid query count bounds.")
        self._min_queries = min_queries
        self._max_queries = max_queries

    def discover(self, profile: BusinessProfileInput) -> DiscoveryAgentResult:
        """Run discovery for a business profile. Never persists data."""
        user_prompt = DISCOVERY_USER_PROMPT_TEMPLATE.format(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            description=profile.description,
            competitors=", ".join(profile.competitors) or "(none)",
        )

        parsed, tokens = self._complete_json(
            system_prompt=DISCOVERY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            repair_prompt_template=DISCOVERY_REPAIR_PROMPT_TEMPLATE,
            required_keys=("queries",),
            expect_type=dict,
        )

        if not parsed.ok or not isinstance(parsed.data, dict):
            return DiscoveryAgentResult(
                queries=(),
                tokens_used=tokens,
                error=parsed.error or "Failed to parse discovery response.",
            )

        drafts, validation_error = self._validate_queries(parsed.data.get("queries"))
        if validation_error:
            return DiscoveryAgentResult(
                queries=tuple(drafts),
                tokens_used=tokens,
                error=validation_error,
            )

        return DiscoveryAgentResult(queries=tuple(drafts), tokens_used=tokens, error=None)

    def _validate_queries(
        self,
        raw_queries: Any,
    ) -> tuple[list[DiscoveredQueryDraft], str | None]:
        if not isinstance(raw_queries, list):
            return [], "queries must be a JSON array."

        drafts: list[DiscoveredQueryDraft] = []
        seen: set[str] = set()

        for item in raw_queries:
            if not isinstance(item, dict):
                continue

            query_text = item.get("query_text")
            if not isinstance(query_text, str) or not query_text.strip():
                continue

            normalized = " ".join(query_text.split())
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)

            intent_raw = item.get("commercial_intent", 0.5)
            try:
                intent = float(intent_raw)
            except (TypeError, ValueError):
                intent = 0.5
            intent = max(0.0, min(1.0, intent))

            drafts.append(
                DiscoveredQueryDraft(query_text=normalized, commercial_intent=intent)
            )

        if len(drafts) < self._min_queries:
            return drafts, (
                f"Expected at least {self._min_queries} valid queries, "
                f"got {len(drafts)}."
            )

        if len(drafts) > self._max_queries:
            drafts = drafts[: self._max_queries]

        return drafts, None

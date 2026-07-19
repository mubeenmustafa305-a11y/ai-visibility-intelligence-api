"""Agent 2 — Visibility Scoring."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import (
    SCORING_REPAIR_PROMPT_TEMPLATE,
    SCORING_SYSTEM_PROMPT,
    SCORING_USER_PROMPT_TEMPLATE,
)
from app.agents.types import ScoredQueryResult
from app.services.dataforseo_client import DataForSEOClient
from app.services.llm_client import LLMClient
from app.utils.scoring import calculate_opportunity_score

logger = logging.getLogger(__name__)


class VisibilityScoringAgent(BaseAgent):
    """Score one query using real SEO data + LLM commercial-intent estimate."""

    name = "visibility_scoring_agent"

    def __init__(
        self,
        llm: LLMClient,
        seo_client: DataForSEOClient,
        *,
        max_json_retries: int = 1,
        temperature: float = 0.1,
    ) -> None:
        super().__init__(llm, max_json_retries=max_json_retries, temperature=temperature)
        self._seo = seo_client

    def score(
        self,
        *,
        query_text: str,
        domain: str,
        commercial_intent_hint: float | None = None,
    ) -> ScoredQueryResult:
        """Score a single query. Never persists data. Isolates per-query failures."""
        cleaned_query = " ".join(query_text.split())
        if not cleaned_query:
            return ScoredQueryResult(
                query_text=query_text,
                estimated_search_volume=0,
                competitive_difficulty=0,
                opportunity_score=0.0,
                domain_visible=None,
                visibility_position=None,
                commercial_intent=0.0,
                tokens_used=0,
                error="query_text must be a non-empty string.",
            )

        try:
            metrics_list = self._seo.get_keyword_metrics([cleaned_query])
            metrics = metrics_list[0] if metrics_list else None
            visibility = self._seo.check_domain_visibility(cleaned_query, domain)
        except Exception as exc:  # noqa: BLE001 — isolate per-query SEO failures
            logger.exception("%s SEO lookup failed: %s", self.name, exc)
            return ScoredQueryResult(
                query_text=cleaned_query,
                estimated_search_volume=0,
                competitive_difficulty=0,
                opportunity_score=0.0,
                domain_visible=None,
                visibility_position=None,
                commercial_intent=(
                    commercial_intent_hint if commercial_intent_hint is not None else 0.5
                ),
                tokens_used=0,
                error=f"SEO data lookup failed: {exc}",
            )

        search_volume = metrics.search_volume if metrics else 0
        difficulty = metrics.competitive_difficulty if metrics else 0
        domain_visible = visibility.domain_visible
        position = visibility.visibility_position

        intent, tokens, intent_error = self._estimate_commercial_intent(
            query_text=cleaned_query,
            domain=domain,
            search_volume=search_volume,
            competitive_difficulty=difficulty,
            domain_visible=domain_visible,
            visibility_position=position,
            fallback_intent=commercial_intent_hint,
        )
        if intent_error:
            logger.warning("%s using intent fallback: %s", self.name, intent_error)

        opportunity = calculate_opportunity_score(
            search_volume=search_volume,
            competitive_difficulty=difficulty,
            domain_visible=domain_visible,
            commercial_intent=intent,
        )

        return ScoredQueryResult(
            query_text=cleaned_query,
            estimated_search_volume=search_volume,
            competitive_difficulty=difficulty,
            opportunity_score=opportunity,
            domain_visible=domain_visible,
            visibility_position=position,
            commercial_intent=intent,
            tokens_used=tokens,
            error=None,
        )

    def _estimate_commercial_intent(
        self,
        *,
        query_text: str,
        domain: str,
        search_volume: int,
        competitive_difficulty: int,
        domain_visible: bool | None,
        visibility_position: int | None,
        fallback_intent: float | None,
    ) -> tuple[float, int, str | None]:
        default_intent = (
            max(0.0, min(1.0, float(fallback_intent)))
            if fallback_intent is not None
            else 0.5
        )

        user_prompt = SCORING_USER_PROMPT_TEMPLATE.format(
            query_text=query_text,
            domain=domain,
            search_volume=search_volume,
            competitive_difficulty=competitive_difficulty,
            domain_visible=domain_visible,
            visibility_position=visibility_position,
        )

        parsed, tokens = self._complete_json(
            system_prompt=SCORING_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            repair_prompt_template=SCORING_REPAIR_PROMPT_TEMPLATE,
            required_keys=("commercial_intent",),
            expect_type=dict,
        )

        if not parsed.ok or not isinstance(parsed.data, dict):
            return default_intent, tokens, parsed.error or "Intent parse failed."

        intent = self._parse_intent(parsed.data.get("commercial_intent"), default_intent)
        return intent, tokens, None

    @staticmethod
    def _parse_intent(raw: Any, default: float) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return default
        return max(0.0, min(1.0, value))

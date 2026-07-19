"""Agent 3 — Content Recommendations."""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import BaseAgent
from app.agents.prompts import (
    RECOMMENDATION_REPAIR_PROMPT_TEMPLATE,
    RECOMMENDATION_SYSTEM_PROMPT,
    RECOMMENDATION_USER_PROMPT_TEMPLATE,
)
from app.agents.types import (
    QueryForRecommendation,
    RecommendationAgentResult,
    RecommendationDraft,
)
from app.services.llm_client import LLMClient

_ALLOWED_CONTENT_TYPES = frozenset(
    {"blog_post", "landing_page", "faq", "comparison_guide", "case_study"}
)
_ALLOWED_PRIORITIES = frozenset({"high", "medium", "low"})
_MIN_RECS = 3
_MAX_RECS = 5


class ContentRecommendationAgent(BaseAgent):
    """Generate 3–5 actionable content recommendations for non-visible queries."""

    name = "content_recommendation_agent"

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_json_retries: int = 1,
        temperature: float = 0.3,
        min_recommendations: int = _MIN_RECS,
        max_recommendations: int = _MAX_RECS,
    ) -> None:
        super().__init__(llm, max_json_retries=max_json_retries, temperature=temperature)
        if min_recommendations < 1 or max_recommendations < min_recommendations:
            raise ValueError("Invalid recommendation count bounds.")
        self._min_recommendations = min_recommendations
        self._max_recommendations = max_recommendations

    def recommend(
        self,
        *,
        name: str,
        domain: str,
        industry: str,
        queries: list[QueryForRecommendation],
    ) -> RecommendationAgentResult:
        """Generate recommendations. Never persists data."""
        if not queries:
            return RecommendationAgentResult(
                recommendations=(),
                tokens_used=0,
                error="At least one non-visible query is required.",
            )

        allowed_refs = {q.query_ref for q in queries}
        queries_payload = [
            {
                "query_ref": q.query_ref,
                "query_text": q.query_text,
                "opportunity_score": q.opportunity_score,
            }
            for q in queries
        ]

        user_prompt = RECOMMENDATION_USER_PROMPT_TEMPLATE.format(
            name=name,
            domain=domain,
            industry=industry,
            queries_json=json.dumps(queries_payload, indent=2),
        )

        parsed, tokens = self._complete_json(
            system_prompt=RECOMMENDATION_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            repair_prompt_template=RECOMMENDATION_REPAIR_PROMPT_TEMPLATE,
            required_keys=("recommendations",),
            expect_type=dict,
        )

        if not parsed.ok or not isinstance(parsed.data, dict):
            return RecommendationAgentResult(
                recommendations=(),
                tokens_used=tokens,
                error=parsed.error or "Failed to parse recommendation response.",
            )

        drafts, validation_error = self._validate_recommendations(
            parsed.data.get("recommendations"),
            allowed_refs=allowed_refs,
        )
        if validation_error:
            return RecommendationAgentResult(
                recommendations=tuple(drafts),
                tokens_used=tokens,
                error=validation_error,
            )

        return RecommendationAgentResult(
            recommendations=tuple(drafts),
            tokens_used=tokens,
            error=None,
        )

    def _validate_recommendations(
        self,
        raw_recs: Any,
        *,
        allowed_refs: set[str],
    ) -> tuple[list[RecommendationDraft], str | None]:
        if not isinstance(raw_recs, list):
            return [], "recommendations must be a JSON array."

        drafts: list[RecommendationDraft] = []
        for item in raw_recs:
            if not isinstance(item, dict):
                continue

            query_ref = item.get("query_ref")
            content_type = item.get("content_type")
            title = item.get("title")
            rationale = item.get("rationale")
            keywords_raw = item.get("target_keywords")
            priority = item.get("priority")

            if not isinstance(query_ref, str) or query_ref not in allowed_refs:
                continue
            if not isinstance(content_type, str) or content_type not in _ALLOWED_CONTENT_TYPES:
                continue
            if not isinstance(title, str) or not title.strip():
                continue
            if not isinstance(rationale, str) or not rationale.strip():
                continue
            if not isinstance(priority, str) or priority not in _ALLOWED_PRIORITIES:
                continue
            if not isinstance(keywords_raw, list):
                continue

            keywords: list[str] = []
            for keyword in keywords_raw:
                if isinstance(keyword, str) and keyword.strip():
                    keywords.append(keyword.strip())
            if not keywords:
                continue

            drafts.append(
                RecommendationDraft(
                    query_ref=query_ref,
                    content_type=content_type,
                    title=title.strip(),
                    rationale=rationale.strip(),
                    target_keywords=tuple(keywords),
                    priority=priority,
                )
            )

            if len(drafts) >= self._max_recommendations:
                break

        if len(drafts) < self._min_recommendations:
            return drafts, (
                f"Expected at least {self._min_recommendations} valid recommendations, "
                f"got {len(drafts)}."
            )

        return drafts, None

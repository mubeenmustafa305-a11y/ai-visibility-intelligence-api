"""Pipeline orchestrator — sequences agents and persistence; no HTTP."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.agents.types import (
    BusinessProfileInput,
    QueryForRecommendation,
)
from app.models import BusinessProfile, ContentRecommendation, DiscoveredQuery, PipelineRun
from app.services.pipeline_service import PersistedQuery, PipelineService

logger = logging.getLogger(__name__)

_TOP_QUERIES_FOR_RESPONSE = 3
_TOP_QUERIES_FOR_RECOMMENDATIONS = 5


@dataclass(frozen=True)
class PipelineRunResult:
    """API-ready outcome of a synchronous pipeline execution."""

    run: PipelineRun
    top_opportunity_queries: tuple[DiscoveredQuery, ...]
    recommendations: tuple[ContentRecommendation, ...]
    profile: BusinessProfile


class PipelineOrchestrator:
    """Coordinates Agent 1 → 2 → 3 with persistence and partial-failure isolation."""

    def __init__(
        self,
        *,
        discovery_agent: QueryDiscoveryAgent,
        scoring_agent: VisibilityScoringAgent,
        recommendation_agent: ContentRecommendationAgent,
        pipeline_service: PipelineService,
        top_queries_for_recommendations: int = _TOP_QUERIES_FOR_RECOMMENDATIONS,
    ) -> None:
        self._discovery = discovery_agent
        self._scoring = scoring_agent
        self._recommendation = recommendation_agent
        self._pipeline = pipeline_service
        self._top_for_recs = top_queries_for_recommendations

    def run(self, profile_uuid: str) -> PipelineRunResult | None:
        """Execute the full pipeline for a profile. Returns None if profile missing."""
        profile = self._pipeline.get_profile(profile_uuid)
        if profile is None:
            return None

        run = self._pipeline.create_run(profile_uuid)
        tokens_used = 0
        queries_discovered = 0
        queries_scored = 0
        scored_rows: list[DiscoveredQuery] = []
        recommendation_rows: list[ContentRecommendation] = []

        # --- Agent 1 ---------------------------------------------------------
        discovery = self._discovery.discover(self._to_profile_input(profile))
        tokens_used += discovery.tokens_used

        if not discovery.ok:
            self._pipeline.finalize_run(
                run,
                status="failed",
                queries_discovered=0,
                queries_scored=0,
                tokens_used=tokens_used,
                error_message=discovery.error or "Query discovery failed.",
            )
            return PipelineRunResult(
                run=run,
                top_opportunity_queries=(),
                recommendations=(),
                profile=profile,
            )

        queries_discovered = len(discovery.queries)
        persisted = self._pipeline.persist_discovered_queries(
            profile_uuid=profile.uuid,
            run_uuid=run.uuid,
            drafts=discovery.queries,
        )

        # --- Agent 2 (per query; continue on failure) -------------------------
        scored_rows, queries_scored, tokens_used = self._score_queries(
            persisted=persisted,
            domain=profile.domain,
            tokens_used=tokens_used,
        )

        # --- Agent 3 (only when non-visible opportunities exist) -------------
        recommendation_rows, tokens_used, agent3_error = self._recommend(
            profile=profile,
            scored_rows=scored_rows,
            tokens_used=tokens_used,
        )

        # Soft failures keep status=completed so discovered/scored data remains usable.
        # Non-fatal issues are recorded on error_message (not a hard pipeline failure).
        soft_error = self._build_soft_error_message(
            queries_discovered=queries_discovered,
            queries_scored=queries_scored,
            agent3_error=agent3_error,
        )
        self._pipeline.finalize_run(
            run,
            status="completed",
            queries_discovered=queries_discovered,
            queries_scored=queries_scored,
            tokens_used=tokens_used,
            error_message=soft_error,
        )

        top_queries = self._select_top_queries(scored_rows, limit=_TOP_QUERIES_FOR_RESPONSE)
        return PipelineRunResult(
            run=run,
            top_opportunity_queries=tuple(top_queries),
            recommendations=tuple(recommendation_rows),
            profile=profile,
        )

    def _score_queries(
        self,
        *,
        persisted: list[PersistedQuery],
        domain: str,
        tokens_used: int,
    ) -> tuple[list[DiscoveredQuery], int, int]:
        scored_rows: list[DiscoveredQuery] = []
        queries_scored = 0

        for item in persisted:
            scored = self._scoring.score(
                query_text=item.record.query_text,
                domain=domain,
                commercial_intent_hint=item.commercial_intent_hint,
            )
            tokens_used += scored.tokens_used

            if not scored.ok:
                logger.warning(
                    "Agent 2 failed for query %s: %s",
                    item.record.uuid,
                    scored.error,
                )
                # Leave unscored row unchanged; do not count as scored.
                continue

            self._pipeline.apply_score(item.record, scored)
            scored_rows.append(item.record)
            queries_scored += 1

        return scored_rows, queries_scored, tokens_used

    def _recommend(
        self,
        *,
        profile: BusinessProfile,
        scored_rows: list[DiscoveredQuery],
        tokens_used: int,
    ) -> tuple[list[ContentRecommendation], int, str | None]:
        candidates = [
            row
            for row in scored_rows
            if row.domain_visible is False
        ]
        candidates.sort(key=lambda row: row.opportunity_score, reverse=True)
        candidates = candidates[: self._top_for_recs]

        if not candidates:
            return [], tokens_used, None

        agent_input = [
            QueryForRecommendation(
                query_ref=row.uuid,
                query_text=row.query_text,
                opportunity_score=row.opportunity_score,
            )
            for row in candidates
        ]
        result = self._recommendation.recommend(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            queries=agent_input,
        )
        tokens_used += result.tokens_used

        if not result.ok:
            logger.warning("Agent 3 failed: %s", result.error)
            return [], tokens_used, result.error

        records = self._pipeline.persist_recommendations(
            profile_uuid=profile.uuid,
            drafts=result.recommendations,
        )
        return records, tokens_used, None

    @staticmethod
    def _build_soft_error_message(
        *,
        queries_discovered: int,
        queries_scored: int,
        agent3_error: str | None,
    ) -> str | None:
        """Compose non-fatal notes for a completed run. Successful runs return None."""
        parts: list[str] = []
        if queries_discovered > 0 and queries_scored == 0:
            parts.append(
                "All visibility scoring attempts failed; "
                "discovered queries were left unscored."
            )
        if agent3_error:
            parts.append(f"Content recommendation agent failed: {agent3_error}")
        return " ".join(parts) if parts else None

    @staticmethod
    def _select_top_queries(
        scored_rows: list[DiscoveredQuery],
        *,
        limit: int,
    ) -> list[DiscoveredQuery]:
        ordered = sorted(
            scored_rows,
            key=lambda row: row.opportunity_score,
            reverse=True,
        )
        return ordered[:limit]

    @staticmethod
    def _to_profile_input(profile: BusinessProfile) -> BusinessProfileInput:
        competitors = profile.competitors or []
        if not isinstance(competitors, list):
            competitors = list(competitors)
        return BusinessProfileInput(
            name=profile.name,
            domain=profile.domain,
            industry=profile.industry,
            description=profile.description,
            competitors=tuple(str(item) for item in competitors),
        )

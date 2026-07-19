"""Persistence helpers for pipeline runs, queries, and recommendations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.agents.types import DiscoveredQueryDraft, RecommendationDraft, ScoredQueryResult
from app.extensions import db
from app.models import (
    BusinessProfile,
    ContentRecommendation,
    DiscoveredQuery,
    PipelineRun,
)
from app.models.base import utcnow
from app.services.profile_service import profile_service


@dataclass(frozen=True)
class PersistedQuery:
    """Query row plus the Agent 1 commercial-intent hint used during scoring."""

    record: DiscoveredQuery
    commercial_intent_hint: float


class PipelineService:
    """Owns pipeline-related database writes/reads. No agent logic."""

    def get_profile(self, profile_uuid: str) -> BusinessProfile | None:
        return profile_service.get_profile(profile_uuid)

    def create_run(self, profile_uuid: str) -> PipelineRun:
        run = PipelineRun(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile_uuid,
            status="running",
            queries_discovered=0,
            queries_scored=0,
            tokens_used=0,
            error_message=None,
            started_at=utcnow(),
            completed_at=None,
        )
        db.session.add(run)
        db.session.commit()
        return run

    def persist_discovered_queries(
        self,
        *,
        profile_uuid: str,
        run_uuid: str,
        drafts: tuple[DiscoveredQueryDraft, ...],
    ) -> list[PersistedQuery]:
        persisted: list[PersistedQuery] = []
        for draft in drafts:
            record = DiscoveredQuery(
                uuid=str(uuid.uuid4()),
                profile_uuid=profile_uuid,
                run_uuid=run_uuid,
                query_text=draft.query_text,
                estimated_search_volume=0,
                competitive_difficulty=0,
                opportunity_score=0.0,
                domain_visible=None,
                visibility_position=None,
                discovered_at=utcnow(),
            )
            db.session.add(record)
            persisted.append(
                PersistedQuery(
                    record=record,
                    commercial_intent_hint=draft.commercial_intent,
                )
            )
        db.session.commit()
        return persisted

    def apply_score(self, query: DiscoveredQuery, scored: ScoredQueryResult) -> None:
        query.estimated_search_volume = scored.estimated_search_volume
        query.competitive_difficulty = scored.competitive_difficulty
        query.opportunity_score = scored.opportunity_score
        query.domain_visible = scored.domain_visible
        query.visibility_position = scored.visibility_position
        db.session.add(query)
        db.session.commit()

    def persist_recommendations(
        self,
        *,
        profile_uuid: str,
        drafts: tuple[RecommendationDraft, ...],
    ) -> list[ContentRecommendation]:
        records: list[ContentRecommendation] = []
        for draft in drafts:
            record = ContentRecommendation(
                uuid=str(uuid.uuid4()),
                profile_uuid=profile_uuid,
                query_uuid=draft.query_ref,
                content_type=draft.content_type,
                title=draft.title,
                rationale=draft.rationale,
                target_keywords=list(draft.target_keywords),
                priority=draft.priority,
                created_at=utcnow(),
            )
            db.session.add(record)
            records.append(record)
        db.session.commit()
        return records

    def finalize_run(
        self,
        run: PipelineRun,
        *,
        status: str,
        queries_discovered: int,
        queries_scored: int,
        tokens_used: int,
        error_message: str | None,
    ) -> PipelineRun:
        run.status = status
        run.queries_discovered = queries_discovered
        run.queries_scored = queries_scored
        run.tokens_used = tokens_used
        run.error_message = error_message
        run.completed_at = utcnow()
        db.session.add(run)
        db.session.commit()
        return run


pipeline_service = PipelineService()

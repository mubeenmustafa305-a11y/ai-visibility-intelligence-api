"""Query listing, recommendation listing, and recheck services."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select

from app.agents.scoring import VisibilityScoringAgent
from app.extensions import db
from app.models import BusinessProfile, ContentRecommendation, DiscoveredQuery
from app.services.pipeline_service import pipeline_service


class QueryServiceError(Exception):
    """Raised for invalid query-list parameters."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


@dataclass(frozen=True)
class QueryListParams:
    min_score: float | None
    status: str | None
    page: int
    per_page: int

    @classmethod
    def from_request_args(cls, args: Any) -> QueryListParams:
        errors: dict[str, str] = {}

        min_score: float | None = None
        if "min_score" in args and args.get("min_score") not in (None, ""):
            try:
                min_score = float(args.get("min_score"))
            except (TypeError, ValueError):
                errors["min_score"] = "Must be a number between 0 and 1."
            else:
                if min_score < 0.0 or min_score > 1.0:
                    errors["min_score"] = "Must be between 0 and 1."

        status = args.get("status")
        if status in (None, ""):
            status = None
        elif status not in {"visible", "not_visible", "unknown"}:
            errors["status"] = "Must be one of: visible, not_visible, unknown."

        try:
            page = int(args.get("page", 1))
        except (TypeError, ValueError):
            page = 0
            errors["page"] = "Must be a positive integer."
        else:
            if page < 1:
                errors["page"] = "Must be a positive integer."

        try:
            per_page = int(args.get("per_page", 20))
        except (TypeError, ValueError):
            per_page = 0
            errors["per_page"] = "Must be an integer between 1 and 100."
        else:
            if per_page < 1 or per_page > 100:
                errors["per_page"] = "Must be an integer between 1 and 100."

        if errors:
            raise QueryServiceError("Invalid query parameters.", details=errors)

        return cls(min_score=min_score, status=status, page=page, per_page=per_page)


@dataclass(frozen=True)
class QueryListResult:
    items: list[DiscoveredQuery]
    page: int
    per_page: int
    total: int

    @property
    def total_pages(self) -> int:
        if self.total == 0:
            return 0
        return int(math.ceil(self.total / self.per_page))


@dataclass(frozen=True)
class RecheckResult:
    query: DiscoveredQuery
    tokens_used: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class QueryService:
    """Read/filter queries and recommendations; recheck via Agent 2."""

    def list_queries(self, profile_uuid: str, params: QueryListParams) -> QueryListResult:
        filters = [DiscoveredQuery.profile_uuid == profile_uuid]

        if params.min_score is not None:
            filters.append(DiscoveredQuery.opportunity_score >= params.min_score)

        if params.status == "visible":
            filters.append(DiscoveredQuery.domain_visible.is_(True))
        elif params.status == "not_visible":
            filters.append(DiscoveredQuery.domain_visible.is_(False))
        elif params.status == "unknown":
            filters.append(DiscoveredQuery.domain_visible.is_(None))

        count_stmt = select(func.count(DiscoveredQuery.uuid)).where(*filters)
        total = int(db.session.execute(count_stmt).scalar_one())

        offset = (params.page - 1) * params.per_page
        list_stmt: Select[tuple[DiscoveredQuery]] = (
            select(DiscoveredQuery)
            .where(*filters)
            .order_by(
                DiscoveredQuery.opportunity_score.desc(),
                DiscoveredQuery.discovered_at.desc(),
            )
            .offset(offset)
            .limit(params.per_page)
        )
        items = list(db.session.execute(list_stmt).scalars().all())
        return QueryListResult(
            items=items,
            page=params.page,
            per_page=params.per_page,
            total=total,
        )

    def list_recommendations(self, profile_uuid: str) -> list[ContentRecommendation]:
        stmt = (
            select(ContentRecommendation)
            .where(ContentRecommendation.profile_uuid == profile_uuid)
            .order_by(ContentRecommendation.created_at.desc())
        )
        return list(db.session.execute(stmt).scalars().all())

    def get_query(self, query_uuid: str) -> DiscoveredQuery | None:
        return db.session.get(DiscoveredQuery, query_uuid)

    def recheck(
        self,
        query_uuid: str,
        *,
        scoring_agent: VisibilityScoringAgent,
    ) -> RecheckResult | None:
        """Re-run Agent 2 for one query and persist updated scores.

        Returns ``None`` when the query does not exist.
        Commercial intent is re-estimated by Agent 2 (not stored on the model).
        """
        query = self.get_query(query_uuid)
        if query is None:
            return None

        profile = db.session.get(BusinessProfile, query.profile_uuid)
        if profile is None:
            return RecheckResult(
                query=query,
                tokens_used=0,
                error="Parent profile is missing.",
            )

        scored = scoring_agent.score(
            query_text=query.query_text,
            domain=profile.domain,
            commercial_intent_hint=None,
        )
        if not scored.ok:
            return RecheckResult(
                query=query,
                tokens_used=scored.tokens_used,
                error=scored.error or "Visibility scoring failed.",
            )

        pipeline_service.apply_score(query, scored)
        return RecheckResult(query=query, tokens_used=scored.tokens_used, error=None)


query_service = QueryService()

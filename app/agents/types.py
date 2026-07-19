"""Typed inputs and outputs for AI agents."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BusinessProfileInput:
    """Profile data required by discovery (no ORM / Flask types)."""

    name: str
    domain: str
    industry: str
    description: str
    competitors: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DiscoveredQueryDraft:
    """A commercially relevant query produced by Agent 1."""

    query_text: str
    commercial_intent: float


@dataclass(frozen=True)
class DiscoveryAgentResult:
    """Agent 1 output — never raises malformed JSON to callers."""

    queries: tuple[DiscoveredQueryDraft, ...]
    tokens_used: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.queries) > 0


@dataclass(frozen=True)
class ScoredQueryResult:
    """Agent 2 output for a single query."""

    query_text: str
    estimated_search_volume: int
    competitive_difficulty: int
    opportunity_score: float
    domain_visible: bool | None
    visibility_position: int | None
    commercial_intent: float
    tokens_used: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class QueryForRecommendation:
    """A scored, non-visible query passed into Agent 3.

    ``query_ref`` must be the persisted DiscoveredQuery UUID so the
    orchestrator can map recommendations back to database rows.
    """

    query_ref: str
    query_text: str
    opportunity_score: float


@dataclass(frozen=True)
class RecommendationDraft:
    """A content recommendation produced by Agent 3.

    ``query_ref`` mirrors ``QueryForRecommendation.query_ref`` (query UUID).
    """

    query_ref: str
    content_type: str
    title: str
    rationale: str
    target_keywords: tuple[str, ...]
    priority: str


@dataclass(frozen=True)
class RecommendationAgentResult:
    """Agent 3 output — never raises malformed JSON to callers."""

    recommendations: tuple[RecommendationDraft, ...]
    tokens_used: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.recommendations) > 0

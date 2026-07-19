"""Unit tests for PipelineOrchestrator with mocked agents and persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.agents.types import (
    DiscoveredQueryDraft,
    DiscoveryAgentResult,
    RecommendationAgentResult,
    RecommendationDraft,
    ScoredQueryResult,
)
from app.services.pipeline_orchestrator import PipelineOrchestrator
from app.services.pipeline_service import PersistedQuery


@dataclass
class FakeRun:
    uuid: str = "run-1"
    profile_uuid: str = "profile-1"
    status: str = "running"
    queries_discovered: int = 0
    queries_scored: int = 0
    tokens_used: int | None = 0
    error_message: str | None = None
    started_at: object | None = None
    completed_at: object | None = None


@dataclass
class FakeQuery:
    uuid: str
    profile_uuid: str = "profile-1"
    run_uuid: str = "run-1"
    query_text: str = ""
    estimated_search_volume: int = 0
    competitive_difficulty: int = 0
    opportunity_score: float = 0.0
    domain_visible: bool | None = None
    visibility_position: int | None = None


@dataclass
class FakeRecommendation:
    uuid: str
    profile_uuid: str
    query_uuid: str
    content_type: str
    title: str
    rationale: str
    target_keywords: list[str]
    priority: str


@dataclass
class FakePipelineService:
    profile: object
    run: FakeRun = field(default_factory=FakeRun)
    persisted_queries: list[PersistedQuery] = field(default_factory=list)
    recommendations: list[FakeRecommendation] = field(default_factory=list)
    finalized: list[dict] = field(default_factory=list)
    applied_scores: list[tuple[str, ScoredQueryResult]] = field(default_factory=list)

    def get_profile(self, profile_uuid: str):
        if self.profile is None or getattr(self.profile, "uuid", None) != profile_uuid:
            return None
        return self.profile

    def create_run(self, profile_uuid: str) -> FakeRun:
        self.run = FakeRun(uuid="run-1", profile_uuid=profile_uuid, status="running")
        return self.run

    def persist_discovered_queries(self, *, profile_uuid, run_uuid, drafts):
        self.persisted_queries = []
        for index, draft in enumerate(drafts):
            record = FakeQuery(
                uuid=f"q-{index}",
                profile_uuid=profile_uuid,
                run_uuid=run_uuid,
                query_text=draft.query_text,
            )
            self.persisted_queries.append(
                PersistedQuery(record=record, commercial_intent_hint=draft.commercial_intent)
            )
        return self.persisted_queries

    def apply_score(self, query, scored: ScoredQueryResult) -> None:
        query.estimated_search_volume = scored.estimated_search_volume
        query.competitive_difficulty = scored.competitive_difficulty
        query.opportunity_score = scored.opportunity_score
        query.domain_visible = scored.domain_visible
        query.visibility_position = scored.visibility_position
        self.applied_scores.append((query.uuid, scored))

    def persist_recommendations(self, *, profile_uuid, drafts):
        self.recommendations = [
            FakeRecommendation(
                uuid=f"r-{index}",
                profile_uuid=profile_uuid,
                query_uuid=draft.query_ref,
                content_type=draft.content_type,
                title=draft.title,
                rationale=draft.rationale,
                target_keywords=list(draft.target_keywords),
                priority=draft.priority,
            )
            for index, draft in enumerate(drafts)
        ]
        return self.recommendations

    def finalize_run(self, run, **kwargs):
        for key, value in kwargs.items():
            setattr(run, key, value)
        self.finalized.append({"run": run, **kwargs})
        return run


def _profile():
    return SimpleNamespace(
        uuid="profile-1",
        name="Surfer SEO",
        domain="surferseo.com",
        industry="SEO Software",
        description="AI SEO tool",
        competitors=["clearscope.io"],
    )


def _discovery_ok(count: int = 3, tokens: int = 11) -> DiscoveryAgentResult:
    queries = tuple(
        DiscoveredQueryDraft(query_text=f"Query {i}", commercial_intent=0.7)
        for i in range(count)
    )
    return DiscoveryAgentResult(queries=queries, tokens_used=tokens, error=None)


def _score_ok(
    *,
    text: str,
    score: float,
    visible: bool | None = False,
    tokens: int = 5,
) -> ScoredQueryResult:
    return ScoredQueryResult(
        query_text=text,
        estimated_search_volume=1000,
        competitive_difficulty=40,
        opportunity_score=score,
        domain_visible=visible,
        visibility_position=None if visible is False else 2,
        commercial_intent=0.7,
        tokens_used=tokens,
        error=None,
    )


def _recs_ok(query_refs: list[str], tokens: int = 9) -> RecommendationAgentResult:
    drafts = tuple(
        RecommendationDraft(
            query_ref=ref,
            content_type="blog_post",
            title=f"Title for {ref}",
            rationale="Closes visibility gap",
            target_keywords=("seo", "tool"),
            priority="high",
        )
        for ref in query_refs[:3]
    )
    # pad to 3 if needed
    while len(drafts) < 3 and query_refs:
        drafts = drafts + (
            RecommendationDraft(
                query_ref=query_refs[0],
                content_type="faq",
                title="Extra",
                rationale="Extra rationale",
                target_keywords=("seo",),
                priority="medium",
            ),
        )
    return RecommendationAgentResult(recommendations=drafts[:3], tokens_used=tokens)


def _build_orchestrator(
    *,
    discovery,
    scoring,
    recommendation,
    persistence: FakePipelineService,
) -> PipelineOrchestrator:
    return PipelineOrchestrator(
        discovery_agent=discovery,
        scoring_agent=scoring,
        recommendation_agent=recommendation,
        pipeline_service=persistence,  # type: ignore[arg-type]
    )


def test_successful_pipeline() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = _discovery_ok(3, tokens=11)

    scoring = MagicMock()
    scoring.score.side_effect = [
        _score_ok(text="Query 0", score=0.9, visible=False, tokens=5),
        _score_ok(text="Query 1", score=0.5, visible=True, tokens=5),
        _score_ok(text="Query 2", score=0.8, visible=False, tokens=5),
    ]

    recommendation = MagicMock()
    recommendation.recommend.return_value = _recs_ok(["q-0", "q-2"], tokens=9)

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert result.run.status == "completed"
    assert result.run.queries_discovered == 3
    assert result.run.queries_scored == 3
    assert result.run.tokens_used == 11 + 5 + 5 + 5 + 9
    assert result.run.error_message is None
    assert [q.uuid for q in result.top_opportunity_queries] == ["q-0", "q-2", "q-1"]
    assert len(result.recommendations) == 3
    assert persistence.finalized[-1]["status"] == "completed"
    recommendation.recommend.assert_called_once()


def test_agent1_failure_fails_pipeline() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = DiscoveryAgentResult(
        queries=(),
        tokens_used=7,
        error="discovery exploded",
    )
    scoring = MagicMock()
    recommendation = MagicMock()

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert result.run.status == "failed"
    assert result.run.tokens_used == 7
    assert result.run.error_message == "discovery exploded"
    scoring.score.assert_not_called()
    recommendation.recommend.assert_not_called()
    assert persistence.persisted_queries == []


def test_single_agent2_failure_continues() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = _discovery_ok(3, tokens=10)

    scoring = MagicMock()
    scoring.score.side_effect = [
        _score_ok(text="Query 0", score=0.9, visible=False, tokens=4),
        ScoredQueryResult(
            query_text="Query 1",
            estimated_search_volume=0,
            competitive_difficulty=0,
            opportunity_score=0.0,
            domain_visible=None,
            visibility_position=None,
            commercial_intent=0.5,
            tokens_used=2,
            error="SEO down",
        ),
        _score_ok(text="Query 2", score=0.7, visible=False, tokens=4),
    ]
    recommendation = MagicMock()
    recommendation.recommend.return_value = _recs_ok(["q-0", "q-2"], tokens=6)

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert result.run.status == "completed"
    assert result.run.queries_discovered == 3
    assert result.run.queries_scored == 2
    assert result.run.tokens_used == 10 + 4 + 2 + 4 + 6
    assert len(persistence.applied_scores) == 2


def test_multiple_agent2_failures_still_completes() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = _discovery_ok(2, tokens=3)

    failed = ScoredQueryResult(
        query_text="x",
        estimated_search_volume=0,
        competitive_difficulty=0,
        opportunity_score=0.0,
        domain_visible=None,
        visibility_position=None,
        commercial_intent=0.5,
        tokens_used=1,
        error="fail",
    )
    scoring = MagicMock()
    scoring.score.side_effect = [failed, failed]
    recommendation = MagicMock()

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert result.run.status == "completed"
    assert result.run.queries_discovered == 2
    assert result.run.queries_scored == 0
    assert result.top_opportunity_queries == ()
    assert result.run.error_message is not None
    assert "All visibility scoring attempts failed" in result.run.error_message
    recommendation.recommend.assert_not_called()


def test_agent3_failure_still_completes_with_error_message() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = _discovery_ok(2, tokens=5)
    scoring = MagicMock()
    scoring.score.side_effect = [
        _score_ok(text="Query 0", score=0.9, visible=False, tokens=2),
        _score_ok(text="Query 1", score=0.8, visible=False, tokens=2),
    ]
    recommendation = MagicMock()
    recommendation.recommend.return_value = RecommendationAgentResult(
        recommendations=(),
        tokens_used=4,
        error="malformed recommendations JSON",
    )

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert result.run.status == "completed"
    assert result.run.queries_scored == 2
    assert result.recommendations == ()
    assert result.run.error_message is not None
    assert "Content recommendation agent failed" in result.run.error_message
    assert "malformed recommendations JSON" in result.run.error_message
    recommendation.recommend.assert_called_once()


def test_agent3_skipped_when_no_not_visible_queries() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = _discovery_ok(2, tokens=5)
    scoring = MagicMock()
    scoring.score.side_effect = [
        _score_ok(text="Query 0", score=0.9, visible=True, tokens=2),
        _score_ok(text="Query 1", score=0.8, visible=None, tokens=2),
    ]
    recommendation = MagicMock()

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert result.run.status == "completed"
    assert result.recommendations == ()
    assert result.run.error_message is None
    recommendation.recommend.assert_not_called()


def test_token_aggregation() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = _discovery_ok(1, tokens=100)
    scoring = MagicMock()
    scoring.score.return_value = _score_ok(
        text="Query 0", score=0.9, visible=False, tokens=20
    )
    recommendation = MagicMock()
    recommendation.recommend.return_value = _recs_ok(["q-0"], tokens=30)

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert result.run.tokens_used == 150


def test_missing_profile_returns_none() -> None:
    persistence = FakePipelineService(profile=None)
    orch = _build_orchestrator(
        discovery=MagicMock(),
        scoring=MagicMock(),
        recommendation=MagicMock(),
        persistence=persistence,
    )
    assert orch.run("missing") is None


def test_status_transitions_running_then_completed() -> None:
    persistence = FakePipelineService(profile=_profile())
    discovery = MagicMock()
    discovery.discover.return_value = _discovery_ok(1, tokens=1)
    scoring = MagicMock()
    scoring.score.return_value = _score_ok(
        text="Query 0", score=0.4, visible=True, tokens=1
    )
    recommendation = MagicMock()

    orch = _build_orchestrator(
        discovery=discovery,
        scoring=scoring,
        recommendation=recommendation,
        persistence=persistence,
    )
    result = orch.run("profile-1")
    assert result is not None
    assert persistence.run.status == "completed"
    assert len(persistence.finalized) == 1
    assert persistence.finalized[0]["status"] == "completed"

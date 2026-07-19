"""HTTP integration tests for profile create, get, and pipeline run."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app import create_app
from app.agents.types import (
    DiscoveredQueryDraft,
    DiscoveryAgentResult,
    RecommendationAgentResult,
    RecommendationDraft,
    ScoredQueryResult,
)
from app.extensions import db
from app.models import BusinessProfile, ContentRecommendation, DiscoveredQuery, PipelineRun
from app.services.pipeline_orchestrator import PipelineOrchestrator
from app.services.pipeline_service import PipelineService


def _valid_profile_payload() -> dict:
    return {
        "name": "Surfer SEO",
        "domain": "surferseo.com",
        "industry": "SEO Software",
        "description": "AI-powered SEO content optimization tool",
        "competitors": ["clearscope.io", "marketmuse.com", "frase.io"],
    }


def _assert_error_envelope(body: dict, *, code: str) -> None:
    assert "error" in body
    assert set(body["error"].keys()) >= {"code", "message", "details"}
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["message"], str)
    assert isinstance(body["error"]["details"], dict)


def test_create_profile_success() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()

    response = client.post("/api/v1/profiles", json=_valid_profile_payload())
    assert response.status_code == 201
    body = response.get_json()
    assert set(body.keys()) == {
        "profile_uuid",
        "name",
        "domain",
        "status",
        "created_at",
    }
    assert body["name"] == "Surfer SEO"
    assert body["domain"] == "surferseo.com"
    assert body["status"] == "created"
    assert body["created_at"].endswith("Z")
    uuid.UUID(body["profile_uuid"])

    with app.app_context():
        stored = db.session.get(BusinessProfile, body["profile_uuid"])
        assert stored is not None
        assert stored.industry == "SEO Software"
        assert stored.competitors == ["clearscope.io", "marketmuse.com", "frase.io"]


def test_create_profile_validation_error_envelope() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()

    response = client.post(
        "/api/v1/profiles",
        json={
            "name": "",
            "domain": "not a domain",
            "industry": "SEO",
            "description": "ok",
            "competitors": [],
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    _assert_error_envelope(body, code="validation_error")
    assert "name" in body["error"]["details"] or "domain" in body["error"]["details"]


def test_create_profile_rejects_non_object_body() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()

    response = client.post(
        "/api/v1/profiles",
        data="[]",
        content_type="application/json",
    )
    assert response.status_code == 400
    _assert_error_envelope(response.get_json(), code="validation_error")


def test_get_profile_success_with_summary() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        profile = BusinessProfile(
            uuid=str(uuid.uuid4()),
            name="Frase",
            domain="frase.io",
            industry="SEO Content Tools",
            description="AI content briefs",
            competitors=["surferseo.com"],
            status="created",
        )
        run = PipelineRun(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            status="completed",
            queries_discovered=2,
            queries_scored=2,
            tokens_used=20,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        q1 = DiscoveredQuery(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            run_uuid=run.uuid,
            query_text="best content brief tool",
            estimated_search_volume=1000,
            competitive_difficulty=40,
            opportunity_score=0.8,
            domain_visible=False,
            discovered_at=datetime.now(timezone.utc),
        )
        q2 = DiscoveredQuery(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            run_uuid=run.uuid,
            query_text="frase vs surfer",
            estimated_search_volume=500,
            competitive_difficulty=50,
            opportunity_score=0.6,
            domain_visible=True,
            visibility_position=2,
            discovered_at=datetime.now(timezone.utc),
        )
        db.session.add_all([profile, run, q1, q2])
        db.session.commit()
        profile_uuid = profile.uuid

    response = client.get(f"/api/v1/profiles/{profile_uuid}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["profile_uuid"] == profile_uuid
    assert body["name"] == "Frase"
    assert body["domain"] == "frase.io"
    assert body["industry"] == "SEO Content Tools"
    assert body["description"] == "AI content briefs"
    assert body["competitors"] == ["surferseo.com"]
    assert body["status"] == "created"
    assert "created_at" in body and "updated_at" in body
    assert body["summary"]["total_queries_discovered"] == 2
    assert body["summary"]["avg_opportunity_score"] == 0.7


def test_get_profile_not_found() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()

    response = client.get("/api/v1/profiles/missing-profile-uuid")
    assert response.status_code == 404
    _assert_error_envelope(response.get_json(), code="not_found")


def test_run_pipeline_success_mocked_agents() -> None:
    """Full HTTP /run path with mocked LLM/SEO agents — no real external calls."""
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        create = client.post("/api/v1/profiles", json=_valid_profile_payload())
        profile_uuid = create.get_json()["profile_uuid"]

    discovery = MagicMock()
    discovery.discover.return_value = DiscoveryAgentResult(
        queries=(
            DiscoveredQueryDraft(query_text="best seo tool", commercial_intent=0.9),
            DiscoveredQueryDraft(query_text="surfer vs clearscope", commercial_intent=0.8),
        ),
        tokens_used=11,
        error=None,
    )
    scoring = MagicMock()
    scoring.score.side_effect = [
        ScoredQueryResult(
            query_text="best seo tool",
            estimated_search_volume=1200,
            competitive_difficulty=40,
            opportunity_score=0.85,
            domain_visible=False,
            visibility_position=None,
            commercial_intent=0.9,
            tokens_used=5,
            error=None,
        ),
        ScoredQueryResult(
            query_text="surfer vs clearscope",
            estimated_search_volume=800,
            competitive_difficulty=55,
            opportunity_score=0.55,
            domain_visible=True,
            visibility_position=3,
            commercial_intent=0.8,
            tokens_used=5,
            error=None,
        ),
    ]
    recommendation = MagicMock()

    def _recommend(**kwargs):
        refs = [q.query_ref for q in kwargs["queries"]]
        return RecommendationAgentResult(
            recommendations=(
                RecommendationDraft(
                    query_ref=refs[0],
                    content_type="blog_post",
                    title="Best SEO Tool Guide",
                    rationale="Closes the visibility gap",
                    target_keywords=("seo tool", "content optimization"),
                    priority="high",
                ),
                RecommendationDraft(
                    query_ref=refs[0],
                    content_type="landing_page",
                    title="SEO Comparison Landing Page",
                    rationale="Targets commercial comparison demand",
                    target_keywords=("surfer vs clearscope",),
                    priority="medium",
                ),
                RecommendationDraft(
                    query_ref=refs[0],
                    content_type="faq",
                    title="SEO Tool FAQ",
                    rationale="Captures informational follow-ups",
                    target_keywords=("seo faq",),
                    priority="low",
                ),
            ),
            tokens_used=9,
            error=None,
        )

    recommendation.recommend.side_effect = _recommend

    def _factory():
        return PipelineOrchestrator(
            discovery_agent=discovery,
            scoring_agent=scoring,
            recommendation_agent=recommendation,
            pipeline_service=PipelineService(),
        )

    app.config["PIPELINE_ORCHESTRATOR_FACTORY"] = _factory

    response = client.post(f"/api/v1/profiles/{profile_uuid}/run")
    assert response.status_code == 200
    body = response.get_json()
    assert set(body.keys()) >= {
        "pipeline_run_uuid",
        "status",
        "queries_discovered",
        "queries_scored",
        "top_opportunity_queries",
        "recommendations",
        "tokens_used",
        "error_message",
    }
    assert body["status"] == "completed"
    assert body["queries_discovered"] == 2
    assert body["queries_scored"] == 2
    assert body["tokens_used"] == 11 + 5 + 5 + 9
    assert body["error_message"] is None
    assert len(body["top_opportunity_queries"]) == 2
    assert body["top_opportunity_queries"][0]["opportunity_score"] >= body[
        "top_opportunity_queries"
    ][1]["opportunity_score"]
    assert len(body["recommendations"]) == 3
    assert body["recommendations"][0]["content_type"] == "blog_post"
    uuid.UUID(body["pipeline_run_uuid"])

    discovery.discover.assert_called_once()
    assert scoring.score.call_count == 2
    recommendation.recommend.assert_called_once()

    with app.app_context():
        assert db.session.query(DiscoveredQuery).count() == 2
        assert db.session.query(ContentRecommendation).count() == 3


def test_run_pipeline_not_found() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()

    app.config["PIPELINE_ORCHESTRATOR_FACTORY"] = lambda: MagicMock(
        run=MagicMock(return_value=None)
    )
    response = client.post("/api/v1/profiles/does-not-exist/run")
    assert response.status_code == 404
    _assert_error_envelope(response.get_json(), code="not_found")


def test_run_pipeline_agent1_failure_returns_failed_status() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        create = client.post("/api/v1/profiles", json=_valid_profile_payload())
        profile_uuid = create.get_json()["profile_uuid"]

    discovery = MagicMock()
    discovery.discover.return_value = DiscoveryAgentResult(
        queries=(),
        tokens_used=3,
        error="LLM returned malformed discovery JSON",
    )

    def _factory():
        return PipelineOrchestrator(
            discovery_agent=discovery,
            scoring_agent=MagicMock(),
            recommendation_agent=MagicMock(),
            pipeline_service=PipelineService(),
        )

    app.config["PIPELINE_ORCHESTRATOR_FACTORY"] = _factory

    response = client.post(f"/api/v1/profiles/{profile_uuid}/run")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "failed"
    assert body["queries_discovered"] == 0
    assert body["queries_scored"] == 0
    assert body["recommendations"] == []
    assert body["top_opportunity_queries"] == []
    assert "malformed" in (body["error_message"] or "").lower()


def test_run_pipeline_agent3_soft_fail_records_error_message() -> None:
    """Agent 3 failure keeps status=completed and records error_message."""
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        create = client.post("/api/v1/profiles", json=_valid_profile_payload())
        profile_uuid = create.get_json()["profile_uuid"]

    discovery = MagicMock()
    discovery.discover.return_value = DiscoveryAgentResult(
        queries=(
            DiscoveredQueryDraft(query_text="best seo tool", commercial_intent=0.9),
        ),
        tokens_used=7,
        error=None,
    )
    scoring = MagicMock()
    scoring.score.return_value = ScoredQueryResult(
        query_text="best seo tool",
        estimated_search_volume=1200,
        competitive_difficulty=40,
        opportunity_score=0.85,
        domain_visible=False,
        visibility_position=None,
        commercial_intent=0.9,
        tokens_used=5,
        error=None,
    )
    recommendation = MagicMock()
    recommendation.recommend.return_value = RecommendationAgentResult(
        recommendations=(),
        tokens_used=4,
        error="invalid recommendations JSON",
    )

    def _factory():
        return PipelineOrchestrator(
            discovery_agent=discovery,
            scoring_agent=scoring,
            recommendation_agent=recommendation,
            pipeline_service=PipelineService(),
        )

    app.config["PIPELINE_ORCHESTRATOR_FACTORY"] = _factory

    response = client.post(f"/api/v1/profiles/{profile_uuid}/run")
    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "completed"
    assert body["queries_scored"] == 1
    assert body["recommendations"] == []
    assert body["error_message"] is not None
    assert "Content recommendation agent failed" in body["error_message"]
    assert "invalid recommendations JSON" in body["error_message"]
    assert len(body["top_opportunity_queries"]) == 1

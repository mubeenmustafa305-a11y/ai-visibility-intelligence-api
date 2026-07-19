"""Tests for Phase 5 query listing, recommendations, and recheck endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app import create_app
from app.agents.types import ScoredQueryResult
from app.extensions import db
from app.models import BusinessProfile, ContentRecommendation, DiscoveredQuery, PipelineRun


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _seed_profile_with_queries(app):
    with app.app_context():
        profile = BusinessProfile(
            uuid=str(uuid.uuid4()),
            name="Surfer SEO",
            domain="surferseo.com",
            industry="SEO Software",
            description="AI SEO tool",
            competitors=["clearscope.io"],
            status="created",
        )
        run = PipelineRun(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            status="completed",
            queries_discovered=3,
            queries_scored=3,
            tokens_used=10,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        q1 = DiscoveredQuery(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            run_uuid=run.uuid,
            query_text="best seo tool",
            estimated_search_volume=1200,
            competitive_difficulty=40,
            opportunity_score=0.9,
            domain_visible=False,
            visibility_position=None,
            discovered_at=_utcnow(),
        )
        q2 = DiscoveredQuery(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            run_uuid=run.uuid,
            query_text="surfer vs clearscope",
            estimated_search_volume=800,
            competitive_difficulty=50,
            opportunity_score=0.6,
            domain_visible=True,
            visibility_position=3,
            discovered_at=_utcnow(),
        )
        q3 = DiscoveredQuery(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            run_uuid=run.uuid,
            query_text="how to write seo content",
            estimated_search_volume=400,
            competitive_difficulty=30,
            opportunity_score=0.4,
            domain_visible=None,
            visibility_position=None,
            discovered_at=_utcnow(),
        )
        rec = ContentRecommendation(
            uuid=str(uuid.uuid4()),
            profile_uuid=profile.uuid,
            query_uuid=q1.uuid,
            content_type="blog_post",
            title="Best SEO Tool Guide",
            rationale="Closes visibility gap",
            target_keywords=["seo tool", "content optimization"],
            priority="high",
            created_at=_utcnow(),
        )
        db.session.add_all([profile, run, q1, q2, q3, rec])
        db.session.commit()
        return {
            "profile_uuid": profile.uuid,
            "q1": q1.uuid,
            "q2": q2.uuid,
            "q3": q3.uuid,
            "rec": rec.uuid,
        }


def test_list_queries_sorted_and_paginated() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        ids = _seed_profile_with_queries(app)

    response = client.get(
        f"/api/v1/profiles/{ids['profile_uuid']}/queries?page=1&per_page=2"
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["pagination"]["total"] == 3
    assert body["pagination"]["total_pages"] == 2
    assert len(body["items"]) == 2
    assert body["items"][0]["opportunity_score"] >= body["items"][1]["opportunity_score"]
    assert set(body["items"][0]) >= {
        "query_uuid",
        "query_text",
        "estimated_search_volume",
        "competitive_difficulty",
        "opportunity_score",
        "domain_visible",
        "visibility_position",
        "discovered_at",
    }


def test_list_queries_min_score_filter() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        ids = _seed_profile_with_queries(app)

    response = client.get(
        f"/api/v1/profiles/{ids['profile_uuid']}/queries?min_score=0.7"
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["pagination"]["total"] == 1
    assert body["items"][0]["query_uuid"] == ids["q1"]


def test_list_queries_status_filters() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        ids = _seed_profile_with_queries(app)

    visible = client.get(
        f"/api/v1/profiles/{ids['profile_uuid']}/queries?status=visible"
    ).get_json()
    assert visible["pagination"]["total"] == 1
    assert visible["items"][0]["query_uuid"] == ids["q2"]

    not_visible = client.get(
        f"/api/v1/profiles/{ids['profile_uuid']}/queries?status=not_visible"
    ).get_json()
    assert not_visible["pagination"]["total"] == 1
    assert not_visible["items"][0]["query_uuid"] == ids["q1"]

    unknown = client.get(
        f"/api/v1/profiles/{ids['profile_uuid']}/queries?status=unknown"
    ).get_json()
    assert unknown["pagination"]["total"] == 1
    assert unknown["items"][0]["query_uuid"] == ids["q3"]


def test_list_queries_invalid_params() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        ids = _seed_profile_with_queries(app)

    response = client.get(
        f"/api/v1/profiles/{ids['profile_uuid']}/queries?status=bad&min_score=2"
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_list_recommendations() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        ids = _seed_profile_with_queries(app)

    response = client.get(f"/api/v1/profiles/{ids['profile_uuid']}/recommendations")
    assert response.status_code == 200
    body = response.get_json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["recommendation_uuid"] == ids["rec"]
    assert item["target_query_uuid"] == ids["q1"]
    assert item["content_type"] == "blog_post"
    assert item["priority"] == "high"
    assert item["target_keywords"] == ["seo tool", "content optimization"]


def test_recheck_success() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        ids = _seed_profile_with_queries(app)

    scoring = MagicMock()
    scoring.score.return_value = ScoredQueryResult(
        query_text="best seo tool",
        estimated_search_volume=1500,
        competitive_difficulty=35,
        opportunity_score=0.95,
        domain_visible=True,
        visibility_position=1,
        commercial_intent=0.8,
        tokens_used=12,
        error=None,
    )
    app.config["SCORING_AGENT_FACTORY"] = lambda: scoring

    response = client.post(f"/api/v1/queries/{ids['q1']}/recheck")
    assert response.status_code == 200
    body = response.get_json()
    assert body["estimated_search_volume"] == 1500
    assert body["opportunity_score"] == 0.95
    assert body["domain_visible"] is True
    assert body["visibility_position"] == 1
    assert body["tokens_used"] == 12

    with app.app_context():
        updated = db.session.get(DiscoveredQuery, ids["q1"])
        assert updated is not None
        assert updated.estimated_search_volume == 1500
        assert updated.opportunity_score == 0.95


def test_recheck_missing_query() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()

    app.config["SCORING_AGENT_FACTORY"] = lambda: MagicMock()
    response = client.post("/api/v1/queries/does-not-exist/recheck")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_recheck_agent2_failure() -> None:
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        db.create_all()
        ids = _seed_profile_with_queries(app)

    scoring = MagicMock()
    scoring.score.return_value = ScoredQueryResult(
        query_text="best seo tool",
        estimated_search_volume=0,
        competitive_difficulty=0,
        opportunity_score=0.0,
        domain_visible=None,
        visibility_position=None,
        commercial_intent=0.5,
        tokens_used=3,
        error="SEO provider unavailable",
    )
    app.config["SCORING_AGENT_FACTORY"] = lambda: scoring

    response = client.post(f"/api/v1/queries/{ids['q1']}/recheck")
    assert response.status_code == 502
    body = response.get_json()
    assert body["error"]["code"] == "scoring_failed"
    assert "unavailable" in body["error"]["message"].lower()

    with app.app_context():
        unchanged = db.session.get(DiscoveredQuery, ids["q1"])
        assert unchanged is not None
        assert unchanged.estimated_search_volume == 1200
        assert unchanged.opportunity_score == 0.9

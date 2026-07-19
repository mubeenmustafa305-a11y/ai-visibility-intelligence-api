"""Unit tests for ContentRecommendationAgent."""

from __future__ import annotations

import json

from app.agents.recommendation import ContentRecommendationAgent
from app.agents.types import QueryForRecommendation
from tests.fakes import FakeLLMClient


def _queries() -> list[QueryForRecommendation]:
    return [
        QueryForRecommendation(
            query_ref="q1",
            query_text="What is the best AI tool for SEO briefs?",
            opportunity_score=0.81,
        ),
        QueryForRecommendation(
            query_ref="q2",
            query_text="Frase vs Surfer SEO",
            opportunity_score=0.77,
        ),
    ]


def _recs_payload(count: int = 3) -> str:
    recs = []
    for i in range(count):
        recs.append(
            {
                "query_ref": "q1" if i % 2 == 0 else "q2",
                "content_type": "blog_post",
                "title": f"Guide {i}",
                "rationale": f"Addresses gap {i}",
                "target_keywords": ["seo tool", "content brief"],
                "priority": "high",
            }
        )
    return json.dumps({"recommendations": recs})


def test_recommendation_success() -> None:
    llm = FakeLLMClient(responses=[_recs_payload(3)])
    agent = ContentRecommendationAgent(llm)
    result = agent.recommend(
        name="Frase",
        domain="frase.io",
        industry="SEO Content Tools",
        queries=_queries(),
    )
    assert result.ok is True
    assert len(result.recommendations) == 3
    assert result.recommendations[0].priority == "high"
    assert result.tokens_used == 10


def test_recommendation_malformed_json_retry() -> None:
    llm = FakeLLMClient(responses=["nope", _recs_payload(4)])
    agent = ContentRecommendationAgent(llm, max_json_retries=1)
    result = agent.recommend(
        name="Frase",
        domain="frase.io",
        industry="SEO",
        queries=_queries(),
    )
    assert result.ok is True
    assert len(result.recommendations) == 4
    assert len(llm.calls) == 2


def test_recommendation_malformed_exhausted() -> None:
    llm = FakeLLMClient(responses=["bad", "bad"])
    agent = ContentRecommendationAgent(llm, max_json_retries=1)
    result = agent.recommend(
        name="Frase",
        domain="frase.io",
        industry="SEO",
        queries=_queries(),
    )
    assert result.ok is False
    assert result.recommendations == ()


def test_recommendation_validation_rejects_bad_fields() -> None:
    payload = {
        "recommendations": [
            {
                "query_ref": "unknown",
                "content_type": "blog_post",
                "title": "Bad ref",
                "rationale": "x",
                "target_keywords": ["a"],
                "priority": "high",
            },
            {
                "query_ref": "q1",
                "content_type": "tweet",
                "title": "Bad type",
                "rationale": "x",
                "target_keywords": ["a"],
                "priority": "high",
            },
            {
                "query_ref": "q1",
                "content_type": "blog_post",
                "title": "Good 1",
                "rationale": "Because gap",
                "target_keywords": ["seo"],
                "priority": "medium",
            },
        ]
    }
    llm = FakeLLMClient(responses=[json.dumps(payload)])
    agent = ContentRecommendationAgent(llm)
    result = agent.recommend(
        name="Frase",
        domain="frase.io",
        industry="SEO",
        queries=_queries(),
    )
    assert result.ok is False
    assert len(result.recommendations) == 1
    assert "at least 3" in (result.error or "").lower()


def test_recommendation_requires_queries() -> None:
    agent = ContentRecommendationAgent(FakeLLMClient())
    result = agent.recommend(
        name="Frase",
        domain="frase.io",
        industry="SEO",
        queries=[],
    )
    assert result.ok is False
    assert "at least one" in (result.error or "").lower()

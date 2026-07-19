"""Unit tests for VisibilityScoringAgent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.agents.scoring import VisibilityScoringAgent
from app.services.dataforseo_client import (
    DataForSEOClient,
    DomainVisibility,
    KeywordMetrics,
)
from app.utils.scoring import calculate_opportunity_score
from tests.fakes import FakeLLMClient


def _seo_mock(
    *,
    volume: int = 1200,
    difficulty: int = 62,
    visible: bool | None = False,
    position: int | None = None,
) -> MagicMock:
    seo = MagicMock(spec=DataForSEOClient)
    seo.get_keyword_metrics.return_value = [
        KeywordMetrics(
            keyword="best seo tool",
            search_volume=volume,
            competitive_difficulty=difficulty,
        )
    ]
    seo.check_domain_visibility.return_value = DomainVisibility(
        query="best seo tool",
        domain="surferseo.com",
        domain_visible=visible,
        visibility_position=position,
    )
    return seo


def test_scoring_success() -> None:
    llm = FakeLLMClient(
        responses=[json.dumps({"commercial_intent": 0.8, "intent_rationale": "comparison"})]
    )
    agent = VisibilityScoringAgent(llm, _seo_mock())
    result = agent.score(query_text="best seo tool", domain="surferseo.com")
    assert result.ok is True
    assert result.estimated_search_volume == 1200
    assert result.competitive_difficulty == 62
    assert result.domain_visible is False
    assert result.commercial_intent == 0.8
    expected = calculate_opportunity_score(
        search_volume=1200,
        competitive_difficulty=62,
        domain_visible=False,
        commercial_intent=0.8,
    )
    assert result.opportunity_score == expected


def test_scoring_malformed_intent_falls_back() -> None:
    llm = FakeLLMClient(responses=["not-json", "still-bad"])
    agent = VisibilityScoringAgent(llm, _seo_mock(), max_json_retries=1)
    result = agent.score(
        query_text="best seo tool",
        domain="surferseo.com",
        commercial_intent_hint=0.6,
    )
    assert result.ok is True
    assert result.commercial_intent == 0.6
    assert result.estimated_search_volume == 1200


def test_scoring_retries_intent_json() -> None:
    llm = FakeLLMClient(
        responses=[
            "broken",
            json.dumps({"commercial_intent": 0.9, "intent_rationale": "ok"}),
        ]
    )
    agent = VisibilityScoringAgent(llm, _seo_mock(), max_json_retries=1)
    result = agent.score(query_text="best seo tool", domain="surferseo.com")
    assert result.ok is True
    assert result.commercial_intent == 0.9
    assert len(llm.calls) == 2


def test_scoring_seo_failure_returns_error_result() -> None:
    seo = MagicMock(spec=DataForSEOClient)
    seo.get_keyword_metrics.side_effect = RuntimeError("down")
    llm = FakeLLMClient(responses=[])
    agent = VisibilityScoringAgent(llm, seo)
    result = agent.score(query_text="best seo tool", domain="surferseo.com")
    assert result.ok is False
    assert result.error is not None
    assert result.domain_visible is None


def test_scoring_empty_query_validation() -> None:
    agent = VisibilityScoringAgent(FakeLLMClient(), _seo_mock())
    result = agent.score(query_text="   ", domain="surferseo.com")
    assert result.ok is False
    assert "non-empty" in (result.error or "")

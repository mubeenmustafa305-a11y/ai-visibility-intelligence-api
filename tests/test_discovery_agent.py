"""Unit tests for QueryDiscoveryAgent."""

from __future__ import annotations

import json

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.types import BusinessProfileInput
from tests.fakes import FakeLLMClient


def _profile() -> BusinessProfileInput:
    return BusinessProfileInput(
        name="Surfer SEO",
        domain="surferseo.com",
        industry="SEO Software",
        description="AI-powered SEO content optimization tool",
        competitors=("clearscope.io", "frase.io"),
    )


def _queries_payload(count: int = 12) -> str:
    queries = [
        {
            "query_text": f"What is the best SEO tool option {i}?",
            "commercial_intent": 0.7,
        }
        for i in range(count)
    ]
    return json.dumps({"queries": queries})


def test_discovery_success() -> None:
    llm = FakeLLMClient(responses=[_queries_payload(12)])
    agent = QueryDiscoveryAgent(llm)
    result = agent.discover(_profile())
    assert result.ok is True
    assert result.error is None
    assert len(result.queries) == 12
    assert result.tokens_used == 10
    assert result.queries[0].commercial_intent == 0.7


def test_discovery_malformed_json_retries_then_succeeds() -> None:
    llm = FakeLLMClient(responses=["NOT JSON", _queries_payload(10)])
    agent = QueryDiscoveryAgent(llm, max_json_retries=1)
    result = agent.discover(_profile())
    assert result.ok is True
    assert len(result.queries) == 10
    assert len(llm.calls) == 2
    assert result.tokens_used == 20


def test_discovery_malformed_json_exhausted() -> None:
    llm = FakeLLMClient(responses=["bad", "still bad"])
    agent = QueryDiscoveryAgent(llm, max_json_retries=1)
    result = agent.discover(_profile())
    assert result.ok is False
    assert result.queries == ()
    assert result.error is not None


def test_discovery_validation_too_few_queries() -> None:
    llm = FakeLLMClient(responses=[_queries_payload(3)])
    agent = QueryDiscoveryAgent(llm)
    result = agent.discover(_profile())
    assert result.ok is False
    assert "at least 10" in (result.error or "").lower()
    assert len(result.queries) == 3


def test_discovery_dedupes_and_clamps_intent() -> None:
    payload = {
        "queries": [
            {"query_text": "Best SEO tool", "commercial_intent": 1.5},
            {"query_text": "best seo tool", "commercial_intent": 0.2},
            *[
                {"query_text": f"Query {i}", "commercial_intent": "oops"}
                for i in range(9)
            ],
        ]
    }
    # 1 unique "Best SEO tool" + 9 = 10
    llm = FakeLLMClient(responses=[json.dumps(payload)])
    agent = QueryDiscoveryAgent(llm)
    result = agent.discover(_profile())
    assert result.ok is True
    assert len(result.queries) == 10
    assert result.queries[0].commercial_intent == 1.0
    assert result.queries[1].commercial_intent == 0.5

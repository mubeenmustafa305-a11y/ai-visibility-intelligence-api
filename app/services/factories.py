"""Factories for wiring LLM/SEO clients and the pipeline orchestrator."""

from __future__ import annotations

from typing import Any

from app.agents.discovery import QueryDiscoveryAgent
from app.agents.recommendation import ContentRecommendationAgent
from app.agents.scoring import VisibilityScoringAgent
from app.services.dataforseo_client import build_dataforseo_client_from_config
from app.services.llm_client import build_llm_client_from_config
from app.services.pipeline_orchestrator import PipelineOrchestrator
from app.services.pipeline_service import PipelineService, pipeline_service


def build_scoring_agent(config: Any) -> VisibilityScoringAgent:
    """Build Agent 2 for standalone recheck operations."""
    llm = build_llm_client_from_config(config)
    seo = build_dataforseo_client_from_config(config)
    max_retries = int(getattr(config, "LLM_MAX_RETRIES", 1))
    return VisibilityScoringAgent(llm, seo, max_json_retries=max_retries)


def build_pipeline_orchestrator(
    config: Any,
    *,
    persistence: PipelineService | None = None,
) -> PipelineOrchestrator:
    """Build a fully wired orchestrator from application config."""
    llm = build_llm_client_from_config(config)
    seo = build_dataforseo_client_from_config(config)
    max_retries = int(getattr(config, "LLM_MAX_RETRIES", 1))

    return PipelineOrchestrator(
        discovery_agent=QueryDiscoveryAgent(llm, max_json_retries=max_retries),
        scoring_agent=VisibilityScoringAgent(
            llm,
            seo,
            max_json_retries=max_retries,
        ),
        recommendation_agent=ContentRecommendationAgent(
            llm,
            max_json_retries=max_retries,
        ),
        pipeline_service=persistence or pipeline_service,
    )

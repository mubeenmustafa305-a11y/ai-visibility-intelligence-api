"""Shared API response serializers."""

from __future__ import annotations

from typing import Any

from app.models import BusinessProfile, ContentRecommendation, DiscoveredQuery
from app.services.pipeline_orchestrator import PipelineRunResult
from app.services.profile_service import ProfileSummary
from app.utils.datetime_format import format_datetime


def serialize_create_profile(profile: BusinessProfile) -> dict[str, Any]:
    return {
        "profile_uuid": profile.uuid,
        "name": profile.name,
        "domain": profile.domain,
        "status": profile.status,
        "created_at": format_datetime(profile.created_at),
    }


def serialize_profile_detail(
    profile: BusinessProfile,
    summary: ProfileSummary,
) -> dict[str, Any]:
    return {
        "profile_uuid": profile.uuid,
        "name": profile.name,
        "domain": profile.domain,
        "industry": profile.industry,
        "description": profile.description,
        "competitors": profile.competitors,
        "status": profile.status,
        "created_at": format_datetime(profile.created_at),
        "updated_at": format_datetime(profile.updated_at),
        "summary": {
            "total_queries_discovered": summary.total_queries_discovered,
            "avg_opportunity_score": summary.avg_opportunity_score,
        },
    }


def serialize_query(query: DiscoveredQuery) -> dict[str, Any]:
    """Full query object for list/recheck responses."""
    return {
        "query_uuid": query.uuid,
        "query_text": query.query_text,
        "estimated_search_volume": query.estimated_search_volume,
        "competitive_difficulty": query.competitive_difficulty,
        "opportunity_score": query.opportunity_score,
        "domain_visible": query.domain_visible,
        "visibility_position": query.visibility_position,
        "discovered_at": format_datetime(query.discovered_at),
    }


def serialize_top_query(query: DiscoveredQuery) -> dict[str, Any]:
    """Compact query object used in pipeline run responses."""
    return {
        "query_uuid": query.uuid,
        "query_text": query.query_text,
        "estimated_search_volume": query.estimated_search_volume,
        "competitive_difficulty": query.competitive_difficulty,
        "opportunity_score": query.opportunity_score,
        "domain_visible": query.domain_visible,
        "visibility_position": query.visibility_position,
    }


def serialize_recommendation(rec: ContentRecommendation) -> dict[str, Any]:
    return {
        "recommendation_uuid": rec.uuid,
        "target_query_uuid": rec.query_uuid,
        "content_type": rec.content_type,
        "title": rec.title,
        "rationale": rec.rationale,
        "target_keywords": rec.target_keywords,
        "priority": rec.priority,
    }


def serialize_pipeline_result(result: PipelineRunResult) -> dict[str, Any]:
    run = result.run
    return {
        "pipeline_run_uuid": run.uuid,
        "status": run.status,
        "queries_discovered": run.queries_discovered,
        "queries_scored": run.queries_scored,
        "top_opportunity_queries": [
            serialize_top_query(query) for query in result.top_opportunity_queries
        ],
        "recommendations": [
            serialize_recommendation(rec) for rec in result.recommendations
        ],
        "tokens_used": run.tokens_used,
        "error_message": run.error_message,
    }

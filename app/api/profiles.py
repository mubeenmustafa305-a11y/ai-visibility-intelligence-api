"""Business profile API endpoints."""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify, request

from app.api.errors import error_response
from app.api.serializers import (
    serialize_create_profile,
    serialize_pipeline_result,
    serialize_profile_detail,
    serialize_query,
    serialize_recommendation,
)
from app.api.validators import PayloadValidationError, validate_create_profile_payload
from app.services.factories import build_pipeline_orchestrator
from app.services.profile_service import profile_service
from app.services.query_service import (
    QueryListParams,
    QueryServiceError,
    query_service,
)

profiles_bp = Blueprint("profiles", __name__)


def _get_orchestrator():
    factory = current_app.config.get("PIPELINE_ORCHESTRATOR_FACTORY")
    if callable(factory):
        return factory()
    return build_pipeline_orchestrator(current_app.config)


@profiles_bp.post("/api/v1/profiles")
def create_profile() -> tuple[Response, int]:
    """Register a new business profile."""
    try:
        data = validate_create_profile_payload(request.get_json(silent=True))
    except PayloadValidationError as exc:
        return error_response(
            code="validation_error",
            message=exc.message,
            status=400,
            details=exc.details,
        )

    profile = profile_service.create_profile(**data)
    return jsonify(serialize_create_profile(profile)), 201


@profiles_bp.get("/api/v1/profiles/<string:profile_uuid>")
def get_profile(profile_uuid: str) -> tuple[Response, int]:
    """Retrieve a profile and its summary statistics."""
    detail = profile_service.get_profile_detail(profile_uuid)
    if detail is None:
        return error_response(
            code="not_found",
            message=f"Profile '{profile_uuid}' was not found.",
            status=404,
        )

    return jsonify(serialize_profile_detail(detail.profile, detail.summary)), 200


@profiles_bp.post("/api/v1/profiles/<string:profile_uuid>/run")
def run_pipeline(profile_uuid: str) -> tuple[Response, int]:
    """Trigger the full 3-agent visibility pipeline for a profile."""
    orchestrator = _get_orchestrator()
    result = orchestrator.run(profile_uuid)
    if result is None:
        return error_response(
            code="not_found",
            message=f"Profile '{profile_uuid}' was not found.",
            status=404,
        )
    return jsonify(serialize_pipeline_result(result)), 200


@profiles_bp.get("/api/v1/profiles/<string:profile_uuid>/queries")
def list_queries(profile_uuid: str) -> tuple[Response, int]:
    """List discovered queries for a profile with filters and pagination."""
    if profile_service.get_profile(profile_uuid) is None:
        return error_response(
            code="not_found",
            message=f"Profile '{profile_uuid}' was not found.",
            status=404,
        )

    try:
        params = QueryListParams.from_request_args(request.args)
    except QueryServiceError as exc:
        return error_response(
            code="validation_error",
            message=exc.message,
            status=400,
            details=exc.details,
        )

    result = query_service.list_queries(profile_uuid, params)
    return jsonify(
        {
            "items": [serialize_query(query) for query in result.items],
            "pagination": {
                "page": result.page,
                "per_page": result.per_page,
                "total": result.total,
                "total_pages": result.total_pages,
            },
        }
    ), 200


@profiles_bp.get("/api/v1/profiles/<string:profile_uuid>/recommendations")
def list_recommendations(profile_uuid: str) -> tuple[Response, int]:
    """List content recommendations for a profile."""
    if profile_service.get_profile(profile_uuid) is None:
        return error_response(
            code="not_found",
            message=f"Profile '{profile_uuid}' was not found.",
            status=404,
        )

    recommendations = query_service.list_recommendations(profile_uuid)
    return jsonify(
        {
            "items": [serialize_recommendation(rec) for rec in recommendations],
        }
    ), 200

"""Query-scoped API endpoints."""

from __future__ import annotations

from flask import Blueprint, Response, current_app, jsonify

from app.api.errors import error_response
from app.api.serializers import serialize_query
from app.services.factories import build_scoring_agent
from app.services.query_service import query_service

queries_bp = Blueprint("queries", __name__)


def _get_scoring_agent():
    factory = current_app.config.get("SCORING_AGENT_FACTORY")
    if callable(factory):
        return factory()
    return build_scoring_agent(current_app.config)


@queries_bp.post("/api/v1/queries/<string:query_uuid>/recheck")
def recheck_query(query_uuid: str) -> tuple[Response, int]:
    """Re-run Agent 2 visibility scoring for a single query."""
    scoring_agent = _get_scoring_agent()
    result = query_service.recheck(query_uuid, scoring_agent=scoring_agent)
    if result is None:
        return error_response(
            code="not_found",
            message=f"Query '{query_uuid}' was not found.",
            status=404,
        )

    if not result.ok:
        return error_response(
            code="scoring_failed",
            message=result.error or "Visibility scoring failed.",
            status=502,
            details={"tokens_used": result.tokens_used},
        )

    body = serialize_query(result.query)
    body["tokens_used"] = result.tokens_used
    return jsonify(body), 200

"""HTTP error helpers and Flask error handlers."""

from __future__ import annotations

from typing import Any

from flask import Flask, Response, jsonify
from werkzeug.exceptions import HTTPException


def error_response(
    code: str,
    message: str,
    status: int,
    details: dict[str, Any] | None = None,
) -> tuple[Response, int]:
    """Build a consistent JSON error envelope."""
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        }
    }
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    """Register global error handlers for consistent JSON responses."""

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException) -> tuple[Response, int]:
        code = (exc.name or "http_error").lower().replace(" ", "_")
        return error_response(
            code=code,
            message=exc.description or str(exc),
            status=exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected_exception(exc: Exception) -> tuple[Response, int]:
        app.logger.exception("Unhandled exception: %s", exc)
        return error_response(
            code="internal_server_error",
            message="An unexpected error occurred.",
            status=500,
        )

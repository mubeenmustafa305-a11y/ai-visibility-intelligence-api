"""Flask application factory for the AI Visibility Intelligence API."""

from __future__ import annotations

from flask import Flask

from app.api.errors import register_error_handlers
from app.api.profiles import profiles_bp
from app.api.queries import queries_bp
from app.config import get_config
from app.extensions import db, migrate


def create_app(config_name: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(get_config(config_name))

    _register_extensions(app)
    register_error_handlers(app)
    _register_blueprints(app)
    _import_models()

    return app


def _register_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)


def _register_blueprints(app: Flask) -> None:
    app.register_blueprint(profiles_bp)
    app.register_blueprint(queries_bp)


def _import_models() -> None:
    """Import models so Flask-Migrate discovers metadata."""
    import app.models  # noqa: F401

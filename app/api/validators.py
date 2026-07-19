"""Request validation helpers for API payloads."""

from __future__ import annotations

from typing import Any

from app.utils.domains import is_valid_domain, normalize_domain


class PayloadValidationError(Exception):
    """Raised when request payload validation fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


_MAX_NAME = 255
_MAX_DOMAIN = 255
_MAX_INDUSTRY = 255
_MAX_DESCRIPTION = 10_000


def _validate_domain_value(value: str, *, field: str, errors: dict[str, str]) -> str | None:
    domain = normalize_domain(value)
    if not is_valid_domain(domain):
        errors[field] = "Must be a valid domain."
        return None
    if len(domain) > _MAX_DOMAIN:
        errors[field] = f"Must be at most {_MAX_DOMAIN} characters."
        return None
    return domain


def validate_create_profile_payload(payload: Any) -> dict[str, Any]:
    """Validate and normalize POST /profiles request body."""
    if not isinstance(payload, dict):
        raise PayloadValidationError(
            "Request body must be a JSON object.",
            details={"body": "Expected a JSON object."},
        )

    errors: dict[str, str] = {}

    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        errors["name"] = "Must be a non-empty string."
    elif len(name.strip()) > _MAX_NAME:
        errors["name"] = f"Must be at most {_MAX_NAME} characters."

    industry = payload.get("industry")
    if not isinstance(industry, str) or not industry.strip():
        errors["industry"] = "Must be a non-empty string."
    elif len(industry.strip()) > _MAX_INDUSTRY:
        errors["industry"] = f"Must be at most {_MAX_INDUSTRY} characters."

    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        errors["description"] = "Must be a non-empty string."
    elif len(description.strip()) > _MAX_DESCRIPTION:
        errors["description"] = f"Must be at most {_MAX_DESCRIPTION} characters."

    domain: str | None = None
    raw_domain = payload.get("domain")
    if not isinstance(raw_domain, str) or not raw_domain.strip():
        errors["domain"] = "Must be a non-empty string."
    else:
        domain = _validate_domain_value(raw_domain, field="domain", errors=errors)

    competitors_raw = payload.get("competitors")
    competitors: list[str] = []
    if not isinstance(competitors_raw, list) or not competitors_raw:
        errors["competitors"] = "Must be a non-empty list of domain strings."
    else:
        seen: set[str] = set()
        for index, item in enumerate(competitors_raw):
            field = f"competitors[{index}]"
            if not isinstance(item, str) or not item.strip():
                errors[field] = "Must be a non-empty string."
                continue
            competitor = _validate_domain_value(item, field=field, errors=errors)
            if competitor is None:
                continue
            if competitor not in seen:
                seen.add(competitor)
                competitors.append(competitor)

        if "competitors" not in errors and not competitors and not any(
            key.startswith("competitors[") for key in errors
        ):
            errors["competitors"] = "Must include at least one valid domain."

    if errors:
        raise PayloadValidationError("Invalid profile payload.", details=errors)

    if domain is None:
        raise PayloadValidationError(
            "Invalid profile payload.",
            details={"domain": "Must be a valid domain."},
        )

    return {
        "name": str(name).strip(),
        "domain": domain,
        "industry": str(industry).strip(),
        "description": str(description).strip(),
        "competitors": competitors,
    }

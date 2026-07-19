"""ISO-8601 datetime serialization helpers."""

from __future__ import annotations

from datetime import datetime


def format_datetime(value: datetime) -> str:
    """Serialize datetimes as UTC ISO-8601 with a trailing Z."""
    iso = value.isoformat()
    if iso.endswith("+00:00"):
        return iso[:-6] + "Z"
    if value.tzinfo is None:
        return f"{iso}Z"
    return iso

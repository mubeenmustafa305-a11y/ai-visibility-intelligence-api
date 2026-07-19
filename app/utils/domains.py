"""Domain string normalization helpers (shared; not API-layer specific)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$"
)


def normalize_domain(value: str) -> str:
    """Normalize a domain or URL to a bare lowercase hostname."""
    raw = value.strip().lower()
    if "://" in raw:
        raw = urlparse(raw).netloc or raw
    raw = raw.split("/")[0].split("?")[0].split("#")[0]
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    if raw.startswith("www."):
        raw = raw[4:]
    if ":" in raw:
        host, _, port = raw.partition(":")
        if port.isdigit():
            raw = host
    return raw.rstrip(".")


def is_valid_domain(value: str) -> bool:
    """Return True when ``value`` is a normalized-looking hostname."""
    return bool(_DOMAIN_RE.match(value))

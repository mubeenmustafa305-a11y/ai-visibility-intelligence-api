"""Opportunity score formula (pure, deterministic)."""

from __future__ import annotations

import math

# Soft cap for log-normalized search volume. Volumes at/above this map to 1.0.
_VOLUME_CAP = 100_000

# Weighting: demand, ease, visibility gap, commercial intent.
_WEIGHT_VOLUME = 0.40
_WEIGHT_DIFFICULTY = 0.30
_WEIGHT_VISIBILITY = 0.20
_WEIGHT_INTENT = 0.10


def calculate_opportunity_score(
    *,
    search_volume: int,
    competitive_difficulty: int,
    domain_visible: bool | None,
    commercial_intent: float = 0.5,
) -> float:
    """Compute an opportunity score in [0.0, 1.0].

    Factors
    -------
    search_volume:
        Higher monthly volume increases opportunity (log-normalized).
    competitive_difficulty:
        0–100. Lower difficulty increases opportunity.
    domain_visible:
        ``False`` = max gap (high opportunity),
        ``True`` = already visible (low gap),
        ``None`` = unknown visibility (neutral gap).
    commercial_intent:
        0.0–1.0. Comparison / transactional queries score higher than
        purely informational ones. Callers supply this (e.g. agent heuristic).

    Formula
    -------
    score =
        0.40 * volume_score +
        0.30 * (1 - difficulty/100) +
        0.20 * visibility_gap +
        0.10 * commercial_intent
    """
    volume_score = _volume_score(search_volume)
    difficulty_score = 1.0 - (_clamp(competitive_difficulty, 0, 100) / 100.0)
    visibility_gap = _visibility_gap(domain_visible)
    intent_score = _clamp(commercial_intent, 0.0, 1.0)

    raw = (
        _WEIGHT_VOLUME * volume_score
        + _WEIGHT_DIFFICULTY * difficulty_score
        + _WEIGHT_VISIBILITY * visibility_gap
        + _WEIGHT_INTENT * intent_score
    )
    return round(_clamp(raw, 0.0, 1.0), 4)


def _volume_score(search_volume: int) -> float:
    volume = max(0, int(search_volume))
    if volume <= 0:
        return 0.0
    return math.log1p(volume) / math.log1p(_VOLUME_CAP)


def _visibility_gap(domain_visible: bool | None) -> float:
    if domain_visible is False:
        return 1.0
    if domain_visible is True:
        return 0.2
    return 0.5


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))

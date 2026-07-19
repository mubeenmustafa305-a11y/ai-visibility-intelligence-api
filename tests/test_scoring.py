"""Unit tests for the opportunity score formula."""

from __future__ import annotations

from app.utils.scoring import calculate_opportunity_score


def test_score_is_bounded() -> None:
    score = calculate_opportunity_score(
        search_volume=10_000,
        competitive_difficulty=40,
        domain_visible=False,
        commercial_intent=0.9,
    )
    assert 0.0 <= score <= 1.0


def test_not_visible_scores_higher_than_visible() -> None:
    shared = {
        "search_volume": 5_000,
        "competitive_difficulty": 50,
        "commercial_intent": 0.7,
    }
    gap = calculate_opportunity_score(domain_visible=False, **shared)
    visible = calculate_opportunity_score(domain_visible=True, **shared)
    assert gap > visible


def test_higher_volume_increases_score() -> None:
    low = calculate_opportunity_score(
        search_volume=100,
        competitive_difficulty=40,
        domain_visible=False,
        commercial_intent=0.5,
    )
    high = calculate_opportunity_score(
        search_volume=50_000,
        competitive_difficulty=40,
        domain_visible=False,
        commercial_intent=0.5,
    )
    assert high > low


def test_lower_difficulty_increases_score() -> None:
    hard = calculate_opportunity_score(
        search_volume=2_000,
        competitive_difficulty=90,
        domain_visible=False,
        commercial_intent=0.5,
    )
    easy = calculate_opportunity_score(
        search_volume=2_000,
        competitive_difficulty=10,
        domain_visible=False,
        commercial_intent=0.5,
    )
    assert easy > hard


def test_unknown_visibility_is_between_gap_and_visible() -> None:
    shared = {
        "search_volume": 3_000,
        "competitive_difficulty": 45,
        "commercial_intent": 0.6,
    }
    gap = calculate_opportunity_score(domain_visible=False, **shared)
    unknown = calculate_opportunity_score(domain_visible=None, **shared)
    visible = calculate_opportunity_score(domain_visible=True, **shared)
    assert gap > unknown > visible


def test_clamps_out_of_range_inputs() -> None:
    score = calculate_opportunity_score(
        search_volume=-10,
        competitive_difficulty=500,
        domain_visible=False,
        commercial_intent=2.0,
    )
    assert 0.0 <= score <= 1.0


def test_formula_matches_documented_weights() -> None:
    """Verify exact arithmetic for a known input set."""
    import math

    search_volume = 1200
    difficulty = 62
    domain_visible = False
    commercial_intent = 0.8

    volume_score = math.log1p(search_volume) / math.log1p(100_000)
    difficulty_score = 1.0 - (difficulty / 100.0)
    visibility_gap = 1.0
    expected = round(
        0.40 * volume_score
        + 0.30 * difficulty_score
        + 0.20 * visibility_gap
        + 0.10 * commercial_intent,
        4,
    )
    actual = calculate_opportunity_score(
        search_volume=search_volume,
        competitive_difficulty=difficulty,
        domain_visible=domain_visible,
        commercial_intent=commercial_intent,
    )
    assert actual == expected

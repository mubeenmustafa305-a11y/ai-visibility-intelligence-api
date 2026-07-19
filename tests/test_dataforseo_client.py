"""Smoke tests for DataForSEO client parsing with mocked HTTP."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.dataforseo_client import DataForSEOClient


def test_get_keyword_metrics_maps_competition_index() -> None:
    session = MagicMock()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "status_code": 20000,
        "tasks": [
            {
                "status_code": 20000,
                "result": [
                    {
                        "keyword": "best seo tool",
                        "search_volume": 1200,
                        "competition_index": 62,
                    }
                ],
            }
        ],
    }
    session.post.return_value = response

    client = DataForSEOClient(
        login="user",
        password="pass",
        session=session,
    )
    metrics = client.get_keyword_metrics(["best seo tool"])
    assert len(metrics) == 1
    assert metrics[0].search_volume == 1200
    assert metrics[0].competitive_difficulty == 62


def test_check_domain_visibility_finds_organic_hit() -> None:
    session = MagicMock()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "status_code": 20000,
        "tasks": [
            {
                "status_code": 20000,
                "result": [
                    {
                        "items": [
                            {
                                "type": "organic",
                                "domain": "www.surferseo.com",
                                "rank_absolute": 3,
                            },
                            {
                                "type": "organic",
                                "domain": "clearscope.io",
                                "rank_absolute": 1,
                            },
                        ]
                    }
                ],
            }
        ],
    }
    session.post.return_value = response

    client = DataForSEOClient(login="user", password="pass", session=session)
    result = client.check_domain_visibility("best seo tool", "surferseo.com")
    assert result.domain_visible is True
    assert result.visibility_position == 3


def test_check_domain_visibility_not_found() -> None:
    session = MagicMock()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {
        "status_code": 20000,
        "tasks": [
            {
                "status_code": 20000,
                "result": [{"items": [{"type": "organic", "domain": "other.com", "rank_absolute": 1}]}],
            }
        ],
    }
    session.post.return_value = response

    client = DataForSEOClient(login="user", password="pass", session=session)
    result = client.check_domain_visibility("best seo tool", "surferseo.com")
    assert result.domain_visible is False
    assert result.visibility_position is None

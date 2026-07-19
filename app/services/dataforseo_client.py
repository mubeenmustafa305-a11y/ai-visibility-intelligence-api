"""DataForSEO HTTP client for real keyword and SERP data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from app.utils.domains import normalize_domain

logger = logging.getLogger(__name__)


class DataForSEOError(Exception):
    """Raised when the DataForSEO API returns an unusable response."""


@dataclass(frozen=True)
class KeywordMetrics:
    """Search demand and competition metrics for a single keyword/query."""

    keyword: str
    search_volume: int
    competitive_difficulty: int  # 0–100


@dataclass(frozen=True)
class DomainVisibility:
    """Whether a domain appears in organic results for a query."""

    query: str
    domain: str
    domain_visible: bool | None
    visibility_position: int | None


class DataForSEOClient:
    """Thin DataForSEO adapter — no scoring or agent business logic."""

    SEARCH_VOLUME_PATH = "/v3/keywords_data/google_ads/search_volume/live"
    SERP_PATH = "/v3/serp/google/organic/live/advanced"

    def __init__(
        self,
        *,
        login: str,
        password: str,
        base_url: str = "https://api.dataforseo.com",
        location_code: int = 2840,
        language_code: str = "en",
        timeout_seconds: float = 60.0,
        session: requests.Session | None = None,
    ) -> None:
        if not login or not password:
            raise ValueError("DataForSEO login and password are required.")

        self._auth = HTTPBasicAuth(login, password)
        self._base_url = base_url.rstrip("/")
        self._location_code = location_code
        self._language_code = language_code
        self._timeout = timeout_seconds
        self._session = session or requests.Session()

    def get_keyword_metrics(self, keywords: list[str]) -> list[KeywordMetrics]:
        """Fetch search volume and competition index for one or more keywords."""
        cleaned = [keyword.strip() for keyword in keywords if keyword and keyword.strip()]
        if not cleaned:
            return []

        payload = [
            {
                "location_code": self._location_code,
                "language_code": self._language_code,
                "keywords": cleaned,
            }
        ]
        response_json = self._post(self.SEARCH_VOLUME_PATH, payload)
        items = self._extract_result_items(response_json)

        by_keyword: dict[str, KeywordMetrics] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            keyword = str(item.get("keyword") or "").strip()
            if not keyword:
                continue

            volume_raw = item.get("search_volume")
            competition_index = item.get("competition_index")
            competition = item.get("competition")

            search_volume = int(volume_raw) if isinstance(volume_raw, (int, float)) else 0
            difficulty = self._to_difficulty(competition_index, competition)
            by_keyword[keyword.lower()] = KeywordMetrics(
                keyword=keyword,
                search_volume=max(search_volume, 0),
                competitive_difficulty=difficulty,
            )

        # Preserve caller order; fill gaps with zeros when API omits a keyword.
        results: list[KeywordMetrics] = []
        for keyword in cleaned:
            results.append(
                by_keyword.get(
                    keyword.lower(),
                    KeywordMetrics(
                        keyword=keyword,
                        search_volume=0,
                        competitive_difficulty=0,
                    ),
                )
            )
        return results

    def check_domain_visibility(self, query: str, domain: str) -> DomainVisibility:
        """Check whether the target domain appears in organic SERP results."""
        normalized_domain = normalize_domain(domain)
        payload = [
            {
                "language_code": self._language_code,
                "location_code": self._location_code,
                "keyword": query,
                "depth": 20,
            }
        ]

        try:
            response_json = self._post(self.SERP_PATH, payload)
            items = self._extract_result_items(response_json)
        except DataForSEOError:
            logger.exception("DataForSEO SERP lookup failed for query=%r", query)
            return DomainVisibility(
                query=query,
                domain=normalized_domain,
                domain_visible=None,
                visibility_position=None,
            )

        best_position: int | None = None
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type is not None and item_type != "organic":
                continue

            item_domain = item.get("domain")
            if not isinstance(item_domain, str):
                continue
            if normalize_domain(item_domain) != normalized_domain:
                continue

            position = item.get("rank_absolute")
            if not isinstance(position, int):
                position = item.get("rank_group")
            if isinstance(position, int):
                if best_position is None or position < best_position:
                    best_position = position

        if best_position is None:
            return DomainVisibility(
                query=query,
                domain=normalized_domain,
                domain_visible=False,
                visibility_position=None,
            )

        return DomainVisibility(
            query=query,
            domain=normalized_domain,
            domain_visible=True,
            visibility_position=best_position,
        )

    def _post(self, path: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = self._session.post(
                url,
                json=payload,
                auth=self._auth,
                timeout=self._timeout,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DataForSEOError(f"DataForSEO request failed: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise DataForSEOError("DataForSEO returned non-JSON response.") from exc

        if not isinstance(body, dict):
            raise DataForSEOError("DataForSEO returned an unexpected payload shape.")

        status_code = body.get("status_code")
        if status_code not in (20000, 20001):
            message = body.get("status_message") or "Unknown DataForSEO error"
            raise DataForSEOError(f"DataForSEO error {status_code}: {message}")

        return body

    @staticmethod
    def _extract_result_items(response_json: dict[str, Any]) -> list[Any]:
        tasks = response_json.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            return []

        items: list[Any] = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_status = task.get("status_code")
            if task_status not in (20000, 20001, None):
                logger.warning(
                    "DataForSEO task failed: %s %s",
                    task_status,
                    task.get("status_message"),
                )
                continue
            results = task.get("result")
            if not isinstance(results, list):
                continue
            for result in results:
                if not isinstance(result, dict):
                    continue
                result_items = result.get("items")
                if isinstance(result_items, list):
                    items.extend(result_items)
                else:
                    # Keyword endpoints may return the keyword object itself.
                    items.append(result)
        return items

    @staticmethod
    def _to_difficulty(
        competition_index: Any,
        competition: Any,
    ) -> int:
        if isinstance(competition_index, (int, float)):
            return max(0, min(100, int(round(float(competition_index)))))

        if isinstance(competition, (int, float)):
            # Legacy google endpoint returns competition as 0.0–1.0.
            if 0.0 <= float(competition) <= 1.0:
                return max(0, min(100, int(round(float(competition) * 100))))
            return max(0, min(100, int(round(float(competition)))))

        if isinstance(competition, str):
            mapping = {"LOW": 25, "MEDIUM": 50, "HIGH": 80}
            return mapping.get(competition.upper(), 0)

        return 0


def build_dataforseo_client_from_config(config: Any) -> DataForSEOClient:
    """Construct a client from a Flask config object."""
    login = getattr(config, "DATAFORSEO_LOGIN", None)
    password = getattr(config, "DATAFORSEO_PASSWORD", None)
    if not login or not password:
        raise ValueError(
            "DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD must be set in the environment."
        )

    return DataForSEOClient(
        login=str(login),
        password=str(password),
        base_url=str(
            getattr(config, "DATAFORSEO_BASE_URL", "https://api.dataforseo.com")
        ),
        location_code=int(getattr(config, "DATAFORSEO_LOCATION_CODE", 2840)),
        language_code=str(getattr(config, "DATAFORSEO_LANGUAGE_CODE", "en")),
        timeout_seconds=float(getattr(config, "DATAFORSEO_TIMEOUT_SECONDS", 60.0)),
    )

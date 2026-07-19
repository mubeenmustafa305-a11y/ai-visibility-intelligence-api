"""Business profile application service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select

from app.extensions import db
from app.models import BusinessProfile, DiscoveredQuery


@dataclass(frozen=True)
class ProfileSummary:
    total_queries_discovered: int
    avg_opportunity_score: float | None


@dataclass(frozen=True)
class ProfileDetail:
    profile: BusinessProfile
    summary: ProfileSummary


class ProfileService:
    """Create and retrieve business profiles."""

    def create_profile(
        self,
        *,
        name: str,
        domain: str,
        industry: str,
        description: str,
        competitors: list[str],
    ) -> BusinessProfile:
        profile = BusinessProfile(
            uuid=str(uuid.uuid4()),
            name=name,
            domain=domain,
            industry=industry,
            description=description,
            competitors=list(competitors),
            status="created",
        )
        db.session.add(profile)
        db.session.commit()
        return profile

    def get_profile(self, profile_uuid: str) -> BusinessProfile | None:
        return db.session.get(BusinessProfile, profile_uuid)

    def get_summary(self, profile_uuid: str) -> ProfileSummary:
        total, average = db.session.execute(
            select(
                func.count(DiscoveredQuery.uuid),
                func.avg(DiscoveredQuery.opportunity_score),
            ).where(DiscoveredQuery.profile_uuid == profile_uuid)
        ).one()

        if int(total) == 0 or average is None:
            avg_score: float | None = None
        else:
            avg_score = round(float(average), 4)

        return ProfileSummary(
            total_queries_discovered=int(total),
            avg_opportunity_score=avg_score,
        )

    def get_profile_detail(self, profile_uuid: str) -> ProfileDetail | None:
        """Fetch a profile and its summary in one service call."""
        profile = self.get_profile(profile_uuid)
        if profile is None:
            return None
        return ProfileDetail(profile=profile, summary=self.get_summary(profile_uuid))


profile_service = ProfileService()

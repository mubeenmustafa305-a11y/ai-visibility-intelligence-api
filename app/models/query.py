"""Discovered query persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import utcnow


class DiscoveredQuery(db.Model):
    """A commercially relevant query discovered and scored for a profile."""

    __tablename__ = "discovered_queries"

    uuid: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    profile_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("business_profiles.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pipeline_runs.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_search_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    competitive_difficulty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opportunity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)
    # Null means visibility could not be determined (API filter status: unknown).
    domain_visible: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    visibility_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    profile = relationship("BusinessProfile", back_populates="queries")
    pipeline_run = relationship("PipelineRun", back_populates="queries")
    recommendations = relationship(
        "ContentRecommendation",
        back_populates="query",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<DiscoveredQuery {self.uuid} score={self.opportunity_score}>"

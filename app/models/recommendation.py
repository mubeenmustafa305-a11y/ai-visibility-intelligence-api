"""Content recommendation persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.extensions import db
from app.models.base import utcnow


class ContentRecommendation(db.Model):
    """Actionable content recommendation produced by Agent 3."""

    __tablename__ = "content_recommendations"

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
    query_uuid: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("discovered_queries.uuid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    target_keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )

    profile = relationship("BusinessProfile", back_populates="recommendations")
    query = relationship("DiscoveredQuery", back_populates="recommendations")

    def __repr__(self) -> str:
        return f"<ContentRecommendation {self.uuid} priority={self.priority!r}>"

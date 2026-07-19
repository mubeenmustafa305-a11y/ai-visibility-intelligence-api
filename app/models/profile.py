"""Business profile persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.extensions import db
from app.models.base import utcnow


class BusinessProfile(db.Model):
    """Registered business used as input to the visibility pipeline."""

    __tablename__ = "business_profiles"

    uuid: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    competitors: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    pipeline_runs = relationship(
        "PipelineRun",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    queries = relationship(
        "DiscoveredQuery",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    recommendations = relationship(
        "ContentRecommendation",
        back_populates="profile",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<BusinessProfile {self.uuid} domain={self.domain!r}>"

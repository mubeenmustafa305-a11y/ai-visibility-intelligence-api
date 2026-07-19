"""Pipeline run persistence model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.base import utcnow


class PipelineRun(db.Model):
    """A single execution of the 3-agent visibility pipeline."""

    __tablename__ = "pipeline_runs"

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
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    queries_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queries_scored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    profile = relationship("BusinessProfile", back_populates="pipeline_runs")
    queries = relationship(
        "DiscoveredQuery",
        back_populates="pipeline_run",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )

    def __repr__(self) -> str:
        return f"<PipelineRun {self.uuid} status={self.status!r}>"

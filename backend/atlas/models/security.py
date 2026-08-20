"""Where a shared rate limiter keeps its counters.

Not part of the domain — no feature reads this — but it is a table, and a table Alembic does
not know about is a table that does not exist on a fresh deployment.

Keys are stored hashed. A counter row for a failed login would otherwise hold an email address,
and a limiter should not become the place someone learns which accounts exist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, PrimaryKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from atlas.db.base import Base


class RateLimitCounter(Base):
    """One key's hits within one fixed window."""

    __tablename__ = "rate_limit_counters"
    __table_args__ = (
        PrimaryKeyConstraint("key_hash", "window_start", name="pk_rate_limit_counters"),
        # Pruning scans by window, and does so far more often than anything scans by key.
        Index("ix_rate_limit_counters_window_start", "window_start"),
    )

    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

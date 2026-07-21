"""Agent step model. See architecture.md §10."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AgentStep(Base):
    """A single tool-call iteration taken by the agent while producing a message."""

    __tablename__ = "agent_steps"
    __table_args__ = (
        Index("ix_agent_steps_message_id_iteration", "message_id", "iteration"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_args: Mapped[dict] = mapped_column(JSONB, nullable=False)
    result_summary: Mapped[list] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow
    )

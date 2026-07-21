"""Message model. See architecture.md §10."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, Boolean, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Message(Base):
    """A single user/assistant/system message within a chat."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_chat_id_created_at", "chat_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    agent_iteration_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_budget_exhausted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=datetime.utcnow
    )

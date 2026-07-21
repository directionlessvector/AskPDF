"""User repository — all direct DB access for the users table."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    """Return the user with the given email, or None."""

    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    """Return the user with the given ID, or None."""

    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create(session: AsyncSession, email: str, hashed_password: str) -> User:
    """Create and persist a new local-auth user."""

    user = User(email=email, hashed_password=hashed_password, auth_provider="local")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user

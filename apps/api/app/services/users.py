"""User service — registration and authentication business logic."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import DuplicateEmailError, InvalidCredentialsError
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories import users as users_repo


async def register(session: AsyncSession, email: str, password: str) -> User:
    """Register a new local-auth user.

    Raises DuplicateEmailError if the email is already registered.
    """

    existing = await users_repo.get_by_email(session, email)
    if existing is not None:
        raise DuplicateEmailError(email)

    return await users_repo.create(session, email, hash_password(password))


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    """Authenticate a user by email/password.

    Raises InvalidCredentialsError if the email is unknown, the account has
    no local password (e.g. OAuth-only), or the password is wrong.
    """

    user = await users_repo.get_by_email(session, email)
    if user is None or user.hashed_password is None:
        raise InvalidCredentialsError()

    if not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError()

    return user

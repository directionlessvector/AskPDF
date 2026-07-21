"""Auth routes: register, login, and current-user lookup."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import create_access_token, get_current_user
from app.models.user import User
from app.schemas.users import TokenResponse, UserCreate, UserLogin, UserOut
from app.services import users as users_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=201,
    summary="Register a new user",
)
async def register(
    body: UserCreate, session: AsyncSession = Depends(get_session)
) -> User:
    """Create a new local-auth user account."""

    return await users_service.register(session, body.email, body.password)


@router.post("/login", response_model=TokenResponse, summary="Log in")
async def login(
    body: UserLogin, session: AsyncSession = Depends(get_session)
) -> TokenResponse:
    """Authenticate with email/password and receive a JWT access token."""

    user = await users_service.authenticate(session, body.email, body.password)
    return TokenResponse(access_token=create_access_token(user.id))


@router.get("/me", response_model=UserOut, summary="Get the current user")
async def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's profile."""

    return current_user

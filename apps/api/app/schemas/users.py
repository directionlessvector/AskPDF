"""User request/response schemas. See rules.md §4.1, §5."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Request body for user registration."""

    email: EmailStr
    password: str = Field(min_length=8)


class UserLogin(BaseModel):
    """Request body for login."""

    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Public-safe user representation — never includes password fields."""

    id: uuid.UUID
    email: EmailStr
    auth_provider: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Response body for a successful login."""

    access_token: str
    token_type: str = "bearer"

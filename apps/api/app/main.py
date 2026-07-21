"""FastAPI application entrypoint."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.auth import router as auth_router
from app.core.config import get_settings
from app.core.exceptions import DuplicateEmailError, InvalidCredentialsError

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(auth_router, prefix="/api/v1")


@app.exception_handler(DuplicateEmailError)
async def duplicate_email_handler(
    request: Request, exc: DuplicateEmailError
) -> JSONResponse:
    """Map DuplicateEmailError to a 409 response."""

    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "duplicate_email",
                "message": "An account with this email already exists.",
                "details": {},
            }
        },
    )


@app.exception_handler(InvalidCredentialsError)
async def invalid_credentials_handler(
    request: Request, exc: InvalidCredentialsError
) -> JSONResponse:
    """Map InvalidCredentialsError to a 401 response."""

    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "invalid_credentials",
                "message": "Incorrect email or password.",
                "details": {},
            }
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Return API liveness status."""

    return {"status": "ok"}

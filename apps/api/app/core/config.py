"""Typed settings for the API service."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    app_name: str = "AskPDF API"
    environment: str = "local"
    database_url: str = "postgresql+asyncpg://askpdf:askpdf@postgres:5432/askpdf"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return cached API settings."""

    return Settings()

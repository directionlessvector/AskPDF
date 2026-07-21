"""Central API exception types, mapped to HTTP status codes. See rules.md §4.1."""


class AppError(Exception):
    """Base class for application-level errors mapped to HTTP responses."""


class DuplicateEmailError(AppError):
    """Raised when registering an email that is already in use."""


class InvalidCredentialsError(AppError):
    """Raised when login credentials are missing or incorrect."""

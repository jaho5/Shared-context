"""Error types as defined in spec §5."""


class SharedContextError(Exception):
    """Base error for all shared context operations."""

    code: str

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": self.code, "message": self.message}


class KeyNotFoundError(SharedContextError):
    code = "KEY_NOT_FOUND"


class ValueTooLargeError(SharedContextError):
    code = "VALUE_TOO_LARGE"


class StoreFullError(SharedContextError):
    code = "STORE_FULL"


class InvalidKeyError(SharedContextError):
    code = "INVALID_KEY"


class SessionNotFoundError(SharedContextError):
    code = "SESSION_NOT_FOUND"


class SessionArchivedError(SharedContextError):
    code = "SESSION_ARCHIVED"

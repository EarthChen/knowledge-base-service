"""Typed domain exceptions for the knowledge base API."""


class KbError(Exception):
    status_code: int = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


class KbClientError(KbError):
    status_code = 400


class KbNotFound(KbError):
    status_code = 404


class KbConflict(KbError):
    status_code = 409


class KbForbidden(KbError):
    status_code = 403


class KbServiceUnavailable(KbError):
    status_code = 503

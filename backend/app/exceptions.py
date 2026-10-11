"""Our own errors. Services raise these; the error handler turns them into JSON."""


class AppError(Exception):
    status_code = 400

    def __init__(self, detail: str, status_code: int | None = None, headers: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        self.headers = headers


class BadRequestError(AppError):
    status_code = 400


class UnauthorizedError(AppError):
    status_code = 401


class ForbiddenError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class TooManyRequestsError(AppError):
    status_code = 429

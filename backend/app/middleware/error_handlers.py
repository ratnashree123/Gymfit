"""One place that turns every kind of error into a clean JSON response."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.exceptions import AppError

logger = logging.getLogger("gymfit")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail},
                            headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        # We list the field and the message only. The submitted value is NOT echoed
        # back, because it could be a password.
        errors = []
        for err in exc.errors():
            location = [str(part) for part in err.get("loc", []) if part not in ("body", "query", "path")]
            message = str(err.get("msg", "Invalid value"))
            if message.startswith("Value error, "):
                message = message[len("Value error, "):]
            errors.append({"field": ".".join(location) or "request", "message": message})
        return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, exc: IntegrityError):
        logger.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc.orig)
        return JSONResponse(status_code=409,
                            content={"detail": "This change conflicts with existing data"})

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError):
        logger.exception("Database error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "A database error occurred"})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

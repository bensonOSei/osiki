from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from loguru import logger


class OsikiError(Exception):
    def __init__(self, message: str, details: dict[str, str] | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class NotFoundError(OsikiError):
    pass


class ConflictError(OsikiError):
    pass


class AuthorizationError(OsikiError):
    pass


class ValidationError(OsikiError):
    pass


def _get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unknown")


async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": "not_found",
            "message": exc.message,
            "details": exc.details,
            "request_id": _get_request_id(request),
        },
    )


async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": "conflict",
            "message": exc.message,
            "details": exc.details,
            "request_id": _get_request_id(request),
        },
    )


async def authorization_handler(
    request: Request, exc: AuthorizationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={
            "error": "forbidden",
            "message": exc.message,
            "details": exc.details,
            "request_id": _get_request_id(request),
        },
    )


async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "validation_error",
            "message": exc.message,
            "details": exc.details,
            "request_id": _get_request_id(request),
        },
    )


async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = _get_request_id(request)
    logger.exception(
        "Unhandled exception",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred",
            "request_id": request_id,
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(NotFoundError, not_found_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ConflictError, conflict_handler)  # type: ignore[arg-type]
    app.add_exception_handler(AuthorizationError, authorization_handler)  # type: ignore[arg-type]
    app.add_exception_handler(ValidationError, validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, internal_error_handler)

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for domain errors. Carries no HTTP knowledge."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationError(AppError):
    """A rule the schema cannot express (upload size, media type, count)."""

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_error"


class AnalysisError(AppError):
    """The vision model could not be reached or answered unusably."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "analysis_failed"


class EmbeddingError(AppError):
    """The embedding model could not be reached or returned an unusable vector.

    Always caught in the service — a missing vector costs searchability, not the
    analysis — so this never reaches a handler. It exists so the failure is
    labelled as its own thing rather than as `analysis_failed`.
    """

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "embedding_failed"


def _error(code: str, message: str, status_code: int, **extra: object) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, **extra}},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.code, exc.message, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error(
            "validation_error",
            "Request validation failed.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=jsonable_encoder(exc.errors()),
        )

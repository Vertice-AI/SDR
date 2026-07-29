"""FastAPI app factory.

A API só recebe, valida, persiste e enfileira — nenhuma regra de negócio
mora aqui (`docs/02-arquitetura.md` §4).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.config import get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(log_level=settings.log_level, phone_hash_pepper=settings.phone_hash_pepper)
    logger.info("app_startup", app_env=settings.app_env)
    yield
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(title="sdr-agent", lifespan=lifespan)

    app.include_router(health_router)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        logger.warning("domain_error", code=exc.code, message=exc.message, details=exc.details)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app


app = create_app()

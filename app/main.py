import logging
import time
import uuid
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request

from app.config import Settings, get_settings
from app.core.logging import setup_logging
from app.routers import general, qbittorrent, torznab
from app.services.airdcpp import AirDCClient
from app.services.cache import AsyncTTLCache
from app.services.database import Repository
from app.services.metadata import MetadataClient
from app.services.search import SearchService


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or get_settings()
    setup_logging(configured.log_level)
    logger = logging.getLogger("app")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configured.validate_runtime()
        repository = Repository(configured.db_path)
        await repository.initialize()
        timeout = httpx.Timeout(configured.search_timeout + 5, connect=5)
        http = httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)
        airdcpp = AirDCClient(http, configured)
        metadata = MetadataClient(http, configured.tmdb_api_key.get_secret_value())
        cache = AsyncTTLCache(
            configured.search_cache_ttl, configured.search_negative_cache_ttl, configured.search_cache_size
        )
        application.state.settings = configured
        application.state.repository = repository
        application.state.airdcpp = airdcpp
        application.state.search_cache = cache
        application.state.search_service = SearchService(airdcpp, metadata, repository, cache, configured)
        logger.info("AirDC++ Bridge v2 iniciado; database=%s", configured.db_path)
        yield
        await http.aclose()

    application = FastAPI(
        title="AirDC++ Torznab/qBittorrent Bridge",
        version="2.0.0-beta.1",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.monotonic()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_id=%s method=%s path=%s error=unhandled", request_id, request.method, request.url.path
            )
            raise
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.monotonic() - started) * 1000,
        )
        return response

    application.include_router(general.router)
    application.include_router(torznab.router)
    application.include_router(qbittorrent.router)
    return application


app = create_app()

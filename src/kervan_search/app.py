"""The HTTP API (SPEC §7): GET /search and GET /health."""

import logging
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import __version__, jsonlog
from .config import Settings
from .corpus import DEFAULT_KB_DIR, load_articles
from .providers import HttpProvider, IndexDoc, ProviderError, SimulatedProvider, VectorProvider

TRACE_HEADER = "X-Trace-Id"
_TRACE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class SearchResult(BaseModel):
    id: str
    title: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


class Health(BaseModel):
    status: Literal["ok"]


class ErrorBody(BaseModel):
    error: str
    message: str


def make_provider(settings: Settings, transport: httpx.BaseTransport | None = None) -> VectorProvider:
    if settings.vector_provider == "http":
        assert settings.vector_provider_url  # Settings.validate guarantees it
        return HttpProvider(
            settings.vector_provider_url, settings.vector_provider_api_key, transport=transport
        )
    return SimulatedProvider()


def _level(status: int) -> int:
    if status >= 500:
        return logging.ERROR
    return logging.WARNING if status >= 400 else logging.INFO


def create_app(
    settings: Settings | None = None,
    *,
    kb_dir: Path = DEFAULT_KB_DIR,
    provider: VectorProvider | None = None,
    configure_logging: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    log = jsonlog.configure(settings.log_file) if configure_logging else logging.getLogger(jsonlog.LOGGER_NAME)
    articles = load_articles(kb_dir)  # fails fast on a malformed knowledge base
    by_id = {a.id: a for a in articles}
    vectors = provider or make_provider(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        docs = [IndexDoc(a.id, f"{a.title}\n\n{a.body}") for a in articles]
        await run_in_threadpool(vectors.index, docs)
        log.info("indexed", extra={"fields": {"articles": len(docs), "provider": vectors.name}})
        yield

    app = FastAPI(
        title="kervan-search",
        version=__version__,
        description="Knowledge base search for Kervan customer help articles.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        trace_id = request.headers.get(TRACE_HEADER, "")
        if not _TRACE_ID.match(trace_id):
            trace_id = uuid.uuid4().hex
        request.state.trace_id = trace_id
        request.state.log_fields = {}
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("unhandled error", extra={"fields": {"trace_id": trace_id}})
            response = JSONResponse(
                status_code=500, content={"error": "internal", "message": "internal error"}
            )
        response.headers[TRACE_HEADER] = trace_id
        # The query string is never logged: customers may type personal data into it.
        fields = {
            "trace_id": trace_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000),
            **request.state.log_fields,
        }
        log.log(_level(response.status_code), "request", extra={"fields": fields})
        return response

    @app.get(
        "/search",
        response_model=SearchResponse,
        responses={502: {"model": ErrorBody, "description": "The vector search provider failed"}},
    )
    def search(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=500, description="Search text")],
        k: Annotated[int, Query(ge=1, le=10, description="Number of results")] = 3,
    ):
        try:
            matches = vectors.query(q, k)
        except ProviderError as e:
            log.error(
                "vector provider failed",
                extra={"fields": {"trace_id": request.state.trace_id, "provider": vectors.name, "error": str(e)}},
            )
            return JSONResponse(
                status_code=502,
                content={"error": "provider_unavailable", "message": "the vector search provider failed"},
            )
        results = []
        for match in matches:
            article = by_id.get(match.id)
            if article is None:
                log.warning(
                    "provider returned an unknown article",
                    extra={"fields": {"trace_id": request.state.trace_id, "article": match.id}},
                )
                continue
            results.append(
                SearchResult(id=article.id, title=article.title, snippet=article.snippet(q), score=match.score)
            )
        request.state.log_fields = {"k": k, "results": len(results)}
        return SearchResponse(results=results)

    @app.get("/health", response_model=Health)
    def health() -> Health:
        return Health(status="ok")

    return app

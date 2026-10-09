"""HttpProvider against a fake external vector search API (httpx.MockTransport)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from kervan_search.app import create_app, make_provider
from kervan_search.config import Settings
from kervan_search.providers import HttpProvider, IndexDoc, Match, ProviderError

BASE = "https://vectors.example.test/api/"


class FakeVectorApi:
    """Records requests; answers /v1/query with `matches` (or a raw `body`)."""

    def __init__(self, matches=None, status: int = 200, body: bytes | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self.matches = matches if matches is not None else []
        self.status = status
        self.body = body

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "boom"})
        if request.url.path.endswith("/v1/index"):
            return httpx.Response(204)
        if self.body is not None:
            return httpx.Response(200, content=self.body)
        return httpx.Response(200, json={"matches": self.matches})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


def provider(api: FakeVectorApi, api_key: str | None = "k-123") -> HttpProvider:
    return HttpProvider(BASE, api_key, transport=api.transport())


def http_settings() -> Settings:
    return Settings(vector_provider="http", vector_provider_url=BASE, vector_provider_api_key="k-123")


def test_index_posts_the_documents():
    api = FakeVectorApi()
    provider(api).index([IndexDoc("a", "alpha text"), IndexDoc("b", "beta text")])
    (request,) = api.requests
    assert request.method == "POST"
    assert str(request.url) == "https://vectors.example.test/api/v1/index"
    assert request.headers["Authorization"] == "Bearer k-123"
    assert json.loads(request.content) == {
        "documents": [{"id": "a", "text": "alpha text"}, {"id": "b", "text": "beta text"}]
    }


def test_query_sends_text_and_k_and_ranks_the_answer():
    api = FakeVectorApi(
        [
            {"id": "b", "score": 0.5},
            {"id": "a", "score": 0.912345},
            {"id": "c", "score": 0.5},
            {"id": "z", "score": 0},
            {"id": "y", "score": -0.2},
        ]
    )
    assert provider(api).query("where is my parcel", 3) == [Match("a", 0.9123), Match("b", 0.5), Match("c", 0.5)]
    (request,) = api.requests
    assert str(request.url) == "https://vectors.example.test/api/v1/query"
    assert json.loads(request.content) == {"query": "where is my parcel", "top_k": 3}


def test_no_authorization_header_without_api_key():
    api = FakeVectorApi()
    provider(api, api_key=None).query("x", 1)
    assert "Authorization" not in api.requests[0].headers


@pytest.mark.parametrize("status", [400, 401, 500, 503])
def test_error_status_raises(status):
    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        provider(FakeVectorApi(status=status)).query("x", 3)


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"{}",
        b'{"matches": 3}',
        b'{"matches": [{"id": "a"}]}',
        b'{"matches": [{"id": "a", "score": "high"}]}',
        b'{"matches": [{"id": "a", "score": NaN}]}',
    ],
)
def test_malformed_answer_raises(body):
    with pytest.raises(ProviderError, match="malformed"):
        provider(FakeVectorApi(body=body)).query("x", 3)


def test_transport_failure_raises():
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(ProviderError, match="ConnectError"):
        HttpProvider(BASE, transport=httpx.MockTransport(refuse)).index([])


def test_make_provider_selects_by_setting():
    assert make_provider(Settings()).name == "simulated"
    assert isinstance(make_provider(http_settings(), FakeVectorApi().transport()), HttpProvider)


def test_service_over_http_provider():
    api = FakeVectorApi(
        [
            {"id": "customs", "score": 0.8},
            {"id": "no-such-article", "score": 0.7},
            {"id": "returns", "score": 0.4},
        ]
    )
    app = create_app(http_settings(), provider=make_provider(http_settings(), api.transport()))
    with TestClient(app) as client:
        assert len(api.requests) == 1  # indexed at start
        indexed = json.loads(api.requests[0].content)["documents"]
        assert len(indexed) == 13 and indexed[0]["text"].startswith("Branches and opening hours")
        body = client.get("/search", params={"q": "customs duties", "k": 3}).json()
    assert [(r["id"], r["score"]) for r in body["results"]] == [("customs", 0.8), ("returns", 0.4)]
    assert body["results"][0]["title"] == "International shipments and customs"
    assert json.loads(api.requests[1].content) == {"query": "customs duties", "top_k": 3}


def test_provider_failure_is_502(capsys):
    api = FakeVectorApi()
    with TestClient(create_app(http_settings(), provider=make_provider(http_settings(), api.transport()))) as client:
        api.status = 503
        response = client.get("/search", params={"q": "parcel"})
    assert response.status_code == 502
    assert response.json() == {"error": "provider_unavailable", "message": "the vector search provider failed"}
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    failure = next(line for line in lines if line["msg"] == "vector provider failed")
    assert failure["level"] == "error" and failure["provider"] == "http" and "503" in failure["error"]
    assert lines[-1]["status"] == 502 and lines[-1]["level"] == "error"


def test_unexpected_error_is_500_and_logged(capsys):
    class Broken:
        name = "broken"

        def index(self, docs):
            pass

        def query(self, text, k):
            raise RuntimeError("bug")

    with TestClient(create_app(Settings(), provider=Broken())) as client:
        response = client.get("/search", params={"q": "parcel"})
    assert response.status_code == 500
    assert response.json() == {"error": "internal", "message": "internal error"}
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert any(line["msg"] == "unhandled error" and line["error"] == "RuntimeError" for line in lines)
    assert lines[-1]["status"] == 500 and lines[-1]["level"] == "error"

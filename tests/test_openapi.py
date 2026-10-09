"""docs/openapi.json is the SearchApi contract (SPEC §1.2): it must match the code exactly."""

import json

from fastapi.testclient import TestClient

from kervan_search.app import create_app
from kervan_search.config import Settings
from kervan_search.openapi import OPENAPI_FILE, render

STALE = "docs/openapi.json is stale; regenerate it with `python -m kervan_search.openapi`"


def committed() -> str:
    return OPENAPI_FILE.read_text(encoding="utf-8")


def test_committed_file_matches_the_code():
    assert committed() == render(create_app(Settings(), configure_logging=False)), STALE


def test_served_document_matches_the_committed_file(client: TestClient):
    assert client.get("/openapi.json").json() == json.loads(committed())


def test_document_does_not_depend_on_the_provider():
    http = Settings(vector_provider="http", vector_provider_url="https://vectors.example.test")
    assert render(create_app(http, configure_logging=False)) == committed()


def test_contract_shape():
    doc = json.loads(committed())
    assert set(doc["paths"]) == {"/search", "/health"}
    params = {p["name"]: p for p in doc["paths"]["/search"]["get"]["parameters"]}
    assert params["q"]["required"] is True
    k = params["k"]["schema"]
    assert (k["minimum"], k["maximum"], k["default"]) == (1, 10, 3)
    result = doc["components"]["schemas"]["SearchResult"]
    assert sorted(result["required"]) == ["id", "score", "snippet", "title"]

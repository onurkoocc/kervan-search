from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kervan_search.app import create_app
from kervan_search.config import Settings

FIXTURE_KB = Path(__file__).parent / "fixtures" / "kb"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The service over the real knowledge base with the simulated provider."""
    with TestClient(create_app(Settings())) as c:
        yield c


def ids(response) -> list[str]:
    return [r["id"] for r in response.json()["results"]]

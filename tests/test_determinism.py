"""Same corpus and query: the same scores on every machine, process and run."""

import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FIXTURE_KB
from kervan_search.app import create_app
from kervan_search.config import Settings
from kervan_search.corpus import load_articles
from kervan_search.providers import IndexDoc, Match, SimulatedProvider

SRC = Path(__file__).resolve().parents[1] / "src"


def fixture_provider(shuffle_seed: int | None = None) -> SimulatedProvider:
    docs = [IndexDoc(a.id, f"{a.title}\n\n{a.body}") for a in load_articles(FIXTURE_KB)]
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(docs)
    provider = SimulatedProvider()
    provider.index(docs)
    return provider


def test_golden_scores():
    # Pinned values: a change here changes ranking for every consumer of SearchApi.
    provider = fixture_provider()
    assert provider.query("parcel tracking number", 3) == [Match("alpha", 0.7591), Match("gamma", 0.1092)]
    assert provider.query("change the delivery date", 3) == [Match("beta", 0.6772), Match("gamma", 0.1092)]
    assert provider.query("customs duties", 3) == [Match("gamma", 0.7256)]


def test_golden_embedding():
    assert fixture_provider().embed("parcel tracking") == {
        150: pytest.approx(-0.6053485081062916, rel=1e-12),
        723: pytest.approx(0.7959605415681652, rel=1e-12),
    }


def test_index_order_does_not_matter():
    queries = ["parcel tracking number", "delivery date", "customs"]
    baseline = [fixture_provider().query(q, 3) for q in queries]
    for seed in range(5):
        assert [fixture_provider(seed).query(q, 3) for q in queries] == baseline


def test_repeated_requests_are_identical(client: TestClient):
    params = {"q": "reschedule my delivery", "k": 5}
    first = client.get("/search", params=params).json()
    for _ in range(3):
        assert client.get("/search", params=params).json() == first


def test_independent_of_hash_seed(client: TestClient):
    """Fresh interpreters with different PYTHONHASHSEED values score exactly like this one."""
    params = {"q": "my parcel arrived damaged, open a ticket", "k": 10}
    expected = client.get("/search", params=params).json()
    script = (
        "import json\n"
        "from fastapi.testclient import TestClient\n"
        "from kervan_search.app import create_app\n"
        "from kervan_search.config import Settings\n"
        "with TestClient(create_app(Settings(), configure_logging=False)) as c:\n"
        f"    print(json.dumps(c.get('/search', params={params!r}).json()))\n"
    )
    for seed in ("0", "1", "4242"):
        env = os.environ | {"PYTHONHASHSEED": seed, "PYTHONPATH": str(SRC)}
        out = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, check=True, encoding="utf-8"
        ).stdout
        assert json.loads(out.strip().splitlines()[-1]) == expected


def test_two_app_instances_agree():
    params = {"q": "customs duties international", "k": 10}
    with TestClient(create_app(Settings())) as a, TestClient(create_app(Settings())) as b:
        assert a.get("/search", params=params).json() == b.get("/search", params=params).json()

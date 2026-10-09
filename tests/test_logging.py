"""JSON-lines logs (SPEC §6)."""

import json
import re

from fastapi.testclient import TestClient

from kervan_search.app import create_app
from kervan_search.config import Settings

TS = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
SECRET_QUERY = "my phone is 05551234567 and my name is Ayse Yilmaz"


def run_requests(tmp_path, *requests):
    log_file = tmp_path / "logs" / "search.jsonl"
    with TestClient(create_app(Settings(log_file=str(log_file)))) as client:
        responses = [client.get(path, params=params, headers=headers) for path, params, headers in requests]
    lines = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    return responses, lines, log_file


def test_every_line_has_the_required_fields(tmp_path):
    _, lines, _ = run_requests(tmp_path, ("/health", {}, {}), ("/search", {"q": "parcel"}, {}))
    assert lines
    for line in lines:
        assert line["service"] == "search"
        assert line["level"] in ("info", "warn", "error")
        assert TS.match(line["ts"]), line["ts"]
        assert isinstance(line["msg"], str) and line["msg"]
        assert list(line)[:4] == ["ts", "level", "service", "msg"]


def test_startup_and_request_lines(tmp_path):
    _, lines, _ = run_requests(tmp_path, ("/search", {"q": "parcel delivery", "k": "2"}, {}))
    assert lines[0] == lines[0] | {"msg": "indexed", "articles": 13, "provider": "simulated", "level": "info"}
    request = lines[-1]
    assert request["msg"] == "request"
    assert request["level"] == "info"
    assert request["method"] == "GET" and request["path"] == "/search"
    assert request["status"] == 200
    assert isinstance(request["duration_ms"], int) and request["duration_ms"] >= 0
    assert request["k"] == 2 and request["results"] == 2
    assert re.fullmatch(r"[0-9a-f]{32}", request["trace_id"])


def test_client_errors_are_warnings(tmp_path):
    (response,), lines, _ = run_requests(tmp_path, ("/search", {"q": "parcel", "k": "99"}, {}))
    assert response.status_code == 422
    assert lines[-1]["level"] == "warn" and lines[-1]["status"] == 422


def test_trace_id_is_propagated(tmp_path):
    (response,), lines, _ = run_requests(tmp_path, ("/health", {}, {"X-Trace-Id": "abc-123"}))
    assert response.headers["X-Trace-Id"] == "abc-123"
    assert lines[-1]["trace_id"] == "abc-123"


def test_malformed_trace_id_is_replaced(tmp_path):
    (response,), lines, _ = run_requests(tmp_path, ("/health", {}, {"X-Trace-Id": "bad id\n{}"}))
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Trace-Id"])
    assert lines[-1]["trace_id"] == response.headers["X-Trace-Id"]


def test_query_text_is_never_logged(tmp_path, capsys):
    _, _, log_file = run_requests(tmp_path, ("/search", {"q": SECRET_QUERY}, {}))
    for text in (log_file.read_text(encoding="utf-8"), capsys.readouterr().out):
        assert "05551234567" not in text and "Yilmaz" not in text and "phone" not in text


def test_stdout_gets_the_same_lines(tmp_path, capsys):
    _, lines, _ = run_requests(tmp_path, ("/health", {}, {}))
    stdout = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert stdout == lines


def test_log_file_is_appended(tmp_path):
    _, first, _ = run_requests(tmp_path, ("/health", {}, {}))
    _, both, _ = run_requests(tmp_path, ("/health", {}, {}))
    assert both[: len(first)] == first and len(both) == 2 * len(first)


def test_stdout_only_without_log_file(tmp_path, capsys):
    with TestClient(create_app(Settings())) as client:
        client.get("/health")
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert lines[-1]["path"] == "/health"
    assert not list(tmp_path.iterdir())

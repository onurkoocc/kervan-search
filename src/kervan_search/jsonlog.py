"""JSON-lines logging (SPEC §6): one object per line on stdout and, with LOG_FILE, in that file.

`service`, `ts`, `level` and `msg` are always present. Other fields are passed as
`extra={"fields": {...}}`. Never pass personal data or raw query text.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from .config import SERVICE

LOGGER_NAME = "kervan_search"
_LEVELS = {logging.DEBUG: "info", logging.INFO: "info", logging.WARNING: "warn"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str = SERVICE) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        line = {
            "ts": ts.replace("+00:00", "Z"),
            "level": _LEVELS.get(record.levelno, "error"),
            "service": self.service,
            "msg": record.getMessage(),
        }
        for key, value in getattr(record, "fields", {}).items():
            line.setdefault(key, value)
        if record.exc_info and record.levelno >= logging.ERROR:
            line.setdefault("error", type(record.exc_info[1]).__name__)
        return json.dumps(line, ensure_ascii=False, separators=(",", ":"))


class StdoutHandler(logging.StreamHandler):
    """Looks up sys.stdout on every write, so redirection (and pytest capture) works."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure(log_file: str | None, names: tuple[str, ...] = (LOGGER_NAME,)) -> logging.Logger:
    """(Re)attach the JSON handlers to the named loggers; returns the service logger."""
    formatter = JsonFormatter()
    handlers: list[logging.Handler] = [StdoutHandler()]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, mode="a", encoding="utf-8"))
    for name in names:
        logger = logging.getLogger(name)
        for old in list(logger.handlers):
            logger.removeHandler(old)
            old.close()
        for handler in handlers:
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logging.getLogger(LOGGER_NAME)

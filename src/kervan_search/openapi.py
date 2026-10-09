"""The committed OpenAPI document, docs/openapi.json (SPEC §1.2, interface SearchApi).

Regenerate with `python -m kervan_search.openapi`; tests fail when it is stale.
"""

import json
from pathlib import Path

from fastapi import FastAPI

from .app import create_app
from .config import Settings

OPENAPI_FILE = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"


def render(app: FastAPI) -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    app = create_app(Settings(), configure_logging=False)
    OPENAPI_FILE.write_text(render(app), encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_FILE}")


if __name__ == "__main__":
    main()

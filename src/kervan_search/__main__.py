"""`python -m kervan_search`: serve on 0.0.0.0:$PORT."""

import sys

import uvicorn

from . import jsonlog
from .app import create_app
from .config import ConfigError, Settings


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        jsonlog.configure(None).error("invalid configuration", extra={"fields": {"error": str(e)}})
        return 2
    jsonlog.configure(settings.log_file, names=(jsonlog.LOGGER_NAME, "uvicorn"))
    app = create_app(settings, configure_logging=False)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
        log_config=None,
        access_log=False,  # the app logs each request itself
        server_header=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Configuration from the environment only (SPEC §2). Defaults are the compose values."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

SERVICE = "search"
PROVIDERS = ("simulated", "http")


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    port: int = 8001
    log_file: str | None = None
    vector_provider: str = "simulated"
    # Only for VECTOR_PROVIDER=http (an external provider; not used in Kervan).
    vector_provider_url: str | None = None
    vector_provider_api_key: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "Settings":
        raw_port = env.get("PORT", "8001")
        if not raw_port.isdigit() or not 0 < int(raw_port) < 65536:
            raise ConfigError(f"PORT must be a port number, got {raw_port!r}")
        settings = cls(
            port=int(raw_port),
            log_file=env.get("LOG_FILE") or None,
            vector_provider=env.get("VECTOR_PROVIDER", "simulated"),
            vector_provider_url=env.get("VECTOR_PROVIDER_URL") or None,
            vector_provider_api_key=env.get("VECTOR_PROVIDER_API_KEY") or None,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.vector_provider not in PROVIDERS:
            raise ConfigError(
                f"VECTOR_PROVIDER must be one of {', '.join(PROVIDERS)}, got {self.vector_provider!r}"
            )
        if self.vector_provider == "http" and not self.vector_provider_url:
            raise ConfigError("VECTOR_PROVIDER=http needs VECTOR_PROVIDER_URL")

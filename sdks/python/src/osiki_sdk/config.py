"""SDK configuration."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class OsikiConfig:
    base_url: str
    environment: str = "default"
    api_key: str | None = None
    poll_interval: float = 2.0
    bundle_ttl: float = 60.0
    bundle_cache_size: int = 10_000
    read_on_unavailable: Literal["deny", "allow"] = "deny"
    # (METHOD, template) pairs that are public in code, e.g.
    # (("GET", "/health"), ("POST", "/auth/login")).
    public_routes: tuple[tuple[str, str], ...] = ()
    log_success_sample_rate: float = 0.1
    log_flush_interval: float = 2.0
    log_batch_size: int = 100
    request_timeout: float = 2.0

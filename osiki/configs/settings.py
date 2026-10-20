from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Osiki"
    api_prefix: str = "/api/v1"

    # CORS
    cors_origins: list[str] = ["*"]
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]
    cors_allow_credentials: bool = True

    # Access logging: every denial is logged; this fraction of successes is.
    access_log_success_sample_rate: float = 0.1

    # MongoDB
    mongodb_url: str = "mongodb://localhost:27017/osiki"
    mongodb_database: str = "osiki"
    # Run each team operation in one MongoDB transaction. Needs a replica set,
    # so it is off by default; standalone MongoDB rejects transactions.
    mongodb_transactions: bool = False

    # Refuse requests without X-Osiki-Actor instead of treating them as the
    # anonymous developer. Off for self-hosted use; hosted front doors set it
    # so a gateway that drops the header fails closed.
    require_actor: bool = False

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_password: str = ""


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):  # type: ignore[misc]
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_name: str = "Osiki"

    # MongoDB
    mongodb_url: str = "mongodb://localhost:27017/osiki"
    mongodb_database: str = "osiki"

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_password: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()

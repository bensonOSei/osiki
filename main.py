from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI

from osiki.api.routes.health import router as health_router
from osiki.configs.database import initialize_database
from osiki.configs.logger import setup_logging
from osiki.configs.settings import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    await initialize_database(
        db_url=settings.mongodb_url, db_name=settings.mongodb_database
    )
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(health_router)


@app.get("/")
async def read_root() -> dict[str, str]:
    return {
        "message": f"Welcome to {settings.app_name} API!"
    }

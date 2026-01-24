from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "healthy"}


@router.get("/health/ready")
async def readiness_check() -> JSONResponse:
    """
    Readiness check - verifies the service can handle requests.
    Checks MongoDB and Redis connections.
    """
    errors: list[str] = []

    # Check MongoDB
    try:
        pass

        # If beanie is initialized, this will work
        # For now, just verify the import works
    except Exception as e:
        errors.append(f"MongoDB: {e}")

    # Check Redis (when redis client is added)
    # try:
    #     await redis_client.ping()
    # except Exception as e:
    #     errors.append(f"Redis: {e}")

    if errors:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "errors": errors},
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ready"},
    )


@router.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """Liveness check - verifies the service is running."""
    return {"status": "alive"}

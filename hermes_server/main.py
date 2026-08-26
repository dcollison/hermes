# Standard
import time
from contextlib import asynccontextmanager

# Remote
import uvicorn
from fastapi import FastAPI

# Local
from . import __version__
from .config import settings
from .database import get_system_stats, init_db
from .http_client import close_http_client, init_http_client
from .routers import clients, notifications, webhooks

_start_time: float = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle tasks.

    :param app: FastAPI application instance.
    """
    global _start_time
    _start_time = time.time()
    await init_db()
    await init_http_client()
    try:
        yield
    finally:
        await close_http_client()


app = FastAPI(
    title="Hermes",
    description="Azure DevOps Webhook Notification Server",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(clients.router, prefix="/clients", tags=["clients"])
app.include_router(
    notifications.router,
    prefix="/notifications",
    tags=["notifications"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for the Hermes server.

    :returns: Dictionary confirming service operational status.
    """
    return {"status": "ok", "service": "Hermes", "version": __version__}


@app.get("/status")
async def server_status() -> dict:
    """Detailed operational status, metrics, and diagnostics.

    :returns: Dictionary with detailed operational diagnostics.
    """
    stats = await get_system_stats()
    uptime = time.time() - _start_time
    return {
        "status": "ok",
        "service": "Hermes",
        "version": __version__,
        "uptime_seconds": round(uptime, 2),
        "clients": stats,
        "ado_configured": bool(settings.ADO_ORGANIZATION_URL and settings.ADO_PAT),
        "webhook_secret_enabled": bool(settings.ADO_WEBHOOK_SECRET),
    }



if __name__ == "__main__":
    uvicorn.run(
        "hermes_server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info",
    )

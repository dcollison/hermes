"""
Hermes Server - Azure DevOps Webhook Receiver & Notification Dispatcher
"""

# Standard
from contextlib import asynccontextmanager

# Remote
import uvicorn
from fastapi import FastAPI

# Local
from .config import settings
from .database import init_db
from .routers import clients, notifications, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown."""
    await init_db()
    yield


app = FastAPI(
    title="Hermes",
    description="Azure DevOps Webhook Notification Server",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
app.include_router(clients.router, prefix="/clients", tags=["clients"])
app.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Hermes"}


if __name__ == "__main__":
    uvicorn.run(
        "server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info",
    )

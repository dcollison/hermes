# Standard
import logging

# Remote
import httpx

# Local
from .config import settings

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the shared httpx.AsyncClient instance, creating it if needed.

    :returns: Initialized httpx.AsyncClient instance.
    """
    global _client
    if _client is None or _client.is_closed:
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        _client = httpx.AsyncClient(
            limits=limits,
            timeout=10.0,
            verify=settings.ADO_SSL_VERIFY,
        )
    return _client


async def init_http_client() -> None:
    """Initialize the shared async HTTP client on application startup."""
    get_http_client()
    logger.debug("Initialized shared HTTP client connection pool")


async def close_http_client() -> None:
    """Close the shared async HTTP client and release connections."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        logger.debug("Closed shared HTTP client connection pool")

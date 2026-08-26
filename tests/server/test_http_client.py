# Remote
import httpx

from hermes_server.http_client import (
    close_http_client,
    get_http_client,
    init_http_client,
)


async def test_get_http_client_singleton():
    await close_http_client()
    client1 = get_http_client()
    client2 = get_http_client()
    assert client1 is client2
    assert not client1.is_closed
    await close_http_client()
    assert client1.is_closed


async def test_init_and_close_http_client():
    await init_http_client()
    client = get_http_client()
    assert isinstance(client, httpx.AsyncClient)
    await close_http_client()
    assert client.is_closed

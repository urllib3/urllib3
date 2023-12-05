from __future__ import annotations

import httpx
import trio
from starlette.requests import Request
from starlette.responses import Response


async def absolute_uri(request, scope, receive, send):
    async with httpx.AsyncClient() as client:
        response = await client.request(
            method=request.method,
            url=scope["path"],
            headers=request.headers,
            data=await request.body(),
        )
    headers = {}
    for header in (
        "Date",
        "Cache-Control",
        "Server",
        "Content-Type",
        "Location",
    ):
        v = response.headers.get(header)
        if v:
            headers[header] = v

    response = Response(
        content=response.content,
        status_code=response.status_code,
        headers=headers,
    )
    await response(scope, receive, send)


async def connect(scope, send):
    host, port = scope["path"].split(":")

    await send({"type": "http.response.start", "status": 200})
    await send({"type": "http.response.body", "body": b"", "more_body": True})

    async def start_forward(
        reader: trio.SocketStream, writer: trio.SocketStream
    ) -> None:
        while True:
            try:
                data = await reader.receive_some(4096)
            except trio.ClosedResourceError:
                break
            if not data:
                break
            await writer.send_all(data)
        await writer.aclose()

    upstream = await trio.open_tcp_stream(host, int(port))
    client: trio.SocketStream = scope["extensions"]["_transport"]

    async with trio.open_nursery(strict_exception_groups=True) as nursery:
        nursery.start_soon(start_forward, client, upstream)
        nursery.start_soon(start_forward, upstream, client)


async def proxy_app(scope, receive, send):
    assert scope["type"] == "http"
    request = Request(scope, receive)
    if request.method in ["GET", "POST"]:
        await absolute_uri(request, scope, receive, send)
    elif request.method == "CONNECT":
        await connect(scope, send)
    else:
        raise ValueError(request.method)

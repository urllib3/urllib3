#!/usr/bin/env python
#
# Simple asynchronous HTTP proxy with tunnelling (CONNECT).
#
# GET/POST proxying based on
# http://groups.google.com/group/python-tornado/msg/7bea08e7a049cf26
#
# Copyright (C) 2012 Senko Rasic <senko.rasic@dobarkod.hr>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from __future__ import annotations

import socket
import ssl
import sys

import tornado.gen
import tornado.httpclient
import tornado.httpserver
import tornado.ioloop
import tornado.iostream
import tornado.web

__all__ = ["ProxyHandler", "run_proxy"]


class ProxyHandler(tornado.web.RequestHandler):
    SUPPORTED_METHODS = ["GET", "POST", "CONNECT"]  # type: ignore[assignment]

    async def get(self) -> None:
        upstream_ca_certs = self.application.settings.get("upstream_ca_certs", None)
        ssl_options = None

        if upstream_ca_certs:
            ssl_options = ssl.create_default_context(cafile=upstream_ca_certs)

        assert self.request.uri is not None
        assert self.request.method is not None
        req = tornado.httpclient.HTTPRequest(
            url=self.request.uri,
            method=self.request.method,
            body=self.request.body,
            headers=self.request.headers,
            follow_redirects=False,
            allow_nonstandard_methods=True,
            ssl_options=ssl_options,
        )

        client = tornado.httpclient.AsyncHTTPClient()
        response = await client.fetch(req, raise_error=False)
        self.set_status(response.code)
        for header in (
            "Date",
            "Cache-Control",
            "Server",
            "Content-Type",
            "Location",
        ):
            v = response.headers.get(header)
            if v:
                self.set_header(header, v)
        if response.body:
            self.write(response.body)
        await self.finish()

    async def post(self) -> None:
        await self.get()

    async def connect(self) -> None:
        assert self.request.uri is not None
        host, port = self.request.uri.split(":")
        assert self.request.connection is not None
        client: tornado.iostream.IOStream = self.request.connection.stream  # type: ignore[attr-defined]

        async def start_forward(
            reader: tornado.iostream.IOStream, writer: tornado.iostream.IOStream
        ) -> None:
            while True:
                try:
                    data = await reader.read_bytes(4096, partial=True)
                except tornado.iostream.StreamClosedError:
                    break
                if not data:
                    break
                writer.write(data)
            writer.close()

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        upstream = tornado.iostream.IOStream(s)
        await upstream.connect((host, int(port)))

        client.write(b"HTTP/1.0 200 Connection established\r\n\r\n")
        fu1 = start_forward(client, upstream)
        fu2 = start_forward(upstream, client)
        await tornado.gen.multi([fu1, fu2])


def run_proxy(port: int, start_ioloop: bool = True) -> None:
    """
    Run proxy on the specified port. If start_ioloop is True (default),
    the tornado IOLoop will be started immediately.
    """
    app = tornado.web.Application([(r".*", ProxyHandler)])
    app.listen(port)
    ioloop = tornado.ioloop.IOLoop.instance()
    if start_ioloop:
        ioloop.start()


if __name__ == "__main__":
    port = 8888
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    print(f"Starting HTTP proxy on port {port}")
    run_proxy(port)

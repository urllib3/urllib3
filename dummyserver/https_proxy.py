#!/usr/bin/env python

from __future__ import annotations

import sys
import typing

import tornado.httpserver
import tornado.ioloop
import tornado.web

from dummyserver.proxy import ProxyHandler
from dummyserver.server import DEFAULT_CERTS, ssl_options_to_context


def run_proxy(port: int, certs: dict[str, typing.Any] = DEFAULT_CERTS) -> None:
    """
    Run proxy on the specified port using the provided certs.

    Example usage:

    python -m dummyserver.https_proxy

    You'll need to ensure you have access to certain packages such as trustme,
    tornado, urllib3.
    """
    upstream_ca_certs = certs.get("ca_certs")
    app = tornado.web.Application(
        [(r".*", ProxyHandler)], upstream_ca_certs=upstream_ca_certs
    )
    ssl_opts = ssl_options_to_context(**certs)
    http_server = tornado.httpserver.HTTPServer(app, ssl_options=ssl_opts)
    http_server.listen(port)

    ioloop = tornado.ioloop.IOLoop.instance()
    try:
        ioloop.start()
    except KeyboardInterrupt:
        ioloop.stop()


if __name__ == "__main__":
    port = 8443
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    print(f"Starting HTTPS proxy on port {port}")
    run_proxy(port)

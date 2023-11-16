from __future__ import annotations

import contextlib
import gzip
import zlib
from io import BytesIO

import quart
from quart_trio import QuartTrio

hypercorn_app = QuartTrio(__name__)


@hypercorn_app.route("/")
async def index() -> str:
    return "Dummy server!"


@hypercorn_app.route("/echo", methods=["GET", "POST"])
async def echo() -> quart.Response:
    "Echo back the params"
    if quart.request.method == "GET":
        return quart.request.query_string

    return await quart.request.get_data()


@hypercorn_app.route("/echo_json", methods=["POST"])
async def echo_json() -> quart.Response:
    "Echo back the JSON"
    data = await quart.request.get_data()
    return data, 200, quart.request.headers


@hypercorn_app.route("/echo_uri")
async def echo_uri() -> quart.Response:
    "Echo back the requested URI"
    assert quart.request.full_path is not None
    return quart.request.full_path


@hypercorn_app.route("/headers", methods=["GET", "POST"])
async def headers() -> quart.Response:
    return dict(quart.request.headers.items())


@hypercorn_app.route("/headers_and_params")
async def headers_and_params() -> quart.Response:
    return {"headers": dict(quart.request.headers), "params": quart.request.args}


@hypercorn_app.route("/multi_headers", methods=["GET", "POST"])
async def multi_headers() -> quart.Response:
    return {"headers": list(quart.request.headers)}


@hypercorn_app.route("/encodingrequest")
def encodingrequest() -> quart.Response:
    "Check for UA accepting gzip/deflate encoding"
    data = b"hello, world!"
    encoding = quart.request.headers.get("Accept-Encoding", "")
    headers = None
    if encoding == "gzip":
        headers = [("Content-Encoding", "gzip")]
        file_ = BytesIO()
        with contextlib.closing(gzip.GzipFile("", mode="w", fileobj=file_)) as zipfile:
            zipfile.write(data)
        data = file_.getvalue()
    elif encoding == "deflate":
        headers = [("Content-Encoding", "deflate")]
        data = zlib.compress(data)
    elif encoding == "garbage-gzip":
        headers = [("Content-Encoding", "gzip")]
        data = b"garbage"
    elif encoding == "garbage-deflate":
        headers = [("Content-Encoding", "deflate")]
        data = b"garbage"
    return data, 200, headers


@hypercorn_app.route("/redirect", methods=["GET", "POST"])
async def redirect() -> quart.Response:
    "Perform a redirect to ``target``"
    values = await quart.request.values
    target = values.get("target", "/")
    status = values.get("status", "303 See Other")
    status_code = status.split(" ")[0]

    headers = [("Location", target)]
    return "", status_code, headers


@hypercorn_app.route("/status")
async def status() -> quart.Response:
    values = await quart.request.values
    status = values.get("status", "200 OK")
    status_code = status.split(" ")[0]
    return "", status_code

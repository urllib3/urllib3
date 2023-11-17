from __future__ import annotations

import contextlib
import gzip
import zlib
from io import BytesIO

from quart import make_response, request
from quart.typing import ResponseTypes
from quart_trio import QuartTrio

hypercorn_app = QuartTrio(__name__)


@hypercorn_app.route("/")
async def index() -> ResponseTypes:
    return await make_response("Dummy server!")


@hypercorn_app.route("/echo", methods=["GET", "POST"])
async def echo() -> ResponseTypes:
    "Echo back the params"
    if request.method == "GET":
        return await make_response(request.query_string)

    return await make_response(await request.get_data())


@hypercorn_app.route("/echo_json", methods=["POST"])
async def echo_json() -> ResponseTypes:
    "Echo back the JSON"
    data = await request.get_data()
    return await make_response(data, 200, request.headers)


@hypercorn_app.route("/echo_uri")
async def echo_uri() -> ResponseTypes:
    "Echo back the requested URI"
    assert request.full_path is not None
    return await make_response(request.full_path)


@hypercorn_app.route("/headers", methods=["GET", "POST"])
async def headers() -> ResponseTypes:
    return await make_response(dict(request.headers.items()))


@hypercorn_app.route("/headers_and_params")
async def headers_and_params() -> ResponseTypes:
    return await make_response(
        {
            "headers": dict(request.headers),
            "params": request.args,
        }
    )


@hypercorn_app.route("/multi_headers", methods=["GET", "POST"])
async def multi_headers() -> ResponseTypes:
    return await make_response({"headers": list(request.headers)})


@hypercorn_app.route("/encodingrequest")
async def encodingrequest() -> ResponseTypes:
    "Check for UA accepting gzip/deflate encoding"
    data = b"hello, world!"
    encoding = request.headers.get("Accept-Encoding", "")
    headers = []
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
    return await make_response(data, 200, headers)


@hypercorn_app.route("/redirect", methods=["GET", "POST"])
async def redirect() -> ResponseTypes:
    "Perform a redirect to ``target``"
    values = await request.values
    target = values.get("target", "/")
    status = values.get("status", "303 See Other")
    status_code = status.split(" ")[0]

    headers = [("Location", target)]
    return await make_response("", status_code, headers)


@hypercorn_app.route("/status")
async def status() -> ResponseTypes:
    values = await request.values
    status = values.get("status", "200 OK")
    status_code = status.split(" ")[0]
    return await make_response("", status_code)

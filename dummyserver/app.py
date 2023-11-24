from __future__ import annotations

import collections
import contextlib
import gzip
import zlib
from io import BytesIO
from typing import Iterator

from quart import make_response, request

# TODO switch to Response if https://github.com/pallets/quart/issues/288 is fixed
from quart.typing import ResponseTypes
from quart_trio import QuartTrio

hypercorn_app = QuartTrio(__name__)

RETRY_TEST_NAMES = collections.Counter()


@hypercorn_app.route("/")
async def index() -> ResponseTypes:
    return await make_response("Dummy server!")


@hypercorn_app.route("/specific_method", methods=["GET", "POST", "PUT"])
async def specific_method() -> ResponseTypes:
    "Confirm that the request matches the desired method type"
    method_param = (await request.values).get("method")

    if request.method != method_param:
        return await make_response(
            f"Wrong method: {method_param} != {request.method}", 400
        )
    return await make_response()


@hypercorn_app.route("/upload", methods=["POST"])
async def upload() -> ResponseTypes:
    "Confirm that the uploaded file conforms to specification"
    params = await request.form
    param = params.get("upload_param")
    filename_param = params.get("upload_filename")
    size = int(params.get("upload_size", "0"))
    files_ = (await request.files).getlist(param)
    assert files_ is not None

    if len(files_) != 1:
        return await make_response(
            f"Expected 1 file for '{param}', not {len(files_)}", 400
        )

    file_ = files_[0]
    # data is short enough to read synchronously without blocking the event loop
    with contextlib.closing(file_.stream) as stream:
        data = stream.read()

    if int(size) != len(data):
        return await make_response(f"Wrong size: {int(size)} != {len(data)}", 400)

    if filename_param != file_.filename:
        return await make_response(
            f"Wrong filename: {filename_param} != {file_.filename}", 400
        )

    return await make_response()


@hypercorn_app.route("/chunked")
async def chunked() -> ResponseTypes:
    def generate() -> Iterator[str]:
        for _ in range(4):
            yield "123"

    return await make_response(generate())


@hypercorn_app.route("/chunked_gzip")
async def chunked_gzip() -> ResponseTypes:
    def generate() -> Iterator[bytes]:
        compressor = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)

        for uncompressed in [b"123"] * 4:
            yield compressor.compress(uncompressed)
        yield compressor.flush()

    return await make_response(generate(), 200, [("Content-Encoding", "gzip")])


@hypercorn_app.route("/keepalive")
async def keepalive() -> ResponseTypes:
    if request.args.get("close", b"0") == b"1":
        headers = [("Connection", "close")]
        return await make_response("Closing", 200, headers)

    headers = [("Connection", "keep-alive")]
    return await make_response("Keeping alive", 200, headers)


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


@hypercorn_app.route("/echo_uri/<path:rest>")
@hypercorn_app.route("/echo_uri", defaults={"rest": ""})
async def echo_uri(rest: str) -> ResponseTypes:
    "Echo back the requested URI"
    assert request.full_path is not None
    return await make_response(request.full_path)


@hypercorn_app.route("/echo_params")
async def echo_params() -> ResponseTypes:
    "Echo back the query parameters"
    await request.get_data()
    echod = sorted((k, v) for k, v in request.args.items())
    return await make_response(repr(echod))


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


@hypercorn_app.route("/multi_redirect")
async def multi_redirect() -> ResponseTypes:
    "Performs a redirect chain based on ``redirect_codes``"
    params = request.args
    codes = params.get("redirect_codes", "200")
    head, tail = codes.split(",", 1) if "," in codes else (codes, None)
    assert head is not None
    status = head
    if not tail:
        return await make_response("Done redirecting", status)

    headers = [("Location", f"/multi_redirect?redirect_codes={tail}")]
    return await make_response("", status, headers)


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


@hypercorn_app.route("/source_address")
async def source_address() -> ResponseTypes:
    """Return the requester's IP address."""
    return await make_response(request.remote_addr)


@hypercorn_app.route("/successful_retry")
async def successful_retry() -> ResponseTypes:
    """First return an error and then success

    It's not currently very flexible as the number of retries is hard-coded.
    """
    test_name = request.headers.get("test-name", None)
    if not test_name:
        return await make_response("test-name header not set", 400)

    RETRY_TEST_NAMES[test_name] += 1

    if RETRY_TEST_NAMES[test_name] >= 2:
        return await make_response("Retry successful!", 200)
    else:
        return await make_response("need to keep retrying!", 418)

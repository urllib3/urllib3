from __future__ import annotations

import collections
import contextlib
import gzip
import json
import logging
import sys
import typing
import zlib
from datetime import datetime, timedelta, timezone
from http.client import responses
from io import BytesIO
from urllib.parse import urlsplit

from tornado import httputil
from tornado.web import RequestHandler

from urllib3.util.util import to_str

log = logging.getLogger(__name__)


class Response:
    def __init__(
        self,
        body: str | bytes | typing.Sequence[str | bytes] = "",
        status: str = "200 OK",
        headers: typing.Sequence[tuple[str, str | bytes]] | None = None,
        json: typing.Any | None = None,
    ) -> None:
        self.body = body
        self.status = status
        if json is not None:
            self.headers = headers or [("Content-type", "application/json")]
            self.body = json
        else:
            self.headers = headers or [("Content-type", "text/plain")]

    def __call__(self, request_handler: RequestHandler) -> None:
        status, reason = self.status.split(" ", 1)
        request_handler.set_status(int(status), reason)
        for header, value in self.headers:
            request_handler.add_header(header, value)

        if isinstance(self.body, str):
            request_handler.write(self.body.encode())
        elif isinstance(self.body, bytes):
            request_handler.write(self.body)
        # chunked
        else:
            for item in self.body:
                if not isinstance(item, bytes):
                    item = item.encode("utf8")
                request_handler.write(item)
                request_handler.flush()


RETRY_TEST_NAMES: dict[str, int] = collections.defaultdict(int)


def request_params(request: httputil.HTTPServerRequest) -> dict[str, bytes]:
    params = {}
    for k, v in request.arguments.items():
        params[k] = next(iter(v))
    return params


class TestingApp(RequestHandler):
    """
    Simple app that performs various operations, useful for testing an HTTP
    library.

    Given any path, it will attempt to load a corresponding local method if
    it exists. Status code 200 indicates success, 400 indicates failure. Each
    method has its own conditions for success/failure.
    """

    def get(self) -> None:
        """Handle GET requests"""
        self._call_method()

    def post(self) -> None:
        """Handle POST requests"""
        self._call_method()

    def put(self) -> None:
        """Handle PUT requests"""
        self._call_method()

    def options(self) -> None:
        """Handle OPTIONS requests"""
        self._call_method()

    def head(self) -> None:
        """Handle HEAD requests"""
        self._call_method()

    def _call_method(self) -> None:
        """Call the correct method in this class based on the incoming URI"""
        req = self.request

        path = req.path[:]
        if not path.startswith("/"):
            path = urlsplit(path).path

        target = path[1:].split("/", 1)[0]
        method = getattr(self, target, self.index)

        resp = method(req)

        if dict(resp.headers).get("Connection") == "close":
            # FIXME: Can we kill the connection somehow?
            pass

        resp(self)

    def index(self, _request: httputil.HTTPServerRequest) -> Response:
        "Render simple message"
        return Response("Dummy server!")

    def certificate(self, request: httputil.HTTPServerRequest) -> Response:
        """Return the requester's certificate."""
        cert = request.get_ssl_certificate()
        assert isinstance(cert, dict)
        subject = {}
        if cert is not None:
            subject = {k: v for (k, v) in [y for z in cert["subject"] for y in z]}
        return Response(json.dumps(subject))

    def alpn_protocol(self, request: httputil.HTTPServerRequest) -> Response:
        """Return the selected ALPN protocol."""
        assert request.connection is not None
        proto = request.connection.stream.socket.selected_alpn_protocol()  # type: ignore[attr-defined]
        return Response(proto.encode("utf8") if proto is not None else "")

    def source_address(self, request: httputil.HTTPServerRequest) -> Response:
        """Return the requester's IP address."""
        return Response(request.remote_ip)  # type: ignore[arg-type]

    def set_up(self, request: httputil.HTTPServerRequest) -> Response:
        params = request_params(request)
        test_type = params.get("test_type")
        test_id = params.get("test_id")
        if test_id:
            print(f"\nNew test {test_type!r}: {test_id!r}")
        else:
            print(f"\nNew test {test_type!r}")
        return Response("Dummy server is ready!")

    def specific_method(self, request: httputil.HTTPServerRequest) -> Response:
        "Confirm that the request matches the desired method type"
        params = request_params(request)
        method = params.get("method")
        method_str = method.decode() if method else None

        if request.method != method_str:
            return Response(
                f"Wrong method: {method_str} != {request.method}",
                status="400 Bad Request",
            )
        return Response()

    def upload(self, request: httputil.HTTPServerRequest) -> Response:
        "Confirm that the uploaded file conforms to specification"
        params = request_params(request)
        # FIXME: This is a huge broken mess
        param = params.get("upload_param", b"myfile").decode("ascii")
        filename = params.get("upload_filename", b"").decode("utf-8")
        size = int(params.get("upload_size", "0"))
        files_ = request.files.get(param)
        assert files_ is not None

        if len(files_) != 1:
            return Response(
                f"Expected 1 file for '{param}', not {len(files_)}",
                status="400 Bad Request",
            )
        file_ = files_[0]

        data = file_["body"]
        if int(size) != len(data):
            return Response(
                f"Wrong size: {int(size)} != {len(data)}", status="400 Bad Request"
            )

        got_filename = file_["filename"]
        if isinstance(got_filename, bytes):
            got_filename = got_filename.decode("utf-8")

        # Tornado can leave the trailing \n in place on the filename.
        if filename != got_filename:
            return Response(
                f"Wrong filename: {filename} != {file_.filename}",
                status="400 Bad Request",
            )

        return Response()

    def redirect(self, request: httputil.HTTPServerRequest) -> Response:  # type: ignore[override]
        "Perform a redirect to ``target``"
        params = request_params(request)
        target = params.get("target", "/")
        status = params.get("status", b"303 See Other").decode("latin-1")
        if len(status) == 3:
            status = f"{status} Redirect"

        headers = [("Location", target)]
        return Response(status=status, headers=headers)

    def not_found(self, request: httputil.HTTPServerRequest) -> Response:
        return Response("Not found", status="404 Not Found")

    def multi_redirect(self, request: httputil.HTTPServerRequest) -> Response:
        "Performs a redirect chain based on ``redirect_codes``"
        params = request_params(request)
        codes = params.get("redirect_codes", b"200").decode("utf-8")
        head, tail = codes.split(",", 1) if "," in codes else (codes, None)
        assert head is not None
        status = f"{head} {responses[int(head)]}"
        if not tail:
            return Response("Done redirecting", status=status)

        headers = [("Location", f"/multi_redirect?redirect_codes={tail}")]
        return Response(status=status, headers=headers)

    def keepalive(self, request: httputil.HTTPServerRequest) -> Response:
        params = request_params(request)
        if params.get("close", b"0") == b"1":
            headers = [("Connection", "close")]
            return Response("Closing", headers=headers)

        headers = [("Connection", "keep-alive")]
        return Response("Keeping alive", headers=headers)

    def echo_params(self, request: httputil.HTTPServerRequest) -> Response:
        params = request_params(request)
        echod = sorted((to_str(k), to_str(v)) for k, v in params.items())
        return Response(repr(echod))

    def echo(self, request: httputil.HTTPServerRequest) -> Response:
        "Echo back the params"
        if request.method == "GET":
            return Response(request.query)

        return Response(request.body)

    def echo_json(self, request: httputil.HTTPServerRequest) -> Response:
        "Echo back the JSON"
        return Response(json=request.body, headers=list(request.headers.items()))

    def echo_uri(self, request: httputil.HTTPServerRequest) -> Response:
        "Echo back the requested URI"
        assert request.uri is not None
        return Response(request.uri)

    def encodingrequest(self, request: httputil.HTTPServerRequest) -> Response:
        "Check for UA accepting gzip/deflate encoding"
        data = b"hello, world!"
        encoding = request.headers.get("Accept-Encoding", "")
        headers = None
        if encoding == "gzip":
            headers = [("Content-Encoding", "gzip")]
            file_ = BytesIO()
            with contextlib.closing(
                gzip.GzipFile("", mode="w", fileobj=file_)
            ) as zipfile:
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
        return Response(data, headers=headers)

    def headers(self, request: httputil.HTTPServerRequest) -> Response:
        return Response(json.dumps(dict(request.headers)))

    def headers_and_params(self, request: httputil.HTTPServerRequest) -> Response:
        params = request_params(request)
        return Response(
            json.dumps({"headers": dict(request.headers), "params": params})
        )

    def multi_headers(self, request: httputil.HTTPServerRequest) -> Response:
        return Response(json.dumps({"headers": list(request.headers.get_all())}))

    def successful_retry(self, request: httputil.HTTPServerRequest) -> Response:
        """Handler which will return an error and then success

        It's not currently very flexible as the number of retries is hard-coded.
        """
        test_name = request.headers.get("test-name", None)
        if not test_name:
            return Response("test-name header not set", status="400 Bad Request")

        RETRY_TEST_NAMES[test_name] += 1

        if RETRY_TEST_NAMES[test_name] >= 2:
            return Response("Retry successful!")
        else:
            return Response("need to keep retrying!", status="418 I'm A Teapot")

    def chunked(self, request: httputil.HTTPServerRequest) -> Response:
        return Response(["123"] * 4)

    def chunked_gzip(self, request: httputil.HTTPServerRequest) -> Response:
        chunks = []
        compressor = zlib.compressobj(6, zlib.DEFLATED, 16 + zlib.MAX_WBITS)

        for uncompressed in [b"123"] * 4:
            chunks.append(compressor.compress(uncompressed))

        chunks.append(compressor.flush())

        return Response(chunks, headers=[("Content-Encoding", "gzip")])

    def nbytes(self, request: httputil.HTTPServerRequest) -> Response:
        params = request_params(request)
        length = int(params["length"])
        data = b"1" * length
        return Response(data, headers=[("Content-Type", "application/octet-stream")])

    def status(self, request: httputil.HTTPServerRequest) -> Response:
        params = request_params(request)
        status = params.get("status", b"200 OK").decode("latin-1")

        return Response(status=status)

    def retry_after(self, request: httputil.HTTPServerRequest) -> Response:
        params = request_params(request)
        if datetime.now() - self.application.last_req < timedelta(seconds=1):  # type: ignore[attr-defined]
            status = params.get("status", b"429 Too Many Requests")
            return Response(
                status=status.decode("utf-8"), headers=[("Retry-After", "1")]
            )

        self.application.last_req = datetime.now()  # type: ignore[attr-defined]

        return Response(status="200 OK")

    def redirect_after(self, request: httputil.HTTPServerRequest) -> Response:
        "Perform a redirect to ``target``"
        params = request_params(request)
        date = params.get("date")
        if date:
            retry_after = str(
                httputil.format_timestamp(
                    datetime.fromtimestamp(float(date), tz=timezone.utc)
                )
            )
        else:
            retry_after = "1"
        target = params.get("target", "/")
        headers = [("Location", target), ("Retry-After", retry_after)]
        return Response(status="303 See Other", headers=headers)

    def shutdown(self, request: httputil.HTTPServerRequest) -> typing.NoReturn:
        sys.exit()

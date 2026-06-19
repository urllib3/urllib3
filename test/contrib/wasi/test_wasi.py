from __future__ import annotations

import shutil
import socket

import pytest

from dummyserver.testcase import HypercornDummyServerTestCase, SocketDummyServerTestCase

from .runner import run_python_component

HAS_COMMANDS = (
    shutil.which("componentize-py") is not None and shutil.which("wasmtime") is not None
)


@pytest.mark.skipif(not HAS_COMMANDS, reason="required commands not found")
class TestWasi(HypercornDummyServerTestCase):

    def test_simple(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool
            with HTTPConnectionPool(
                "{self.host}",
                {self.port},
            ) as http_pool:
                r = http_pool.request("GET", "/")
                assert r.status == 200, r.data
                assert r.data == b"Dummy server!"
            """
        )

    def test_toplevel_request_import(self) -> None:
        run_python_component(
            f"""\
            import urllib3
            r = urllib3.request("GET", "http://{self.host}:{self.port}")
            assert r.status == 200, r.data
            assert r.data == b"Dummy server!"
            """
        )

    def test_connection_import(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connection import HTTPConnection
            conn = HTTPConnection("{self.host}", {self.port})
            conn.request("GET", "/")
            r = conn.getresponse()
            assert r.status == 200, r.data
            assert r.data == b"Dummy server!"
            """
        )

    def test_connectionpool_import(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnection
            conn = HTTPConnection("{self.host}", {self.port})
            conn.request("GET", "/")
            r = conn.getresponse()
            assert r.status == 200, r.data
            assert r.data == b"Dummy server!"
            """
        )

    def test_direct(self) -> None:
        run_python_component(
            f"""\
            from urllib3 import request
            r = request("GET", "http://{self.host}:{self.port}")
            assert r.status == 200, r.data
            assert r.data == b"Dummy server!"
        """
        )

    def test_specific_method(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool
            with HTTPConnectionPool(
                "{self.host}",
                {self.port},
            ) as http_pool:
                r = http_pool.request("PUT", "/specific_method?method=PUT")
                assert r.status == 200
                assert r.data == b""
            """
        )

    def test_chunked(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool
            with HTTPConnectionPool(
                "{self.host}",
                {self.port},
            ) as http_pool:
                r = http_pool.request("GET", "/chunked")
                assert r.status == 200
                assert r.data == b"123123123123"
            """
        )

    @pytest.mark.skip(reason="zlib is currently unsupported in wasi")
    def test_chunked_gzip(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool
            with HTTPConnectionPool(
                "{self.host}",
                {self.port},
            ) as http_pool:
                r = http_pool.request("GET", "/chunked_gzip", decode_content=True)
                assert r.status == 200
                assert r.data == b"123123123123"
            """
        )

    def test_echo_json(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool
            import json

            json_data = {{
                "Bears": "like",
                "to": {{"eat": "buns", "with": ["marmalade", "and custard"]}},
            }}
            with HTTPConnectionPool(
                "{self.host}",
                {self.port},
            ) as http_pool:
                r  = http_pool.request(
                    "POST",
                    "/echo_json",
                    body=json.dumps(json_data).encode("utf-8")
                )
                assert r.json() == json_data
            """
        )

    def test_headers(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool

            with HTTPConnectionPool(
                "{self.host}",
                {self.port},
            ) as http_pool:
                r = http_pool.request(
                    "GET",
                    "/headers",
                    headers={{"foo": "bar"}}
                )
                assert r.json()["Foo"] == "bar"
            """
        )

    def test_upload(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool
            data = "I'm in ur multipart form-data, hazing a cheezburgr"
            fields = {{
                "upload_param": "filefield",
                "upload_filename": "lolcat.txt",
                "filefield": ("lolcat.txt", data),
            }}
            fields["upload_size"] = len(data)  # type: ignore[assignment]

            with HTTPConnectionPool("{self.host}", {self.port}) as pool:
                r = pool.request("POST", "/upload", fields=fields)
                assert r.status == 200, r.data
            """
        )

    def test_unicode_upload(self) -> None:
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool

            fieldname = "myfile"
            filename = "\\xe2\\x99\\xa5.txt"
            data = "\\xe2\\x99\\xa5".encode()
            size = len(data)

            fields = {{
                "upload_param": fieldname,
                "upload_filename": filename,
                fieldname: (filename, data),
            }}
            fields["upload_size"] = size

            with HTTPConnectionPool(
                "{self.host}",
                {self.port},
            ) as http_pool:
                r = http_pool.request(
                    "POST",
                    "/upload",
                    fields=fields
                )
                assert r.status == 200, r.data
            """
        )


@pytest.mark.skipif(not HAS_COMMANDS, reason="required commands not found")
class TestWasiSocketServer(SocketDummyServerTestCase):
    def start_chunked_handler(self) -> None:
        self.buffer = b""

        def socket_handler(listener: socket.socket) -> None:
            sock = listener.accept()[0]

            while not self.buffer.endswith(b"\r\n0\r\n\r\n"):
                self.buffer += sock.recv(65536)

            sock.send(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-type: text/plain\r\n"
                b"Content-Length: 0\r\n"
                b"\r\n"
            )
            sock.close()

        self._start_server(socket_handler)

    def test_send_chunks(self) -> None:
        self.start_chunked_handler()
        run_python_component(
            f"""\
            from urllib3.connectionpool import HTTPConnectionPool
            with HTTPConnectionPool("{self.host}", {self.port}, retries=False) as pool:
                pool.urlopen("POST", "/", body=[b"foo", b"bar", b"", b"bazzzzzzzzzzzzzzzzzzzzzz"], headers=dict(DNT="1"))
        """
        )
        assert b"transfer-encoding" in self.buffer
        body = self.buffer.split(b"\r\n\r\n", 1)[1]
        lines = body.split(b"\r\n")
        assert lines == [
            b"3",
            b"foo",
            b"3",
            b"bar",
            b"18",
            b"bazzzzzzzzzzzzzzzzzzzzzz",
            b"0" b"",
            b"",
            b"",
        ]

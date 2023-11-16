from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import os
import textwrap
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from tornado import web

from tornado.httputil import HTTPServerRequest
from dummyserver.handlers import Response, TestingApp
from dummyserver.server import run_loop_in_thread, run_tornado_app
from dummyserver.testcase import HTTPDummyProxyTestCase

from typing import Generator,Any

@pytest.fixture(scope="module")
def testserver_http(request:pytest.FixtureRequest)->Generator[PyodideServerInfo,None,None]:
    dist_dir = Path(os.getcwd(), request.config.getoption("--dist-dir"))
    server = PyodideDummyServerTestCase
    server.setup_class(str(dist_dir))
    print(
        f"Server:{server.http_host}:{server.http_port},https({server.https_port}) [{dist_dir}]"
    )
    yield server
    print("Server teardown")
    server.teardown_class()


class ServerRunnerInfo:
    def __init__(self, host:str, port:int, selenium:Any)->None:
        self.host = host
        self.port = port
        self.selenium = selenium

    def run_webworker(self, code:str)->Any:
        if isinstance(code, str) and code.startswith("\n"):
            # we have a multiline string, fix indentation
            code = textwrap.dedent(code)

        return self.selenium.run_js(
            """
            let worker = new Worker('{}');
            let p = new Promise((res, rej) => {{
                worker.onmessageerror = e => rej(e);
                worker.onerror = e => rej(e);
                worker.onmessage = e => {{
                    if (e.data.results) {{
                       res(e.data.results);
                    }} else {{
                       rej(e.data.error);
                    }}
                }};
                worker.postMessage({{ python: {!r} }});
            }});
            return await p;
            """.format(
                f"https://{self.host}:{self.port}/pyodide/webworker_dev.js",
                code,
            ),
            pyodide_checks=False,
        )


# run pyodide on our test server instead of on the default
# pytest-pyodide one - this makes it so that
# we are at the same origin as web requests to server_host
@pytest.fixture()
def run_from_server(selenium:Any, testserver_http:PyodideServerInfo)->Generator[ServerRunnerInfo,None,None]:
    addr = f"https://{testserver_http.http_host}:{testserver_http.https_port}/pyodide/test.html"
    selenium.goto(addr)
    #    import time
    #    time.sleep(100)
    selenium.javascript_setup()
    selenium.load_pyodide()
    selenium.initialize_pyodide()
    selenium.save_state()
    selenium.restore_state()
    # install the wheel, which is served at /wheel/*
    selenium.run_js(
        """
await pyodide.loadPackage('/wheel/dist.whl')
"""
    )
    yield ServerRunnerInfo(
        testserver_http.http_host, testserver_http.https_port, selenium
    )


class PyodideTestingApp(TestingApp):
    pyodide_dist_dir: str = ""

    def set_default_headers(self) -> None:
        """Allow cross-origin requests for emscripten"""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Cross-Origin-Opener-Policy", "same-origin")
        self.set_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.add_header("Feature-Policy", "sync-xhr *;")

    def bigfile(self, req:HTTPServerRequest)->Response:
        print("Bigfile requested")
        # great big text file, should force streaming
        # if supported
        bigdata = 1048576 * b"WOOO YAY BOOYAKAH"
        return Response(bigdata)

    def pyodide(self, req:HTTPServerRequest)->Response:
        path = req.path[:]
        if not path.startswith("/"):
            path = urlsplit(path).path
        path_split = path.split("/")
        file_path = Path(PyodideTestingApp.pyodide_dist_dir, *path_split[2:])
        if file_path.exists():
            mime_type, encoding = mimetypes.guess_type(file_path)
            print(file_path, mime_type)
            if not mime_type:
                mime_type = "text/plain"
            self.set_header("Content-Type", mime_type)
            return Response(
                body=file_path.read_bytes(),
                headers=[("Access-Control-Allow-Origin", "*")],
            )
        else:
            return Response(status="404 NOT FOUND")

    def wheel(self, _req:HTTPServerRequest)->Response:
        # serve our wheel
        wheel_folder = Path(__file__).parent.parent.parent.parent / "dist"
        print(wheel_folder)
        wheels = list(wheel_folder.glob("*.whl"))
        print(wheels)
        if len(wheels) > 0:
            resp = Response(
                body=wheels[0].read_bytes(),
                headers=[
                    ("Content-Disposition", f"inline; filename='{wheels[0].name}'")
                ],
            )
            return resp
        else:
            return Response(status="404 NOT FOUND")


class PyodideDummyServerTestCase(HTTPDummyProxyTestCase):
    @classmethod
    def setup_class(cls, pyodide_dist_dir:str) -> None: # type:ignore[override]
        PyodideTestingApp.pyodide_dist_dir = pyodide_dist_dir
        with contextlib.ExitStack() as stack:
            io_loop = stack.enter_context(run_loop_in_thread())

            async def run_app() -> None:
                app = web.Application([(r".*", PyodideTestingApp)])
                cls.http_server, cls.http_port = run_tornado_app(
                    app, None, "http", cls.http_host
                )

                app = web.Application([(r".*", PyodideTestingApp)])
                cls.https_server, cls.https_port = run_tornado_app(
                    app, cls.https_certs, "https", cls.http_host
                )

            asyncio.run_coroutine_threadsafe(run_app(), io_loop.asyncio_loop).result()  # type: ignore[attr-defined]
            cls._stack = stack.pop_all()

PyodideServerInfo=type[PyodideDummyServerTestCase]
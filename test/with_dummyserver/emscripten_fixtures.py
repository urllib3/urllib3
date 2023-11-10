import asyncio
import contextlib
import os

from urllib.parse import urlsplit
import textwrap
import mimetypes
import pytest
from tornado import web
from dummyserver.server import (
    run_loop_in_thread,
    run_tornado_app,
)

from pathlib import Path
from dummyserver.handlers import TestingApp
from dummyserver.handlers import Response
from dummyserver.testcase import HTTPDummyProxyTestCase


@pytest.fixture(scope="module")
def testserver_http(request):
    dist_dir = Path(os.getcwd(), request.config.getoption("--dist-dir"))
    server = PyodideDummyServerTestCase
    server.setup_class(dist_dir)
    print(
        f"Server:{server.http_host}:{server.http_port},https({server.https_port}) [{dist_dir}]"
    )
    yield server
    print("Server teardown")
    server.teardown_class()


class _FromServerRunner:
    def __init__(self, host, port, selenium):
        self.host = host
        self.port = port
        self.selenium = selenium

    def run_webworker(self, code):
        if isinstance(code, str) and code.startswith("\n"):
            # we have a multiline string, fix indentation
            code = textwrap.dedent(code)

        return self.selenium.run_js(
            """
            let worker = new Worker('{}');
            let p = new Promise((res, rej) => {{
                worker.onerror = e => res(e);
                worker.onmessage = e => {{
                    if (e.data.results) {{
                       res(e.data.results);
                    }} else {{
                       res(e.data.error);
                    }}
                }};
                worker.postMessage({{ python: {!r} }});
            }});
            return await p
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
def run_from_server(selenium, testserver_http):
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
    yield _FromServerRunner(
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

    def bigfile(self,req):
        print("Bigfile requested")
        return Response(b"WOOO YAY BOOYAKAH")

    def pyodide(self, req):
        path = req.path[:]
        if not path.startswith("/"):
            path = urlsplit(path).path
        path = path.split("/")
        file_path = Path(PyodideTestingApp.pyodide_dist_dir, *path[2:])
        if file_path.exists():
            mime_type, encoding = mimetypes.guess_type(file_path)
            print(file_path,mime_type)
            if not mime_type:
                mime_type = "text/plain"
            self.set_header("Content-Type",mime_type)
            return Response(
                body=file_path.read_bytes(), headers=[("Access-Control-Allow-Origin", "*")]
            )
        else:
            return Response(status=404)

    def wheel(self, req):
        # serve our wheel
        wheel_folder = Path(__file__).parent.parent.parent / "dist"
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


class PyodideDummyServerTestCase(HTTPDummyProxyTestCase):
    @classmethod
    def setup_class(cls, pyodide_dist_dir) -> None:
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

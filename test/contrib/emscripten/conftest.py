from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import os
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator
from urllib.parse import urlsplit

import pytest
from tornado import web
from tornado.httputil import HTTPServerRequest

from dummyserver.handlers import Response, TestingApp
from dummyserver.testcase import HTTPDummyProxyTestCase
from dummyserver.tornadoserver import run_tornado_app, run_tornado_loop_in_thread

_coverage_count = 0


def _get_coverage_filename(prefix: str) -> str:
    global _coverage_count
    _coverage_count += 1
    rand_part = "".join([random.choice("1234567890") for x in range(20)])
    return prefix + rand_part + f".{_coverage_count}"


@pytest.fixture(scope="module")
def testserver_http(
    request: pytest.FixtureRequest,
) -> Generator[PyodideServerInfo, None, None]:
    dist_dir = Path(os.getcwd(), request.config.getoption("--dist-dir"))
    server = PyodideDummyServerTestCase
    server.setup_class(str(dist_dir))
    print(
        f"Server:{server.http_host}:{server.http_port},https({server.https_port}) [{dist_dir}]"
    )
    yield PyodideServerInfo(
        http_host=server.http_host,
        http_port=server.http_port,
        https_port=server.https_port,
    )
    print("Server teardown")
    server.teardown_class()


@pytest.fixture()
def selenium_coverage(selenium: Any) -> Generator[Any, None, None]:
    def _install_coverage(self: Any) -> None:
        self.run_js(
            """
            await pyodide.loadPackage("coverage")
            await pyodide.runPythonAsync(`import coverage
_coverage= coverage.Coverage(source_pkgs=['urllib3'])
_coverage.start()
        `
        )"""
        )

    setattr(
        selenium,
        "_install_coverage",
        _install_coverage.__get__(selenium, selenium.__class__),
    )
    selenium._install_coverage()
    yield selenium
    # on teardown, save _coverage output
    coverage_out = selenium.run_js(
        """
return await pyodide.runPythonAsync(`
_coverage.stop()
_coverage.save()
datafile=open(".coverage","rb")
datafile.read()
`)
    """
    )
    coverage_out_binary = bytes(coverage_out)
    with open(f"{_get_coverage_filename('.coverage.emscripten.')}", "wb") as outfile:
        outfile.write(coverage_out_binary)


class ServerRunnerInfo:
    def __init__(self, host: str, port: int, selenium: Any) -> None:
        self.host = host
        self.port = port
        self.selenium = selenium

    def run_webworker(self, code: str) -> Any:
        if isinstance(code, str) and code.startswith("\n"):
            # we have a multiline string, fix indentation
            code = textwrap.dedent(code)
            # add coverage collection to this code
            code = (
                textwrap.dedent(
                    """
            import coverage
            _coverage= coverage.Coverage(source_pkgs=['urllib3'])
            _coverage.start()
            """
                )
                + code
            )
            code += textwrap.dedent(
                """
            _coverage.stop()
            _coverage.save()
            datafile=open(".coverage","rb")
            str(list(datafile.read()))
            """
            )

        coverage_out = self.selenium.run_js(
            f"""
            let worker = new Worker('https://{self.host}:{self.port}/pyodide/webworker_dev.js');
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
                worker.postMessage({{ python: {repr(code)} }});
            }});
            return await p;
            """,
            pyodide_checks=False,
        )
        coverage_out = eval(coverage_out)
        coverage_out_binary = bytes(coverage_out)
        with open(
            f"{_get_coverage_filename('.coverage.emscripten.worker.')}", "wb"
        ) as outfile:
            outfile.write(coverage_out_binary)


# run pyodide on our test server instead of on the default
# pytest-pyodide one - this makes it so that
# we are at the same origin as web requests to server_host
@pytest.fixture()
def run_from_server(
    selenium_coverage: Any, testserver_http: PyodideServerInfo
) -> Generator[ServerRunnerInfo, None, None]:
    addr = f"https://{testserver_http.http_host}:{testserver_http.https_port}/pyodide/test.html"
    selenium_coverage.goto(addr)
    selenium_coverage.javascript_setup()
    selenium_coverage.load_pyodide()
    selenium_coverage.initialize_pyodide()
    selenium_coverage.save_state()
    selenium_coverage.restore_state()
    # install the wheel, which is served at /wheel/*
    selenium_coverage.run_js(
        """
await pyodide.loadPackage('/wheel/dist.whl')
"""
    )
    selenium_coverage._install_coverage()
    yield ServerRunnerInfo(
        testserver_http.http_host, testserver_http.https_port, selenium_coverage
    )


class PyodideTestingApp(TestingApp):
    pyodide_dist_dir: str = ""

    def set_default_headers(self) -> None:
        """Allow cross-origin requests for emscripten"""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Cross-Origin-Opener-Policy", "same-origin")
        self.set_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.add_header("Feature-Policy", "sync-xhr *;")
        self.add_header("Access-Control-Allow-Headers", "*")

    def slow(self, _req: HTTPServerRequest) -> Response:
        import time

        time.sleep(10)
        return Response("TEN SECONDS LATER")

    def bigfile(self, req: HTTPServerRequest) -> Response:
        # great big text file, should force streaming
        # if supported
        bigdata = 1048576 * b"WOOO YAY BOOYAKAH"
        return Response(bigdata)

    def pyodide(self, req: HTTPServerRequest) -> Response:
        path = req.path[:]
        if not path.startswith("/"):
            path = urlsplit(path).path
        path_split = path.split("/")
        file_path = Path(PyodideTestingApp.pyodide_dist_dir, *path_split[2:])
        if file_path.exists():
            mime_type, encoding = mimetypes.guess_type(file_path)
            if not mime_type:
                mime_type = "text/plain"
            self.set_header("Content-Type", mime_type)
            return Response(
                body=file_path.read_bytes(),
                headers=[("Access-Control-Allow-Origin", "*")],
            )
        else:
            return Response(status="404 NOT FOUND")

    def wheel(self, _req: HTTPServerRequest) -> Response:
        # serve our wheel
        wheel_folder = Path(__file__).parent.parent.parent.parent / "dist"
        wheels = list(wheel_folder.glob("*.whl"))
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
    def setup_class(cls, pyodide_dist_dir: str) -> None:  # type:ignore[override]
        PyodideTestingApp.pyodide_dist_dir = pyodide_dist_dir
        with contextlib.ExitStack() as stack:
            io_loop = stack.enter_context(run_tornado_loop_in_thread())

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


@dataclass
class PyodideServerInfo:
    http_port: int
    https_port: int
    http_host: str

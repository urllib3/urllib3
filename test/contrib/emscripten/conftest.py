from __future__ import annotations

import contextlib
import mimetypes
import os
import random
import textwrap
import typing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

import hypercorn
import pytest
import trio
from quart import make_response, request

# TODO switch to Response if https://github.com/pallets/quart/issues/288 is fixed
from quart.typing import ResponseTypes
from quart_trio import QuartTrio

from dummyserver.hypercornserver import run_hypercorn_in_thread
from dummyserver.tornadoserver import DEFAULT_CERTS
from urllib3.util.url import parse_url

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
    pyodide_dist_dir = Path(os.getcwd(), request.config.getoption("--dist-dir"))
    pyodide_testing_app.config["config.pyodide_dist_dir"] = str(pyodide_dist_dir)
    http_host = "localhost"
    with contextlib.ExitStack() as stack:
        http_server_config = hypercorn.Config()
        http_server_config.bind = [f"{http_host}:0"]
        stack.enter_context(
            run_hypercorn_in_thread(http_server_config, pyodide_testing_app)
        )
        http_port = typing.cast(int, parse_url(http_server_config.bind[0]).port)

        https_server_config = hypercorn.Config()
        https_server_config.accesslog = "/tmp/https_access.txt"
        https_server_config.errorlog = "/tmp/https_error.txt"
        https_server_config.certfile = DEFAULT_CERTS["certfile"]
        https_server_config.keyfile = DEFAULT_CERTS["keyfile"]
        https_server_config.verify_mode = DEFAULT_CERTS["cert_reqs"]
        https_server_config.ca_certs = DEFAULT_CERTS["ca_certs"]
        https_server_config.alpn_protocols = DEFAULT_CERTS["alpn_protocols"]
        https_server_config.bind = [f"{http_host}:0"]
        stack.enter_context(
            run_hypercorn_in_thread(https_server_config, pyodide_testing_app)
        )
        https_port = typing.cast(int, parse_url(https_server_config.bind[0]).port)

        yield PyodideServerInfo(
            http_host=http_host,
            http_port=http_port,
            https_port=https_port,
        )
        print("Server teardown")


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
    coverage_out_binary = bytes(
        selenium.run_js(
            """
return await pyodide.runPythonAsync(`
_coverage.stop()
_coverage.save()
_coverage_datafile = open(".coverage","rb")
_coverage_outdata = _coverage_datafile.read()
# avoid polluting main namespace too much
import js as _coverage_js
# convert to js Array (as default conversion is TypedArray which does
# bad things in firefox)
_coverage_js.Array.from_(_coverage_outdata)
`)
    """
        )
    )
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
            _coverage_datafile = open(".coverage","rb")
            _coverage_outdata = _coverage_datafile.read()
            # avoid polluting main namespace too much
            import js as _coverage_js
            # convert to js Array (as default conversion is TypedArray which does
            # bad things in firefox)
            _coverage_js.Array.from_(_coverage_outdata)
            """
            )

        coverage_out_binary = bytes(
            self.selenium.run_js(
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
        )
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


pyodide_testing_app = QuartTrio(__name__)
DEFAULT_HEADERS = [
    # Allow cross-origin requests for emscripten
    ("Access-Control-Allow-Origin", "*"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Embedder-Policy", "require-corp"),
    ("Feature-Policy", "sync-xhr *;"),
    ("Access-Control-Allow-Headers", "*"),
]


@pyodide_testing_app.route("/")
@pyodide_testing_app.route("/index")
async def pyodide_index() -> ResponseTypes:
    return await make_response("Dummy server!", 200, DEFAULT_HEADERS)


@pyodide_testing_app.route("/status")
async def status() -> ResponseTypes:
    values = await request.values
    status = values.get("status", "200 OK")
    status_code = status.split(" ")[0]
    return await make_response("", status_code)


@pyodide_testing_app.route("/slow")
async def slow() -> ResponseTypes:
    await trio.sleep(10)
    return await make_response("TEN SECONDS LATER", 200, DEFAULT_HEADERS)


@pyodide_testing_app.route("/bigfile")
async def bigfile() -> ResponseTypes:
    # great big text file, should force streaming
    # if supported
    bigdata = 1048576 * b"WOOO YAY BOOYAKAH"
    return await make_response(bigdata, 200, DEFAULT_HEADERS)


@pyodide_testing_app.route("/mediumfile")
async def mediumfile() -> ResponseTypes:
    # quite big file
    bigdata = 1024 * b"WOOO YAY BOOYAKAH"
    return await make_response(bigdata, 200, DEFAULT_HEADERS)


@pyodide_testing_app.route("/pyodide/<path:path>")
async def pyodide(path: str) -> ResponseTypes:
    file_path = Path(pyodide_testing_app.config["pyodide_dist_dir"], path)
    if file_path.exists():
        mime_type, encoding = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "text/plain"
        return await make_response(
            file_path.read_bytes(),
            200,
            DEFAULT_HEADERS + [("Content-Type", mime_type)],
        )
    else:
        return await make_response("", 404, DEFAULT_HEADERS)


@pyodide_testing_app.route("/wheel/dist.whl")
async def wheel() -> ResponseTypes:
    # serve our wheel
    wheel_folder = Path(__file__).parent.parent / "dist"
    wheels = list(wheel_folder.glob("*.whl"))
    if len(wheels) > 0:
        wheel = wheels[0]
        headers = DEFAULT_HEADERS + [
            ("Content-Disposition", f"inline; filename='{wheel.name}'")
        ]
        resp = await make_response(wheel.read_bytes(), 200, headers)
        return resp
    else:
        return await make_response("", 404, DEFAULT_HEADERS)


@dataclass
class PyodideServerInfo:
    http_port: int
    https_port: int
    http_host: str

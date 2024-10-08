from __future__ import annotations

import contextlib
import os
import random
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

import pytest

from dummyserver.app import pyodide_testing_app
from dummyserver.hypercornserver import run_hypercorn_in_thread
from dummyserver.socketserver import DEFAULT_CERTS

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
    pyodide_testing_app.config["pyodide_dist_dir"] = str(pyodide_dist_dir)
    http_host = "localhost"
    with contextlib.ExitStack() as stack:
        http_port = stack.enter_context(
            run_hypercorn_in_thread(http_host, None, pyodide_testing_app)
        )
        https_port = stack.enter_context(
            run_hypercorn_in_thread(http_host, DEFAULT_CERTS, pyodide_testing_app)
        )

        yield PyodideServerInfo(
            http_host=http_host,
            http_port=http_port,
            https_port=https_port,
            pyodide_dist_dir=pyodide_dist_dir,
        )
        print("Server teardown")


@dataclass
class PyodideServerInfo:
    http_port: int
    https_port: int
    http_host: str
    pyodide_dist_dir: Path


@pytest.fixture()
def selenium_with_jspi_if_possible(
    request: pytest.FixtureRequest, runtime: str
) -> Generator[Any, None, None]:
    if runtime.startswith("firefox"):
        fixture_name = "selenium"
        with_jspi = False
    else:
        fixture_name = "selenium_jspi"
        with_jspi = True
    selenium_obj = request.getfixturevalue(fixture_name)
    selenium_obj.with_jspi = with_jspi
    yield selenium_obj


@pytest.fixture()
def selenium_coverage(
    selenium_with_jspi_if_possible: Any, testserver_http: PyodideServerInfo
) -> Generator[Any, None, None]:
    def enable_jspi(self: Any, jspi: bool) -> None:
        if jspi is False and selenium_with_jspi_if_possible.with_jspi:
            code = f"""
                    import urllib3.contrib.emscripten.fetch
                    urllib3.contrib.emscripten.fetch.has_jspi = lambda : {jspi}"""
            self.run(code)

    def _install_packages(self: Any) -> None:
        if self.browser == "node":
            # stop Node.js checking our https certificates
            self.run_js('process.env["NODE_TLS_REJECT_UNAUTHORIZED"] = 0;')
        # install urllib3 from our test server, rather than from existing package
        self.run_js(
            f'await pyodide.loadPackage("http://{testserver_http.http_host}:{testserver_http.http_port}/dist/urllib3.whl")'
        )
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
        selenium_with_jspi_if_possible,
        "_install_packages",
        _install_packages.__get__(
            selenium_with_jspi_if_possible, selenium_with_jspi_if_possible.__class__
        ),
    )

    setattr(
        selenium_with_jspi_if_possible,
        "enable_jspi",
        enable_jspi.__get__(
            selenium_with_jspi_if_possible, selenium_with_jspi_if_possible.__class__
        ),
    )

    selenium_with_jspi_if_possible._install_packages()
    yield selenium_with_jspi_if_possible
    # on teardown, save _coverage output
    coverage_out_binary = bytes(
        selenium_with_jspi_if_possible.run_js(
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
    def __init__(self, host: str, port: int, selenium: Any, dist_dir: Path) -> None:
        self.host = host
        self.port = port
        self.selenium = selenium
        self.dist_dir = dist_dir

    def run_webworker(self, code: str, *, has_jspi: bool = True) -> Any:
        if isinstance(code, str) and code.startswith("\n"):
            # we have a multiline string, fix indentation
            code = textwrap.dedent(code)
        # make sure any import of urllib comes from our package
        code = (
            textwrap.dedent(
                f"""
                import pyodide_js as _pjs
                await _pjs.loadPackage('https://{self.host}:{self.port}/dist/urllib3.whl')
                """
            )
            + code
        )

        if has_jspi is False:
            # disable jspi in this code
            code = (
                textwrap.dedent(
                    """
                import urllib3.contrib.emscripten.fetch
                urllib3.contrib.emscripten.fetch.has_jspi = lambda : False
                """
                )
                + code
            )
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
        if self.selenium.browser == "firefox":
            # running in worker is SLOW on firefox
            self.selenium.set_script_timeout(30)
        if self.selenium.browser == "node":
            worker_path = str(self.dist_dir / "webworker_dev.js")
            self.selenium.run_js(
                f"""const {{
                    Worker, isMainThread, parentPort, workerData,
                }} = require('node:worker_threads');
                globalThis.Worker= Worker;
                process.chdir('{self.dist_dir}');
                """
            )
        else:
            worker_path = f"https://{self.host}:{self.port}/pyodide/webworker_dev.js"
        coverage_out_binary = bytes(
            self.selenium.run_js(
                f"""
            let worker = new Worker('{worker_path}');
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
    if selenium_coverage.browser != "node":
        # on node, we don't need to be on the same origin
        # so we can ignore all this
        addr = f"https://{testserver_http.http_host}:{testserver_http.https_port}/pyodide/test.html"
        selenium_coverage.goto(addr)
        selenium_coverage.javascript_setup()
        selenium_coverage.load_pyodide()
        selenium_coverage.initialize_pyodide()
        selenium_coverage.save_state()
        selenium_coverage.restore_state()
        selenium_coverage._install_packages()
    dist_dir = testserver_http.pyodide_dist_dir
    yield ServerRunnerInfo(
        testserver_http.http_host,
        testserver_http.https_port,
        selenium_coverage,
        dist_dir,
    )


def pytest_configure(config: pytest.Config) -> None:
    # register an additional marker
    config.addinivalue_line(
        "markers",
        "in_webbrowser: mark test to run only in browser (not in Node.js)",
    )
    config.addinivalue_line(
        "markers",
        "with_jspi: mark test to run only if WebAssembly JavaScript Promise Integration is supported",
    )
    config.addinivalue_line(
        "markers",
        "without_jspi: mark test to run only if this platform works without  WebAssembly JavaScript Promise Integration",
    )
    config.addinivalue_line(
        "markers",
        "webworkers: mark test to run only if this platform can test web workers",
    )


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Configure various markers to mark tests which use behaviour which is
    browser / Node.js specific."""
    if item.get_closest_marker("without_jspi"):
        if item.config.getoption("--runtime").startswith("node"):
            pytest.skip("Node.js doesn't support non jspi tests")

    if item.get_closest_marker("with_jspi"):
        if item.config.getoption("--runtime").startswith("firefox"):
            pytest.skip("Firefox doesn't support jspi tests")

    if item.get_closest_marker("in_webbrowser"):
        if item.config.getoption("--runtime").startswith("node"):
            pytest.skip("Skipping web browser test in Node.js")

    if item.get_closest_marker("webworkers"):
        if item.config.getoption("--runtime").startswith("node"):
            pytest.skip("Skipping webworker test in Node.js")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Generate WebAssembly JavaScript Promise Integration based tests
    only for platforms that support it.

    Currently:
    1) Node.js only supports use of JSPI because it doesn't support
    synchronous XMLHttpRequest

    2) firefox doesn't support JSPI

    3) Chrome supports JSPI on or off.
    """
    if "has_jspi" in metafunc.fixturenames:
        if metafunc.config.getoption("--runtime").startswith("node"):
            metafunc.parametrize("has_jspi", [True])
        elif metafunc.config.getoption("--runtime").startswith("firefox"):
            metafunc.parametrize("has_jspi", [False])
        else:
            metafunc.parametrize("has_jspi", [True, False])

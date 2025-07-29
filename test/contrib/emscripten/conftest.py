from __future__ import annotations

import contextlib
import os
import random
import textwrap
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
) -> Generator[PyodideServerInfo]:
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


def _get_coverage_code() -> tuple[str, str]:
    begin = textwrap.dedent(
        """
        import coverage

        _coverage = coverage.Coverage(source_pkgs=["urllib3"])
        _coverage.start()
        """
    )
    end = textwrap.dedent(
        """
        _coverage.stop()
        _coverage.save()

        _coverage_datafile = open(".coverage", "rb")
        _coverage_outdata = _coverage_datafile.read()
        _coverage_datafile.close()

        # avoid polluting main namespace too much
        import js as _coverage_js
        # convert to js Array (as default conversion is TypedArray which does
        # bad things in firefox)
        _coverage_js.Array.from_(_coverage_outdata)
        """
    )
    return begin, end


def _get_jspi_monkeypatch_code(runtime: str, prefer_jspi: bool) -> tuple[str, str]:
    """
    Return code to make Pyodide think JSPI is disabled in Chrome when a
    test needs this to check some code paths.
    """
    if runtime != "chrome" or prefer_jspi:
        return "", ""
    monkeypatch_code = textwrap.dedent(
        """
        import pyodide.ffi

        original_can_run_sync = pyodide.ffi.can_run_sync
        if pyodide.ffi.can_run_sync():
            pyodide.ffi.can_run_sync = lambda: False
        """
    )
    unmonkeypatch_code = "pyodide.ffi.can_run_sync = original_can_run_sync"
    return monkeypatch_code, unmonkeypatch_code


@pytest.fixture()
def selenium_with_jspi_if_possible(
    request: pytest.FixtureRequest, runtime: str, prefer_jspi: bool
) -> Generator[Any]:
    if runtime == "node" and prefer_jspi:
        fixture_name = "selenium_jspi"
    else:
        fixture_name = "selenium"
    selenium_obj = request.getfixturevalue(fixture_name)

    jspi_monkeypatch_code, jspi_unmonkeypatch_code = _get_jspi_monkeypatch_code(
        runtime, prefer_jspi
    )
    if jspi_monkeypatch_code:
        selenium_obj.run_async(jspi_monkeypatch_code)

    yield selenium_obj

    if jspi_unmonkeypatch_code:
        selenium_obj.run_async(jspi_unmonkeypatch_code)


@pytest.fixture()
def selenium_coverage(
    selenium_with_jspi_if_possible: Any, testserver_http: PyodideServerInfo
) -> Generator[Any]:
    def _install_packages(self: Any) -> None:
        if self.browser == "node":
            # stop Node.js checking our https certificates
            self.run_js('process.env["NODE_TLS_REJECT_UNAUTHORIZED"] = 0;')
        # install urllib3 from our test server, rather than from existing package
        result = self.run_js(
            f'await pyodide.loadPackage("http://{testserver_http.http_host}:{testserver_http.http_port}/dist/urllib3.whl")'
        )
        print("Installed package:", result)
        self.run_js("await pyodide.loadPackage('coverage')")

    setattr(
        selenium_with_jspi_if_possible,
        "_install_packages",
        _install_packages.__get__(
            selenium_with_jspi_if_possible, selenium_with_jspi_if_possible.__class__
        ),
    )

    selenium_with_jspi_if_possible._install_packages()

    coverage_begin, coverage_end = _get_coverage_code()
    selenium_with_jspi_if_possible.run_js(
        f"await pyodide.runPythonAsync(`{coverage_begin}`)"
    )

    yield selenium_with_jspi_if_possible

    # on teardown, save _coverage output
    coverage_out_binary = bytes(
        selenium_with_jspi_if_possible.run_js(
            f"return await pyodide.runPythonAsync(`{coverage_end}`)"
        )
    )
    with open(f"{_get_coverage_filename('.coverage.emscripten.')}", "wb") as outfile:
        outfile.write(coverage_out_binary)


class ServerRunnerInfo:
    def __init__(
        self, host: str, port: int, selenium: Any, dist_dir: Path, prefer_jspi: bool
    ) -> None:
        self.host = host
        self.port = port
        self.selenium = selenium
        self.dist_dir = dist_dir
        self.prefer_jspi = prefer_jspi

    def run_webworker(self, code: str) -> Any:
        if isinstance(code, str) and code.startswith("\n"):
            # we have a multiline string, fix indentation
            code = textwrap.dedent(code)

        coverage_init_code, coverage_end_code = _get_coverage_code()
        jspi_monkeypatch_code, jspi_unmonkeypatch_code = _get_jspi_monkeypatch_code(
            self.selenium.browser, self.prefer_jspi
        )

        # the ordering of these code blocks is important - makes sure
        # that the first thing that happens is our wheel is loaded
        code = (
            coverage_init_code
            + "\n"
            + jspi_monkeypatch_code
            + "\n"
            + code
            + "\n"
            + jspi_unmonkeypatch_code
            + "\n"
            + coverage_end_code
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
    selenium: Any, testserver_http: PyodideServerInfo, prefer_jspi: bool
) -> Generator[ServerRunnerInfo]:
    if selenium.browser != "node":
        # on node, we don't need to be on the same origin
        # so we can ignore all this
        addr = f"https://{testserver_http.http_host}:{testserver_http.https_port}/pyodide/test.html"
        selenium.goto(addr)
        selenium.javascript_setup()
        selenium.load_pyodide()
        selenium.initialize_pyodide()
        selenium.save_state()
        selenium.restore_state()
    dist_dir = testserver_http.pyodide_dist_dir
    yield ServerRunnerInfo(
        testserver_http.http_host,
        testserver_http.https_port,
        selenium,
        dist_dir,
        prefer_jspi,
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """
    A pytest hook modifying collected test items for Emscripten.
    """
    selected_tests = []
    deselected_tests = []

    runtime = config.getoption("--runtime", default=None)
    if not runtime:
        return

    for item in items:
        # Deselect tests which Node.js cannot run.
        if runtime.startswith("node"):
            if (
                item.get_closest_marker("webworkers")
                or item.get_closest_marker("in_webbrowser")
                or item.get_closest_marker("without_jspi")
            ):
                deselected_tests.append(item)
                continue
        # Tests marked with `in_webbrowser` are only for Node.js.
        elif item.get_closest_marker("node_without_jspi"):
            deselected_tests.append(item)
            continue

        # Firefox cannot run JSPI tests.
        if runtime.startswith("firefox") and item.get_closest_marker("with_jspi"):
            deselected_tests.append(item)
            continue

        selected_tests.append(item)

    config.hook.pytest_deselected(items=deselected_tests)
    items[:] = selected_tests


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """
    A pytest hook generating parametrized calls to a test function.
    """

    # Set proper `prefer_jspi` values for tests with WebAssembly
    # JavaScript Promise Integration both enabled and disabled depending
    # on browser/Node.js support for features.
    if "prefer_jspi" in metafunc.fixturenames:
        # node only supports JSPI and doesn't support workers or
        # webbrowser specific tests
        if metafunc.config.getoption("--runtime").startswith("node"):
            if metafunc.definition.get_closest_marker("node_without_jspi"):
                can_run_with_jspi = False
                can_run_without_jspi = True
            else:
                can_run_with_jspi = True
                can_run_without_jspi = False
        # firefox doesn't support JSPI
        elif metafunc.config.getoption("--runtime").startswith("firefox"):
            can_run_with_jspi = False
            can_run_without_jspi = True
        else:
            # chrome supports JSPI on or off
            can_run_without_jspi = True
            can_run_with_jspi = True

        # if the function is marked to only run with or without jspi,
        # then disable the alternative option
        if metafunc.definition.get_closest_marker("with_jspi"):
            can_run_without_jspi = False
        elif metafunc.definition.get_closest_marker("without_jspi"):
            can_run_with_jspi = False

        jspi_options = []
        if can_run_without_jspi:
            jspi_options.append(False)
        if can_run_with_jspi:
            jspi_options.append(True)
        metafunc.parametrize("prefer_jspi", jspi_options)

from __future__ import annotations

import typing

import pytest

from urllib3.fields import _TYPE_FIELD_VALUE_TUPLE

# only run these tests if pytest_pyodide is installed
# so we don't break non-emscripten pytest running
pytest_pyodide = pytest.importorskip("pytest_pyodide")

from pytest_pyodide import run_in_pyodide  # type: ignore[import] # noqa: E402
from pytest_pyodide.decorator import (  # type: ignore[import] # noqa: E402
    copy_files_to_pyodide,
)

from .conftest import PyodideServerInfo, ServerRunnerInfo  # noqa: E402

# make our ssl certificates work in chrome
pytest_pyodide.runner.CHROME_FLAGS.append("ignore-certificate-errors")


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_index(selenium: typing.Any, testserver_http: PyodideServerInfo) -> None:
    @run_in_pyodide  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        from urllib3.connection import HTTPConnection
        from urllib3.response import HTTPResponse

        conn = HTTPConnection(host, port)
        method = "GET"
        path = "/"
        url = f"http://{host}:{port}{path}"
        conn.request(method, url)
        response = conn.getresponse()
        assert isinstance(response, HTTPResponse)
        data = response.data
        assert data.decode("utf-8") == "Dummy server!"
        1

    pyodide_test(selenium, testserver_http.http_host, testserver_http.http_port)


# wrong protocol / protocol error etc. should raise an exception of urllib3.exceptions.ResponseError
@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_wrong_protocol(
    selenium: typing.Any, testserver_http: PyodideServerInfo
) -> None:
    @run_in_pyodide(packages=("pytest",))  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        import pytest

        import urllib3.exceptions
        from urllib3.connection import HTTPConnection

        conn = HTTPConnection(host, port)
        method = "GET"
        path = "/"
        url = f"http://{host}:{port}{path}"
        try:
            conn.request(method, url)
            conn.getresponse()
            pytest.fail("Should have thrown ResponseError here")
        except BaseException as ex:
            assert isinstance(ex, urllib3.exceptions.ResponseError)

    pyodide_test(selenium, testserver_http.http_host, testserver_http.https_port)


# no connection - should raise
@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_no_response(selenium: typing.Any, testserver_http: PyodideServerInfo) -> None:
    @run_in_pyodide(packages=("pytest",))  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        import pytest

        import urllib3.exceptions
        from urllib3.connection import HTTPConnection

        conn = HTTPConnection(host, port)
        method = "GET"
        path = "/"
        url = f"http://{host}:{port}{path}"
        try:
            conn.request(method, url)
            _ = conn.getresponse()
            pytest.fail("No response, should throw exception.")
        except BaseException as ex:
            assert isinstance(ex, urllib3.exceptions.ResponseError)

    import socket

    sock = socket.socket()
    sock.bind(("", 0))
    free_port = sock.getsockname()[1]
    sock.close()

    pyodide_test(selenium, testserver_http.http_host, free_port)


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_404(selenium: typing.Any, testserver_http: PyodideServerInfo) -> None:
    @run_in_pyodide  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        from urllib3.connection import HTTPConnection
        from urllib3.response import HTTPResponse

        conn = HTTPConnection(host, port)
        method = "GET"
        path = "/status?status=404 NOT FOUND"
        url = f"http://{host}:{port}{path}"
        conn.request(method, url)
        response = conn.getresponse()
        assert isinstance(response, HTTPResponse)
        assert response.status == 404
        1

    pyodide_test(selenium, testserver_http.http_host, testserver_http.http_port)


# setting timeout should show a warning to js console
# if we're on the ui thread, because XMLHttpRequest doesn't
# support timeout in async mode if globalThis == Window
@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_timeout_warning(
    selenium: typing.Any, testserver_http: PyodideServerInfo
) -> None:
    @run_in_pyodide()  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        import urllib3.contrib.emscripten.fetch
        from urllib3.connection import HTTPConnection

        conn = HTTPConnection(host, port, timeout=1.0)
        method = "GET"
        path = "/"
        url = f"http://{host}:{port}{path}"
        conn.request(method, url)
        conn.getresponse()
        assert urllib3.contrib.emscripten.fetch._SHOWN_TIMEOUT_WARNING
        1

    pyodide_test(selenium, testserver_http.http_host, testserver_http.http_port)


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_timeout_in_worker(
    selenium: typing.Any,
    testserver_http: PyodideServerInfo,
    run_from_server: ServerRunnerInfo,
) -> None:
    worker_code = f"""
        import micropip
        await micropip.install('http://{testserver_http.http_host}:{testserver_http.http_port}/wheel/urllib3-2.0.7-py3-none-typing.Any.whl',deps=False)
        import urllib3.contrib.emscripten.fetch
        await urllib3.contrib.emscripten.fetch.wait_for_streaming_ready()
        from urllib3.exceptions import TimeoutError
        from urllib3.connection import HTTPConnection
        conn = HTTPConnection("{testserver_http.http_host}", {testserver_http.http_port},timeout=1.0)
        method = "GET"
        url = "http://{testserver_http.http_host}:{testserver_http.http_port}/slow"
        result=-1
        try:
            conn.request(method, url)
            _response = conn.getresponse()
            result=-3
        except TimeoutError as e:
            result=1 # we've got the correct exception
        except BaseException as e:
            result=-2
        result
"""
    result = run_from_server.run_webworker(worker_code)
    # result == 1 = success, -2 = wrong exception, -3 = no exception thrown
    assert result == 1


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_index_https(selenium: typing.Any, testserver_http: PyodideServerInfo) -> None:
    @run_in_pyodide  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        from urllib3.connection import HTTPSConnection
        from urllib3.response import HTTPResponse

        conn = HTTPSConnection(host, port)
        method = "GET"
        path = "/"
        url = f"https://{host}:{port}{path}"
        conn.request(method, url)
        response = conn.getresponse()
        assert isinstance(response, HTTPResponse)
        data = response.data
        assert data.decode("utf-8") == "Dummy server!"
        1

    pyodide_test(selenium, testserver_http.http_host, testserver_http.https_port)


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_non_streaming_no_fallback_warning(
    selenium: typing.Any, testserver_http: PyodideServerInfo
) -> None:
    @run_in_pyodide  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        import urllib3.contrib.emscripten.fetch
        from urllib3.connection import HTTPSConnection
        from urllib3.response import HTTPResponse

        conn = HTTPSConnection(host, port)
        method = "GET"
        path = "/"
        url = f"https://{host}:{port}{path}"
        conn.request(method, url, preload_content=True)
        response = conn.getresponse()
        assert isinstance(response, HTTPResponse)
        data = response.data
        assert data.decode("utf-8") == "Dummy server!"
        # no console warnings because we didn't ask it to stream the response
        assert not urllib3.contrib.emscripten.fetch._SHOWN_STREAMING_WARNING

    pyodide_test(selenium, testserver_http.http_host, testserver_http.https_port)


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_streaming_fallback_warning(
    selenium: typing.Any, testserver_http: PyodideServerInfo
) -> None:
    @run_in_pyodide  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        import urllib3.contrib.emscripten.fetch
        from urllib3.connection import HTTPSConnection
        from urllib3.response import HTTPResponse

        conn = HTTPSConnection(host, port)
        method = "GET"
        path = "/"
        url = f"https://{host}:{port}{path}"
        conn.request(method, url, preload_content=False)
        response = conn.getresponse()
        assert isinstance(response, HTTPResponse)
        data = response.data
        assert data.decode("utf-8") == "Dummy server!"
        # check that it has warned about falling back to non-streaming fetch
        assert urllib3.contrib.emscripten.fetch._SHOWN_STREAMING_WARNING

    pyodide_test(selenium, testserver_http.http_host, testserver_http.https_port)


def test_upload(
    selenium: typing.Any,
    testserver_http: PyodideServerInfo,
    run_from_server: ServerRunnerInfo,
) -> None:
    @run_in_pyodide  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        from urllib3 import HTTPConnectionPool

        data = "I'm in ur multipart form-data, hazing a cheezburgr"
        fields: dict[str, _TYPE_FIELD_VALUE_TUPLE] = {
            "upload_param": "filefield",
            "upload_filename": "lolcat.txt",
            "filefield": ("lolcat.txt", data),
        }
        fields["upload_size"] = len(data)  # type: ignore
        with HTTPConnectionPool(host, port) as pool:
            r = pool.request("POST", "/upload", fields=fields)
            assert r.status == 200, r.data

    pyodide_test(selenium, testserver_http.http_host, testserver_http.https_port)


def test_specific_method(
    selenium: typing.Any,
    testserver_http: PyodideServerInfo,
    run_from_server: ServerRunnerInfo,
) -> None:
    print("Running from server")

    @run_in_pyodide  # type: ignore[misc]
    def pyodide_test(selenium, host: str, port: int) -> None:  # type: ignore[no-untyped-def]
        from urllib3 import HTTPConnectionPool
        from urllib3.response import HTTPResponse

        with HTTPConnectionPool(host, port) as pool:
            method = "POST"
            path = "/specific_method?method=POST"
            response = pool.request(method, path)
            assert isinstance(response, HTTPResponse)
            assert response.status == 200

            method = "PUT"
            path = "/specific_method?method=POST"
            response = pool.request(method, path)
            assert isinstance(response, HTTPResponse)
            assert response.status == 400

    pyodide_test(selenium, testserver_http.http_host, testserver_http.https_port)


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_streaming_download(
    selenium: typing.Any,
    testserver_http: PyodideServerInfo,
    run_from_server: ServerRunnerInfo,
) -> None:
    # test streaming download, which must be in a webworker
    # as you can't do it on main thread

    # this should return the 17mb big file, and
    # should not log typing.Any warning about falling back
    bigfile_url = (
        f"http://{testserver_http.http_host}:{testserver_http.http_port}/bigfile"
    )
    worker_code = f"""import micropip
await micropip.install('http://{testserver_http.http_host}:{testserver_http.http_port}/wheel/urllib3-2.0.7-py3-none-typing.Any.whl',deps=False)
import urllib3.contrib.emscripten.fetch
await urllib3.contrib.emscripten.fetch.wait_for_streaming_ready()
from urllib3.response import HTTPResponse
from urllib3.connection import HTTPConnection
import js

conn = HTTPConnection("{testserver_http.http_host}", {testserver_http.http_port})
method = "GET"
url = "{bigfile_url}"
conn.request(method, url,preload_content=False)
response = conn.getresponse()
assert isinstance(response, HTTPResponse)
assert urllib3.contrib.emscripten.fetch._SHOWN_STREAMING_WARNING==False
data=response.data.decode('utf-8')
data
"""
    result = run_from_server.run_webworker(worker_code)
    assert len(result) == 17825792


@copy_files_to_pyodide(file_list=[("dist/*.whl", "/tmp")], install_wheels=True)  # type: ignore[misc]
def test_streaming_notready_warning(
    selenium: typing.Any,
    testserver_http: PyodideServerInfo,
    run_from_server: ServerRunnerInfo,
) -> None:
    # test streaming download but don't wait for
    # worker to be ready - should fallback to non-streaming
    # and log a warning
    bigfile_url = (
        f"http://{testserver_http.http_host}:{testserver_http.http_port}/bigfile"
    )
    worker_code = f"""import micropip
await micropip.install('http://{testserver_http.http_host}:{testserver_http.http_port}/wheel/urllib3-2.0.7-py3-none-typing.Any.whl',deps=False)
import urllib3.contrib.emscripten.fetch
from urllib3.response import HTTPResponse
from urllib3.connection import HTTPConnection

conn = HTTPConnection("{testserver_http.http_host}", {testserver_http.http_port})
method = "GET"
url = "{bigfile_url}"
conn.request(method, url,preload_content=False)
response = conn.getresponse()
assert isinstance(response, HTTPResponse)
data=response.data.decode('utf-8')
assert urllib3.contrib.emscripten.fetch._SHOWN_STREAMING_WARNING==True
data
"""
    result = run_from_server.run_webworker(worker_code)
    assert len(result) == 17825792

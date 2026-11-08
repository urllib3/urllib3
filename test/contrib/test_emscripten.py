from __future__ import annotations

import sys
from unittest.mock import MagicMock


def test_send_jspi_request_null_body() -> None:
    class MockJsNull:
        def __getattr__(self, name: str) -> None:
            raise AttributeError(f"'JsNull' object has no attribute '{name}'")

    js_mock = MagicMock()
    pyodide_mock = MagicMock()
    pyodide_mock.ffi.JsNull = MockJsNull

    orig_js = sys.modules.get("js")
    orig_pyodide = sys.modules.get("pyodide")
    orig_pyodide_ffi = sys.modules.get("pyodide.ffi")

    sys.modules["js"] = js_mock
    sys.modules["pyodide"] = pyodide_mock
    sys.modules["pyodide.ffi"] = pyodide_mock.ffi

    orig_fetch_jsnull = None
    fetch_module = None

    try:
        import urllib3.contrib.emscripten.fetch as fetch
        from urllib3.contrib.emscripten.request import EmscriptenRequest

        fetch_module = fetch
        orig_fetch_jsnull = getattr(fetch, "JsNull", None)
        setattr(fetch, "JsNull", MockJsNull)

        # Test with JsNull instance
        req = EmscriptenRequest("GET", "http://example.com")
        mock_resp_js = MagicMock()
        mock_resp_js.headers.entries().next.return_value = MagicMock(done=True)
        mock_resp_js.status = 204
        mock_resp_js.body = MockJsNull()

        orig_run_sync = fetch._run_sync_with_timeout
        fetch._run_sync_with_timeout = MagicMock(return_value=mock_resp_js)
        try:
            resp = fetch.send_jspi_request(req, streaming=True)
            assert resp.status_code == 204
            assert resp.body == b""

            # Test with None body
            mock_resp_js.body = None
            resp_none = fetch.send_jspi_request(req, streaming=True)
            assert resp_none.status_code == 204
            assert resp_none.body == b""
        finally:
            fetch._run_sync_with_timeout = orig_run_sync
    finally:
        if fetch_module is not None:
            setattr(fetch_module, "JsNull", orig_fetch_jsnull)

        sys.modules.pop("urllib3.contrib.emscripten.fetch", None)
        sys.modules.pop("urllib3.contrib.emscripten.request", None)
        sys.modules.pop("urllib3.contrib.emscripten.response", None)
        sys.modules.pop("urllib3.contrib.emscripten", None)

        if orig_js is not None:
            sys.modules["js"] = orig_js
        else:
            sys.modules.pop("js", None)

        if orig_pyodide is not None:
            sys.modules["pyodide"] = orig_pyodide
        else:
            sys.modules.pop("pyodide", None)

        if orig_pyodide_ffi is not None:
            sys.modules["pyodide.ffi"] = orig_pyodide_ffi
        else:
            sys.modules.pop("pyodide.ffi", None)

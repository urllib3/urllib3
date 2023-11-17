"""
Support for streaming http requests in emscripten.

A few caveats -

Firstly, you can't do streaming http in the main UI thread, because atomics.wait isn't allowed.
Streaming only works if you're running pyodide in a web worker.

Secondly, this uses an extra web worker and SharedArrayBuffer to do the asynchronous fetch
operation, so it requires that you have crossOriginIsolation enabled, by serving over https
(or from localhost) with the two headers below set:

    Cross-Origin-Opener-Policy: same-origin
    Cross-Origin-Embedder-Policy: require-corp

You can tell if cross origin isolation is successfully enabled by looking at the global crossOriginIsolated variable in
javascript console. If it isn't, streaming requests will fallback to XMLHttpRequest, i.e. getting the whole
request into a buffer and then returning it. it shows a warning in the javascript console in this case.

Finally, the webworker which does the streaming fetch is created on initial import, but will only be started once
control is returned to javascript. Call `await wait_for_streaming_ready()` to wait for streaming fetch.
"""
from __future__ import annotations

import io
import json
from email.parser import Parser
from typing import TYPE_CHECKING, Any

import js  # type: ignore[import]
from pyodide.ffi import JsArray, JsException, JsProxy, to_js  # type: ignore[import]

if TYPE_CHECKING:
    from typing_extensions import Buffer

from .request import EmscriptenRequest
from .response import EmscriptenResponse

"""
There are some headers that trigger unintended CORS preflight requests.
See also https://github.com/koenvo/pyodide-http/issues/22
"""
HEADERS_TO_IGNORE = ("user-agent",)

SUCCESS_HEADER = -1
SUCCESS_EOF = -2
ERROR_TIMEOUT = -3
ERROR_EXCEPTION = -4


class _RequestError(Exception):
    def __init__(
        self,
        message: str | None = None,
        *,
        request: EmscriptenRequest | None = None,
        response: EmscriptenResponse | None = None,
    ):
        self.request = request
        self.response = response
        self.message = message
        super().__init__(self.message)


class _StreamingError(_RequestError):
    pass


class _TimeoutError(_RequestError):
    pass


_STREAMING_WORKER_CODE = """
let SUCCESS_HEADER = -1
let SUCCESS_EOF = -2
let ERROR_TIMEOUT = -3
let ERROR_EXCEPTION = -4

let connections = {};
let nextConnectionID = 1;

self.addEventListener("message", async function (event) {
    if(event.data.close)
    {
        let connectionID=event.data.close;
        delete connections[connectionID];
        return;
    }else if (event.data.getMore) {
        let connectionID = event.data.getMore;
        let { curOffset, value, reader,intBuffer,byteBuffer } = connections[connectionID];
        // if we still have some in buffer, then just send it back straight away
        if (!value || curOffset >= value.length) {
            // read another buffer if required
            try
            {
                let readResponse = await reader.read();

                if (readResponse.done) {
                    // read everything - clear connection and return
                    delete connections[connectionID];
                    Atomics.store(intBuffer, 0, SUCCESS_EOF);
                    Atomics.notify(intBuffer, 0);
                    // finished reading successfully
                    // return from event handler
                    return;
                }
                curOffset = 0;
                connections[connectionID].value = readResponse.value;
                value=readResponse.value;
            }catch(error)
            {
                console.log("Request exception:", error);
                let errorBytes = encoder.encode(error.message);
                let written = errorBytes.length;
                byteBuffer.set(errorBytes);
                intBuffer[1] = written;
                Atomics.store(intBuffer, 0, ERROR_EXCEPTION);
                Atomics.notify(intBuffer, 0);
            }
        }

        // send as much buffer as we can
        let curLen = value.length - curOffset;
        if (curLen > byteBuffer.length) {
            curLen = byteBuffer.length;
        }
        byteBuffer.set(value.subarray(curOffset, curOffset + curLen), 0)

        Atomics.store(intBuffer, 0, curLen);// store current length in bytes
        Atomics.notify(intBuffer, 0);
        curOffset+=curLen;
        connections[connectionID].curOffset = curOffset;

        return;
    } else {
        // start fetch
        let connectionID = nextConnectionID;
        nextConnectionID += 1;
        const encoder = new TextEncoder();
        const intBuffer = new Int32Array(event.data.buffer);
        const byteBuffer = new Uint8Array(event.data.buffer, 8)
        try {
            const response = await fetch(event.data.url, event.data.fetchParams);
            // return the headers first via textencoder
            var headers = [];
            for (const pair of response.headers.entries()) {
                headers.push([pair[0], pair[1]]);
            }
            headerObj = { headers: headers, status: response.status, connectionID };
            const headerText = JSON.stringify(headerObj);
            let headerBytes = encoder.encode(headerText);
            let written = headerBytes.length;
            byteBuffer.set(headerBytes);
            intBuffer[1] = written;
            // make a connection
            connections[connectionID] = { reader:response.body.getReader(),intBuffer:intBuffer,byteBuffer:byteBuffer,value:undefined,curOffset:0 };
            // set header ready
            Atomics.store(intBuffer, 0, SUCCESS_HEADER);
            Atomics.notify(intBuffer, 0);
            // all fetching after this goes through a new postmessage call with getMore
            // this allows for parallel requests
        }
        catch (error) {
            console.log("Request exception:", error);
            let errorBytes = encoder.encode(error.message);
            let written = errorBytes.length;
            byteBuffer.set(errorBytes);
            intBuffer[1] = written;
            Atomics.store(intBuffer, 0, ERROR_EXCEPTION);
            Atomics.notify(intBuffer, 0);
        }
    }
});
self.postMessage({inited:true})
"""


def _obj_from_dict(dict_val: dict[str, Any]) -> JsProxy:
    return to_js(dict_val, dict_converter=js.Object.fromEntries)


class _ReadStream(io.RawIOBase):
    def __init__(
        self,
        int_buffer: JsArray,
        byte_buffer: JsArray,
        timeout: float,
        worker: JsProxy,
        connection_id: int,
    ):
        self.int_buffer = int_buffer
        self.byte_buffer = byte_buffer
        self.read_pos = 0
        self.read_len = 0
        self.connection_id = connection_id
        self.worker = worker
        self.timeout = int(1000 * timeout) if timeout > 0 else None
        self.is_live = True

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if self.is_live:
            self.worker.postMessage(_obj_from_dict({"close": self.connection_id}))
            self.is_live = False
        super().close()

    def readable(self) -> bool:
        return True

    def writeable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def readinto(self, byte_obj: Buffer) -> int:
        if not self.int_buffer:
            return 0
        if self.read_len == 0:
            # wait for the worker to send something
            js.Atomics.store(self.int_buffer, 0, 0)
            self.worker.postMessage(_obj_from_dict({"getMore": self.connection_id}))
            if js.Atomics.wait(self.int_buffer, 0, 0, self.timeout) == "timed-out":
                raise _TimeoutError
            data_len = self.int_buffer[0]
            if data_len > 0:
                self.read_len = data_len
                self.read_pos = 0
            elif data_len == ERROR_EXCEPTION:
                raise _StreamingError
            else:
                # EOF, free the buffers and return zero
                self.read_len = 0
                self.read_pos = 0
                self.int_buffer = None
                self.byte_buffer = None
                return 0
        # copy from int32array to python bytes
        ret_length = min(self.read_len, len(memoryview(byte_obj)))
        subarray = self.byte_buffer.subarray(
            self.read_pos, self.read_pos + ret_length
        ).to_py()
        memoryview(byte_obj)[0:ret_length] = subarray
        self.read_len -= ret_length
        self.read_pos += ret_length
        return ret_length


class _StreamingFetcher:
    def __init__(self) -> None:
        # make web-worker and data buffer on startup
        self.streaming_ready = False

        dataBlob = js.Blob.new(
            [_STREAMING_WORKER_CODE], _obj_from_dict({"type": "application/javascript"})
        )

        def promise_resolver(res: JsProxy, rej: JsProxy) -> None:
            def onMsg(e: JsProxy) -> None:
                self.streaming_ready = True
                res(e)

            def onErr(e: JsProxy) -> None:
                rej(e)

            self._worker.onmessage = onMsg
            self._worker.onerror = onErr

        dataURL = js.URL.createObjectURL(dataBlob)
        self._worker = js.globalThis.Worker.new(dataURL)
        self._worker_ready_promise = js.globalThis.Promise.new(promise_resolver)

    def send(self, request: EmscriptenRequest) -> EmscriptenResponse:
        headers = {
            k: v for k, v in request.headers.items() if k not in HEADERS_TO_IGNORE
        }

        body = request.body
        fetch_data = {"headers": headers, "body": to_js(body), "method": request.method}
        # start the request off in the worker
        timeout = int(1000 * request.timeout) if request.timeout > 0 else None
        shared_buffer = js.SharedArrayBuffer.new(1048576)
        int_buffer = js.Int32Array.new(shared_buffer)
        byte_buffer = js.Uint8Array.new(shared_buffer, 8)

        js.Atomics.store(int_buffer, 0, 0)
        js.Atomics.notify(int_buffer, 0)
        absolute_url = js.URL.new(request.url, js.location).href
        self._worker.postMessage(
            _obj_from_dict(
                {
                    "buffer": shared_buffer,
                    "url": absolute_url,
                    "fetchParams": fetch_data,
                }
            )
        )
        # wait for the worker to send something
        js.Atomics.wait(int_buffer, 0, 0, timeout)
        if int_buffer[0] == 0:
            raise _TimeoutError(
                "Timeout connecting to streaming request",
                request=request,
                response=None,
            )
        if int_buffer[0] == SUCCESS_HEADER:
            # got response
            # header length is in second int of intBuffer
            string_len = int_buffer[1]
            # decode the rest to a JSON string
            decoder = js.TextDecoder.new()
            # this does a copy (the slice) because decode can't work on shared array
            # for some silly reason
            json_str = decoder.decode(byte_buffer.slice(0, string_len))
            # get it as an object
            response_obj = json.loads(json_str)
            return EmscriptenResponse(
                request=request,
                status_code=response_obj["status"],
                headers=response_obj["headers"],
                body=io.BufferedReader(
                    _ReadStream(
                        int_buffer,
                        byte_buffer,
                        request.timeout,
                        self._worker,
                        response_obj["connectionID"],
                    ),
                    buffer_size=1048576,
                ),
            )
        elif int_buffer[0] == ERROR_EXCEPTION:
            string_len = int_buffer[1]
            # decode the error string
            decoder = js.TextDecoder.new()
            json_str = decoder.decode(byte_buffer.slice(0, string_len))
            raise _StreamingError(
                f"Exception thrown in fetch: {json_str}", request=request, response=None
            )
        else:
            raise _StreamingError(
                f"Unknown status from worker in fetch: {int_buffer[0]}",
                request=request,
                response=None,
            )


# check if we are in a worker or not
def is_in_browser_main_thread() -> bool:
    return hasattr(js, "window") and hasattr(js, "self") and js.self == js.window


def is_cross_origin_isolated() -> bool:
    return hasattr(js, "crossOriginIsolated") and js.crossOriginIsolated


def is_in_node() -> bool:
    return (
        hasattr(js, "process")
        and hasattr(js.process, "release")
        and hasattr(js.process.release, "name")
        and js.process.release.name == "node"
    )


def is_worker_available() -> bool:
    return hasattr(js, "Worker") and hasattr(js, "Blob")


_fetcher: _StreamingFetcher | None = None

if is_worker_available() and (
    (is_cross_origin_isolated() and not is_in_browser_main_thread())
    and (not is_in_node())
):
    _fetcher = _StreamingFetcher()
else:
    _fetcher = None


def send_streaming_request(request: EmscriptenRequest) -> EmscriptenResponse | None:
    if _fetcher and streaming_ready():
        return _fetcher.send(request)
    else:
        _show_streaming_warning()
        return None


_SHOWN_TIMEOUT_WARNING = False


def _show_timeout_warning() -> None:
    global _SHOWN_TIMEOUT_WARNING
    if not _SHOWN_TIMEOUT_WARNING:
        _SHOWN_TIMEOUT_WARNING = True
        message = "Warning: Timeout is not available on main browser thread"
        js.console.warn(message)


_SHOWN_STREAMING_WARNING = False


def _show_streaming_warning() -> None:
    global _SHOWN_STREAMING_WARNING
    if not _SHOWN_STREAMING_WARNING:
        _SHOWN_STREAMING_WARNING = True
        message = "Can't stream HTTP requests because: \n"
        if not is_cross_origin_isolated():
            message += "  Page is not cross-origin isolated\n"
        if is_in_browser_main_thread():
            message += "  Python is running in main browser thread\n"
        if not is_worker_available():
            message += " Worker or Blob classes are not available in this environment."
        if streaming_ready() is False:
            message += """ Streaming fetch worker isn't ready. If you want to be sure that streamig fetch
is working, you need to call: 'await urllib3.contrib.emscripten.fetc.wait_for_streaming_ready()`"""
        from js import console

        console.warn(message)


def send_request(request: EmscriptenRequest) -> EmscriptenResponse:
    try:
        xhr = js.XMLHttpRequest.new()

        if not is_in_browser_main_thread():
            xhr.responseType = "arraybuffer"
            if request.timeout:
                xhr.timeout = int(request.timeout * 1000)
        else:
            xhr.overrideMimeType("text/plain; charset=ISO-8859-15")
            if request.timeout:
                # timeout isn't available on the main thread - show a warning in console
                # if it is set
                _show_timeout_warning()

        xhr.open(request.method, request.url, False)
        for name, value in request.headers.items():
            if name.lower() not in HEADERS_TO_IGNORE:
                xhr.setRequestHeader(name, value)

        xhr.send(to_js(request.body))

        headers = dict(Parser().parsestr(xhr.getAllResponseHeaders()))

        if not is_in_browser_main_thread():
            body = xhr.response.to_py().tobytes()
        else:
            body = xhr.response.encode("ISO-8859-15")
        return EmscriptenResponse(
            status_code=xhr.status, headers=headers, body=body, request=request
        )
    except JsException as err:
        if err.name == "TimeoutError":
            raise _TimeoutError(err.message, request=request)
        elif err.name == "NetworkError":
            raise _RequestError(err.message, request=request)
        else:
            # general http error
            raise _RequestError(err.message, request=request)


def streaming_ready() -> bool | None:
    if _fetcher:
        return _fetcher.streaming_ready
    else:
        return None  # no fetcher, return None to signify that


async def wait_for_streaming_ready() -> bool:
    if _fetcher:
        await _fetcher._worker_ready_promise
        return True
    else:
        return False

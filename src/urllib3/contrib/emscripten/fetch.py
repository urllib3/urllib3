"""
Support for streaming http requests in emscripten. 

A couple of caveats - 

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
"""
import io
import json
import js
from pyodide.ffi import to_js
from .request import EmscriptenRequest
from .response import EmscriptenResponse

from email.parser import Parser

"""
There are some headers that trigger unintended CORS preflight requests.
See also https://github.com/koenvo/pyodide-http/issues/22
"""
HEADERS_TO_IGNORE = ("user-agent",)

SUCCESS_HEADER = -1
SUCCESS_EOF = -2
ERROR_TIMEOUT = -3
ERROR_EXCEPTION = -4

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
"""


def _obj_from_dict(dict_val: dict) -> any:
    return to_js(dict_val, dict_converter=js.Object.fromEntries)


class _ReadStream(io.RawIOBase):
    def __init__(self, int_buffer, byte_buffer, timeout, worker, connection_id):
        self.int_buffer = int_buffer
        self.byte_buffer = byte_buffer
        self.read_pos = 0
        self.read_len = 0
        self.connection_id = connection_id
        self.worker = worker
        self.timeout = int(1000 * timeout) if timeout > 0 else None
        self.closed = False

    def __del__(self):
        self.close()

    def close(self):
        if not self.closed:
            self.worker.postMessage(_obj_from_dict({"close": self.connection_id}))
            self.closed = True

    def readable(self) -> bool:
        return True

    def writeable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def readinto(self, byte_obj) -> bool:
        if not self.int_buffer:
            return 0
        if self.read_len == 0:
            # wait for the worker to send something
            js.Atomics.store(self.int_buffer, 0, 0)
            self.worker.postMessage(_obj_from_dict({"getMore": self.connection_id}))
            if js.Atomics.wait(self.int_buffer, 0, 0, self.timeout) == "timed-out":
                from ._core import _StreamingTimeout

                raise _StreamingTimeout
            data_len = self.int_buffer[0]
            if data_len > 0:
                self.read_len = data_len
                self.read_pos = 0
            elif data_len == ERROR_EXCEPTION:
                from ._core import _StreamingError

                raise _StreamingError
            else:
                # EOF, free the buffers and return zero
                self.read_len = 0
                self.read_pos = 0
                self.int_buffer = None
                self.byte_buffer = None
                return 0
        # copy from int32array to python bytes
        ret_length = min(self.read_len, len(byte_obj))
        self.byte_buffer.subarray(self.read_pos, self.read_pos + ret_length).assign_to(
            byte_obj[0:ret_length]
        )
        self.read_len -= ret_length
        self.read_pos += ret_length
        return ret_length


class _StreamingFetcher:
    def __init__(self):
        # make web-worker and data buffer on startup
        dataBlob = js.globalThis.Blob.new(
            [_STREAMING_WORKER_CODE], _obj_from_dict({"type": "application/javascript"})
        )
        print("Make worker")
        dataURL = js.URL.createObjectURL(dataBlob)
        self._worker = js.Worker.new(dataURL)
        print("Initialized worker")

    def send(self, request):
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
        js.console.log(
            _obj_from_dict(
                {
                    "buffer": shared_buffer,
                    "url": absolute_url,
                    "fetchParams": fetch_data,
                }
            )
        )
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
            from ._core import _StreamingTimeout

            raise _StreamingTimeout(
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
        if int_buffer[0] == ERROR_EXCEPTION:
            string_len = int_buffer[1]
            # decode the error string
            decoder = js.TextDecoder.new()
            json_str = decoder.decode(byte_buffer.slice(0, string_len))
            from ._core import _StreamingError

            raise _StreamingError(
                f"Exception thrown in fetch: {json_str}", request=request, response=None
            )


# check if we are in a worker or not
def is_in_browser_main_thread() -> bool:
    return hasattr(js, "window") and hasattr(js, "self") and js.self == js.window

def is_cross_origin_isolated():
    print("COI:",js.crossOriginIsolated)
    return hasattr(js, "crossOriginIsolated") and js.crossOriginIsolated


def is_in_node():
    return (
        hasattr(js, "process")
        and hasattr(js.process, "release")
        and hasattr(js.process.release, "name")
        and js.process.release.name == "node"
    )

def is_worker_available():
    return hasattr(js,"Worker") and hasattr(js,"Blob")

if (is_worker_available() and ((is_cross_origin_isolated() and not is_in_browser_main_thread()) or is_in_node())):    
    _fetcher = _StreamingFetcher()
else:
    _fetcher = None

def send_streaming_request(request: EmscriptenRequest) -> EmscriptenResponse:
    if _fetcher:
        return _fetcher.send(request)
    else:
        _show_streaming_warning()
        return None


_SHOWN_WARNING = False


def _show_streaming_warning():
    global _SHOWN_WARNING
    if not _SHOWN_WARNING:
        _SHOWN_WARNING = True
        message = "Can't stream HTTP requests because: \n"
        if not is_cross_origin_isolated():
            message += "  Page is not cross-origin isolated\n"
        if is_in_browser_main_thread():
            message += "  Python is running in main browser thread\n"
        if not is_worker_available():
            message += " Worker or Blob classes are not available in this environment."
        from js import console

        console.warn(message)


def send_request(request:EmscriptenRequest)->EmscriptenResponse:
    xhr = js.XMLHttpRequest.new()
    xhr.timeout = int(request.timeout * 1000)

    if not is_in_browser_main_thread():
        xhr.responseType = "arraybuffer"
    else:
        xhr.overrideMimeType("text/plain; charset=ISO-8859-15")

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
    return EmscriptenResponse(status_code=xhr.status, headers=headers, body=body)

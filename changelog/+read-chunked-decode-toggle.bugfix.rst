Fixed rejected decoding-mode switches in ``HTTPResponse.read_chunked()``
consuming chunked response data and closing the pooled connection before
raising ``RuntimeError``. The response stays readable with decoding enabled,
matching ``HTTPResponse.read()`` from `#5344 <https://github.com/urllib3/urllib3/pull/5344>`__.
``read_chunked(decode_content=None)`` now also follows the response's
``decode_content`` setting, matching ``read()`` / ``read1()`` / ``stream()``
and fixing the same default as `#5326 <https://github.com/urllib3/urllib3/pull/5326>`__.

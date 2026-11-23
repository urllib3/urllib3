Fixed rejected decoding-mode switches in ``HTTPResponse.read_chunked()``
consuming chunked response data and closing the pooled connection before
raising ``RuntimeError``. The response stays readable with decoding enabled,
matching ``HTTPResponse.read()`` from `#5344 <https://github.com/urllib3/urllib3/pull/5344>`__.

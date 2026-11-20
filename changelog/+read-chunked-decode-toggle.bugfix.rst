Fixed rejected decoding-mode switches in ``HTTPResponse.read_chunked()``
consuming chunked response data before raising ``RuntimeError``, matching the
``HTTPResponse.read()`` behavior from `#5344 <https://github.com/urllib3/urllib3/pull/5344>`__.

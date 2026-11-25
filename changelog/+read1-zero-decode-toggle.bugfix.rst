Fixed ``HTTPResponse.read1(0, decode_content=False)`` raising ``RuntimeError`` after a decoded read, matching ``read(0, decode_content=False)`` which returns ``b""`` without consuming data.

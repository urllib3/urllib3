Fields and Multipart Forms
==========================

Fields
------

.. automodule:: urllib3.fields
    :members:
    :undoc-members:
    :show-inheritance:


Multipart Forms
---------------

.. autofunction:: urllib3.encode_multipart_formdata
.. autofunction:: urllib3.filepost.choose_boundary
.. autofunction:: urllib3.filepost.iter_field_objects


Streaming multipart bodies
--------------------------

:class:`~urllib3.multipart.MultipartEncoder` accepts file objects without reading
an entire file into memory. Pass the encoder as ``body`` and use its
``content_type`` as the request's ``Content-Type``::

    from urllib3 import PoolManager
    from urllib3.multipart import MultipartEncoder

    with open("report.csv", "rb") as source:
        body = MultipartEncoder.from_fields({
            "description": "Monthly report",
            "file": ("report.csv", source, "text/csv"),
        })
        with PoolManager() as http:
            response = http.request(
                "POST",
                "https://example.com/upload",
                body=body,
                headers={"Content-Type": body.content_type},
            )

The request uses chunked transfer encoding unless a content length is supplied
separately. Keep the files open until the request finishes. Closing an encoder
or a :class:`~urllib3.multipart.Part` does not close caller-owned input files.
Files start at their current position. ``seek(0, 0)`` rewinds every part to that
starting position, including attempts after an earlier part fails. If any part
cannot rewind, the encoder raises ``io.UnsupportedOperation`` and cannot be
read again until a successful rewind. Other encoder seek positions are not
supported. Use seekable inputs when a request might need to be resent.

Bounded positive ``read(size)`` calls stream the body. Calling ``read()`` without
a size materializes the remaining output. The legacy
:func:`~urllib3.encode_multipart_formdata` still returns the complete body as
``bytes``, so it necessarily allocates memory proportional to that body.
Encoder metadata scales with the number of parts and their headers. Text and
bytes-like values are buffered in memory when constructing a part; use binary
file objects to avoid loading large inputs into memory.

:class:`~urllib3.multipart.MultipartDecoder` reads a multipart stream one part
at a time. Supply the boundary value without the leading ``--`` delimiter::

    from urllib3.multipart import MultipartDecoder

    decoder = MultipartDecoder(source, boundary="example-boundary")
    for part in decoder:
        print(part.headers)
        while chunk := part.read(8192):
            destination.write(chunk)

Consume each part before advancing the iterator. Advancing discards unread
source bytes for the previous part; previously buffered bytes may remain
readable from that old part, but it will never read into a subsequent part.
Decoded parts do not support seeking. The decoder leaves its source open.
It raises ``ValueError`` for malformed headers or truncated framing. Header
blocks and boundary padding are bounded by ``max_header_size``; the source is
read in chunks of ``buffer_size``. ``Part.peek()`` has the same buffering
semantics as ``io.BufferedReader.peek()`` and may return more or fewer bytes
than requested.

.. autoclass:: urllib3.multipart.Part
    :members: from_field

.. autoclass:: urllib3.multipart.MultipartEncoder
    :members: from_fields, read, readinto, seek, tell

.. autoclass:: urllib3.multipart.MultipartDecoder

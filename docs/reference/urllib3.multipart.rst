Multipart Encoders and Decoders
===============================

Streaming Request Encoding
--------------------------

.. autoclass:: urllib3.multipart.MultipartEncoder
   :members: content_type, content_length, headers

   .. automethod:: read

   .. automethod:: seek

   .. automethod:: tell

``seek(0, 0)`` rewinds all parts to their original body positions. Other
seeks are unsupported. The encoder attempts to rewind every part before
raising the first error if a body cannot be rewound. Keep file objects open
until the upload and any retries are complete; the encoder does not close them.

.. autoclass:: urllib3.multipart.Part
   :members: from_field, read, peek, seek


Response Decoding
-----------------

.. autoclass:: urllib3.multipart.MultipartDecoder
   :members: content_type, encoding, parts

   .. automethod:: from_response

.. autoclass:: urllib3.multipart.decoder.BodyPart
   :members: data, headers

The decoder consumes a complete response body in memory. Each part retains
its raw ``data`` bytes; use ``part.data.decode(...)`` to decode text explicitly.
Repeated header values are available through ``part.headers.getlist(...)``.

.. autoexception:: urllib3.multipart.ImproperBodyPartContentError

.. autoexception:: urllib3.multipart.NonMultipartContentTypeError

Multipart Encoder and Decoder
=============================

.. module:: urllib3.multipart

Encoder
-------

.. class:: MultipartEncoder(fields, *, boundary=None, encoding="utf-8", blocksize=32768)

   A file-like, memory-efficient streaming ``multipart/form-data`` encoder.

   .. automethod:: urllib3.multipart.MultipartEncoder.read
   .. automethod:: urllib3.multipart.MultipartEncoder.tell
   .. automethod:: urllib3.multipart.MultipartEncoder.seek
   .. automethod:: urllib3.multipart.MultipartEncoder.seekable
   .. autoattribute:: urllib3.multipart.MultipartEncoder.boundary
   .. autoattribute:: urllib3.multipart.MultipartEncoder.content_type
   .. autoattribute:: urllib3.multipart.MultipartEncoder.content_length
   .. autoattribute:: urllib3.multipart.MultipartEncoder.headers

.. class:: Part(headers, body)

   A streaming multipart body part containing headers and a body stream.

   .. automethod:: urllib3.multipart.Part.read
   .. automethod:: urllib3.multipart.Part.peek
   .. automethod:: urllib3.multipart.Part.rewind

Decoder
-------

.. autoclass:: urllib3.multipart.MultipartDecoder
    :members:

.. autoclass:: urllib3.multipart.BodyPart
    :members:

Exceptions
----------

.. autoclass:: urllib3.multipart.ImproperBodyPartContentError

.. autoclass:: urllib3.multipart.NonMultipartContentTypeError

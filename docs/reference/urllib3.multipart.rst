Multipart Streaming
===================

.. module:: urllib3.multipart

``PoolManager.request`` uses ``MultipartEncoder`` automatically when ``fields``
are provided. It can also be used directly when the encoded body or headers are
needed separately:

.. code-block:: python

   import urllib3
   from urllib3.multipart import MultipartEncoder

   http = urllib3.PoolManager()
   encoder = MultipartEncoder({"field": "value"})
   response = http.request(
       "POST", "https://example.com/upload", body=encoder, headers=encoder.headers
   )

.. autoclass:: urllib3.multipart.MultipartEncoder
   :members: boundary, blocksize, content_type, content_length, headers, read, tell, seek

.. autoclass:: urllib3.multipart.Part
   :members: read, peek

Multipart responses can be decoded from an ``HTTPResponse``:

.. code-block:: python

   from urllib3.multipart import MultipartDecoder

   decoder = MultipartDecoder.from_response(response)
   for part in decoder.parts:
       print(part.headers, part.data)

.. autoclass:: urllib3.multipart.MultipartDecoder
   :members: from_response

.. autoclass:: urllib3.multipart.BodyPart
   :members: read, peek, tell, seek

.. autoexception:: urllib3.multipart.ImproperBodyPartContentError

.. autoexception:: urllib3.multipart.NonMultipartContentTypeError

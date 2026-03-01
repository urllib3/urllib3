Multipart Encoders and Decoders
===============================

Streaming Request Encoding
--------------------------

.. autoclass:: urllib3.multipart.MultipartEncoder
   :members: content_type, content_length, headers

   .. automethod:: read
   .. automethod:: tell
   .. automethod:: seek


Response Decoding
-----------------

.. autoclass:: urllib3.multipart.MultipartDecoder
   :members: content_type, encoding, parts

   .. automethod:: from_response

.. autoclass:: urllib3.multipart.decoder.BodyPart
   :members: content, encoding, headers, text

.. autoexception:: urllib3.multipart.ImproperBodyPartContentError

.. autoexception:: urllib3.multipart.NonMultipartContentTypeError

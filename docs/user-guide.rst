User Guide
==========

.. currentmodule:: urllib3

Making requests
---------------

First things first, import the Urllib3 module::

    >>> import urllib3

You'll need a :class:`~poolmanager.PoolManager` instance to make requests.
This object handles all of the details of connection pooling and thread safety
so that you don't have to::

    >>> http = urllib3.PoolManager()

To make a request use :meth:`~poolmanager.PoolManager.request`::

    >>> r = http.request('GET', 'http://httpbin.org/robots.txt')
    >>> r.data
    b'User-agent: *\nDisallow: /deny\n'

``request()`` returns a :class:`~response.HTTPResponse` object, the
:ref:`response_content` section explains how to handle various responses.

You can use :meth:`~poolmanager.PoolManager.request` to make requests using any
HTTP verb::

    >>> r = http.request(
    ...     'POST',
    ...     'http://httpbin.org/post',
    ...     fields={'hello: 'world'})

The different types of requests you can send is covered in :ref:`request_data`.

.. _response_content:

Response content
----------------

The :class:`~response.HTTPResponse` object provides ``status``, ``data``, and
``header`` attributes::

    >>> r = http.request('GET', 'http://httpbin.org/ip')
    >>> r.status
    200
    >>> r.data
    b'{\n  "origin": "104.232.115.37"\n}\n'
    >>> r.headers
    HTTPHeaderDict({'Content-Length': '33', ...})

JSON content
~~~~~~~~~~~~

The simpliest way to load JSON content is to read the whole response into
memory::

    >>> import json
    >>> r = http.request('GET', 'http://httpbin.org/ip')
    >>> json.loads(r.data.decode('utf-8'))
    {'origin': '127.0.0.1'}

However, this might not be the best way to handle larger responses. In these
cases, you might want to stream the response::

    >>> import codecs
    >>> reader = codecs.getreader('utf-8')
    >>> r = http.request('GET', 'http://httpbin.org/ip', preload_content=False)
    >>> json.load(reader(r))
    {'origin': '127.0.0.1'}
    >>> r.release_conn()

Setting ``preload_content`` to ``False`` means that urllib3 will stream the
response content. The response object can be treated as a file-like object where
calls to :meth:`~response.HTTPResponse.read()` will block until more response
data is available. The :mod:`codecs` module is used to ensure that the bytes are decoded as utf-8 suitable for the :mod:`json` module. Finally,
the call to :meth:`~response.HTTPResponse.release_conn` signals that the
connection can be returned to the pool to be re-used.

Binary content
~~~~~~~~~~~~~~

The ``data`` attribute of the response is always set to a byte string
representing the response content::

    >>> r = http.request('GET', 'http://httpbin.org/bytes/8')
    >>> r.data
    b'\xaa\xa5H?\x95\xe9\x9b\x11'

When dealing with large responses it's often better to stream and optionally
buffer the response content::

    >>> import io
    >>> r = http.request('GET', 'http://httpbin.org/bytes/1024', preload_content=False)
    >>> reader = io.BufferedReader(r, 8)
    >>> reader.read(4)
    b'\x88\x1f\x8b\xe5'
    >>> r.release_conn()

Setting ``preload_content`` to ``False`` means that urllib3 will stream the
response content. The response object can be treated as a file-like object where
calls to :meth:`~response.HTTPResponse.read()` will block until more response
data is available. :class:`io.BufferedReader` is used to demonstrate how to
buffer the stream. Finally, the call to :meth:`~response.HTTPResponse.release_conn` signals that the connection can be returned to the pool to be re-used.

.. _request_data:

Request data
------------

Query parameters
~~~~~~~~~~~~~~~~

For ``GET``, ``HEAD``, and ``DELETE`` requests, you can simply pass the
arguments as a dictionary in the ``fields`` argument to
:meth:`~poolmanager.PoolManager.request`::

    >>> r = http.request(
    ...     'GET',
    ...     'http://httpbin.org/get',
    ...     fields={'arg': 'value'})
    >>> json.loads(r.data.decode('utf-8'))['args']
    {'arg': 'value'}

For ``POST`` and ``PUT`` requests, you need to manually encode query parameters
in the URL::

    >>> from urllib.parse import urlencode
    >>> encoded_args = urlencode({'arg': 'value'})
    >>> url = 'http://httpbin.org/post?' + encoded_args
    >>> r = http.request('POST', url)
    >>> json.loads(r.data.decode('utf-8'))['args']
    {'arg': 'value'}

Headers
~~~~~~~

You can specify headers as a dictionary in the ``headers`` argument in :meth:`~poolmanager.PoolManager.request`::

    >>> r = http.request(
    ...     'GET',
    ...     'http://httpbin.org/headers',
    ...     headers={
    ...         'X-Something': 'value'
    ...     })
    >>> json.loads(r.data.decode('utf-8'))['headers']
    {'X-Something': 'value', 'Host': 'httpbin.org', 'Accept-Encoding': 'identity'}

Form data
~~~~~~~~~

For ``PUT`` and ``POST`` requests, urllib3 will automatically form-encode the
dictionary in the ``fields`` argument provided to
:meth:`~poolmanager.PoolManager.request`::

    >>> r = http.request(
    ...     'POST',
    ...     'http://httpbin.org/post',
    ...     fields={'field': 'value'})
    >>> json.loads(r.data.decode('utf-8'))['form']
    {'field': 'value'}

JSON
~~~~

You can sent JSON a request by specifying the encoded data as the `body`
argument and setting the ``Content-Type`` header when calling 
:meth:`~poolmanager.PoolManager.request`::

    >>> import json
    >>> data = {'attribute': 'value'}
    >>> encoded_data = json.dumps(data)
    >>> r = http.request(
    ...     'POST',
    ...     'http://httpbin.org/post',
    ...     body=encoded_data,
    ...     headers={'Content-Type': 'application/json'})
    >>> json.loads(r.data.decode('utf-8'))['json']
    {'attribute': 'value'}

Files & binary data
~~~~~~~~~~~~~~~~~~~

SSL Verification
----------------

Using timeouts
--------------

Retrying requests
-----------------

Logging
-------

Errors & Exceptions
-------------------

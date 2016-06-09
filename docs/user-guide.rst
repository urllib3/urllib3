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
    'User-agent: *\nDisallow: /deny\n'

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

JSON content
~~~~~~~~~~~~

Binary content
~~~~~~~~~~~~~~

.. _request_data:

Request data
------------

Query parameters
~~~~~~~~~~~~~~~~

Headers
~~~~~~~

Form data
~~~~~~~~~

JSON
~~~~

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

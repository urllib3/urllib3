Advanced Usage
==============

.. currentmodule:: urllib3

TODO: This section is under construction and stuff may move around.
Please review for accuracy, not organization.

.. _stream:

Streaming and IO
----------------

When dealing with large responses it's often better to stream the response
content::

    >>> r = http.request(
    ...     'GET',
    ...     'http://httpbin.org/bytes/1024',
    ...     preload_content=False)
    >>> for chunk in r.stream(32):
    ...     print(chunk)
    b'...'
    b'...'
    ...
    >>> r.release_conn()

Setting ``preload_content`` to ``False`` means that urllib3 will stream the
response content. :meth:`~response.HTTPResponse.stream` lets you iterate over
chunks of the response content.

.. note:: When using ``preload_content=False``, you should call 
    :meth:`~response.HTTPResponse.release_conn` to release the http connection
    back to the connection pool so that it can be re-used.

However, you can also treat the :class:`~response.HTTPResponse` instance as
a file-like object. This allows you to do buffering::

    >>> import io
    >>> r = http.request(
    ...     'GET',
    ...     'http://httpbin.org/bytes/1024',
    ...     preload_content=False)
    >>> r.read(4)
    b'\x88\x1f\x8b\xe5'

Calls to :meth:`~response.HTTPResponse.read()` will block until more response
data is available. 

    >>> reader = io.BufferedReader(r, 8)
    >>> reader.read(4)
    >>> r.release_conn()

You can use this file-like objects to do things like decode the content using
:mod:`codecs`::

    >>> import codecs
    >>> reader = codecs.getreader('utf-8')
    >>> r = http.request(
    ...     'GET',
    ...     'http://httpbin.org/ip',
    ...     preload_content=False)
    >>> json.load(reader(r))
    {'origin': '127.0.0.1'}
    >>> r.release_conn()

.. _ssl_mac:

Certificate validation and Mac OS X
-----------------------------------

Apple-provided Python and OpenSSL libraries contain a patches that make them
automatically check the system keychain's certificates. This can be
surprising if you specify custom certificates and see requests unexpectedly
succeed. See this
`article <https://hynek.me/articles/apple-openssl-verification-surprises/>`_
for more information.

.. _ssl_warnings:

SSL Warnings
------------

urllib3 will issue several different warnings based on the level of certificate
verification support. These warning indicate particular situations and can
resolved in different ways.

* :class:`~exceptions.InsecureRequestWarning`
    This happens when an request is made to an HTTPS URL without certificate
    verification enabled. Follow the :ref:`certificate verification <ssl>`
    guide to resolve this warning.
* :class:`~exceptions.InsecurePlatformWarning`
    This happens on Python 2 platforms that have an outdated :mod:`ssl` module.
    These older :mod:`ssl` can cause some insecure requests to succeed where
    they should fail and secure requests to fail where they should succeed.
    Follow the :ref:`pyOpenSSL <ssl_py2>` guide to resolve this warning.

.. _sni_warning:

* :class:`~exceptions.SNIMissingWarning`
    This happens on Python 2 versions older than 2.7.9 and older versions of
    pyOpenSSL. These older versions lack
    `SNI <https://en.wikipedia.org/wiki/Server_Name_Indication>`_ support. This
    can cause servers to present a certificate that the client thinks is
    invalid. Follow the :ref:`pyOpenSSL <ssl_py2>` guide to resolve this
    warning.

.. _disable_ssl_warnings:

Making unverified HTTPS requests is **strongly** discouraged, however, if you
understand the risks and wish to disable these warnings, you can use :func:`~urllib3.disable_warnings`::

    >>> import urllib3
    >>> urllib3.disable_warnings()

Alternatively you can capture the warnings with the standard :mod:`logging` module::

    >>> logging.captureWarnings(True)

Finally, you can suppress the warnings at the interpreter level by setting the
``PYTHONWARNINGS`` environment variable or by using the
`-W flag <https://docs.python.org/2/using/cmdline.html#cmdoption-W>`_.

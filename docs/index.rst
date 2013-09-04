=====================
urllib3 Documentation
=====================

.. toctree::
   :hidden:

   pools
   managers
   helpers
   collections
   contrib


Highlights
==========

- Re-use the same socket connection for multiple requests, with optional
  client-side certificate verification. See:
  :class:`~urllib3.connectionpool.HTTPConnectionPool` and
  :class:`~urllib3.connectionpool.HTTPSConnectionPool`

- File posting. See:
  :func:`~urllib3.filepost.encode_multipart_formdata`

- Built-in redirection and retries (optional).

- Supports gzip and deflate decoding. See:
  :func:`~urllib3.response.decode_gzip` and
  :func:`~urllib3.response.decode_deflate`

- Thread-safe and sanity-safe.

- Tested on Python 2.6+ and Python 3.2+, 100% unit test coverage.

- Works with AppEngine, gevent, and eventlib.

- Small and easy to understand codebase perfect for extending and building upon.
  For a more comprehensive solution, have a look at
  `Requests <http://python-requests.org/>`_ which is also powered by urllib3.


Getting Started
===============

Installing
----------

``pip install urllib3`` or fetch the latest source from
`github.com/shazow/urllib3 <https://github.com/shazow/urllib3>`_.

Usage
-----

::

    >>> import urllib3
    >>> http = urllib3.PoolManager()
    >>> r = http.request('GET', 'http://google.com/')
    >>> r.status
    200
    >>> r.headers['server']
    'gws'
    >>> r.data
    ...

Components
==========

:mod:`urllib3` tries to strike a fine balance between power, extendability, and
sanity. To achieve this, the codebase is a collection of small reusable
utilities and abstractions composed together in a few helpful layers.

PoolManager
-----------

The highest level is the :doc:`PoolManager(...) <managers>`.

The :class:`~urllib3.poolmanagers.PoolManager` will take care of reusing
connections for you whenever you request the same host. this should cover most
scenarios without significant loss of efficiency, but you can always drop down
to a lower level component for more granular control.

::

    >>> http = urllib3.PoolManager(10)
    >>> r1 = http.request('GET', 'http://google.com/')
    >>> r2 = http.request('GET', 'http://google.com/mail')
    >>> r3 = http.request('GET', 'http://yahoo.com/')
    >>> len(http.pools)
    2

A :class:`~urllib3.poolmanagers.PoolManager` is a proxy for a collection of
:class:`ConnectionPool` objects. They both inherit from
:class:`~urllib3.request.RequestMethods` to make sure that their API is
similar, so that instances of either can be passed around interchangeably.

ProxyManager
------------

The :class:`~urllib3.poolmanagers.ProxyManager` is an HTTP proxy-aware
subclass of :class:`~urllib3.poolmanagers.PoolManager`. It produces a single
:class:`~urllib3.connectionpool.HTTPConnectionPool` instance for all HTTP
connections and individual per-server:port
:class:`~urllib3.connectionpool.HTTPSConnectionPool` instances for tunnelled
HTTPS connections:

::

    >>> proxy = urllib3.ProxyManager('http://localhost:3128/')
    >>> r1 = proxy.request('GET', 'http://google.com/')
    >>> r2 = proxy.request('GET', 'http://httpbin.org/')
    >>> len(proxy.pools)
    1
    >>> r3 = proxy.request('GET', 'https://httpbin.org/')
    >>> r4 = proxy.request('GET', 'https://twitter.com/')
    >>> len(proxy.pools)
    3

ConnectionPool
--------------

The next layer is the :doc:`ConnectionPool(...) <pools>`.

The :class:`~urllib3.connectionpool.HTTPConnectionPool` and
:class:`~urllib3.connectionpool.HTTPSConnectionPool` classes allow you to
define a pool of connections to a single host and make requests against this
pool with automatic **connection reusing** and **thread safety**.

When the :mod:`ssl` module is available, then
:class:`~urllib3.connectionpool.HTTPSConnectionPool` objects can be configured
to check SSL certificates against specific provided certificate authorities. ::

    >>> conn = urllib3.connection_from_url('http://www.google.com')
    >>> r1 = conn.request('GET', 'http://www.google.com/')
    >>> r2 = conn.request('GET', '/search')
    >>> r3 = conn.request('GET', 'http://wwww.yahoo.com/')
    Traceback (most recent call last)
      ...
    HostChangedError: Connection pool with host 'http://google.com' tried to
    open a foreign host: http://yahoo.com/

Again, a ConnectionPool is a pool of connections to a specific host. Trying to
access a different host through the same pool will raise a ``HostChangedError``
exception unless you specify ``assert_same_host=False``. Do this at your own
risk as the outcome is completely dependent on the behaviour of the host server.

If you need to access multiple hosts and don't want to manage your own
collection of :class:`~urllib3.connectionpool.ConnectionPool` objects, then you
should use a :class:`~urllib3.poolmanager.PoolManager`.

A :class:`~urllib3.connectionpool.ConnectionPool` is composed of a collection
of :class:`httplib.HTTPConnection` objects.

Foundation
----------

At the very core, just like its predecessors, :mod:`urllib3` is built on top of
:mod:`httplib` -- the lowest level HTTP library included in the Python
standard library.

To aid the limited functionality of the :mod:`httplib` module, :mod:`urllib3`
provides various helper methods which are used with the higher level components
but can also be used independently.

.. toctree::

   helpers

Contrib Modules
---------------

These modules implement various extra features, that may not be ready for
prime time.

.. toctree::

   contrib

Contributing
============

#. `Check for open issues <https://github.com/shazow/urllib3/issues>`_ or open
   a fresh issue to start a discussion around a feature idea or a bug. There is
   a *Contributor Friendly* tag for issues that should be ideal for people who
   are not very familiar with the codebase yet.
#. Fork the `urllib3 repository on Github <https://github.com/shazow/urllib3>`_
   to start making your changes.
#. Write a test which shows that the bug was fixed or that the feature works
   as expected.
#. Send a pull request and bug the maintainer until it gets merged and published.
   :) Make sure to add yourself to ``CONTRIBUTORS.txt``.

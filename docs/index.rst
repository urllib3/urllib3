=====================
urllib3 Documentation
=====================

.. toctree::
   :hidden:

   pools
   managers
   security
   helpers
   exceptions
   collections
   contrib
   recipes


Highlights
==========

- Re-use the same socket connection for multiple requests, with optional
  client-side certificate verification. See:
  :class:`~urllib3.connectionpool.HTTPConnectionPool` and
  :class:`~urllib3.connectionpool.HTTPSConnectionPool`

- File posting with multipart encoding. See:
  :func:`~urllib3.filepost.encode_multipart_formdata`

- Built-in redirection and retries (optional).

- Supports gzip and deflate decoding. See:
  :func:`~urllib3.response.decode_gzip` and
  :func:`~urllib3.response.decode_deflate`

- Thread-safe and sanity-safe.

- Proxy over :ref:`HTTP or SOCKS <proxymanager>`.

- Tested on Python 2.6+ and Python 3.2+, 100% unit test coverage.

- Works with AppEngine, gevent, eventlib, and the standard library :mod:`io` module.

- Small and easy to understand codebase perfect for extending and building upon.
  For a simplified abstraction, have a look at
  `Requests <http://python-requests.org/>`_ which is also powered by urllib3.


Getting Started
===============

Installing
----------

``pip install urllib3`` or fetch the latest source from
`github.com/shazow/urllib3 <https://github.com/shazow/urllib3>`_.

Usage
-----

.. doctest ::

    >>> import urllib3
    >>> http = urllib3.PoolManager()
    >>> r = http.request('GET', 'http://example.com/')
    >>> r.status
    200
    >>> r.headers['server']
    'ECS (iad/182A)'
    >>> 'data: ' + r.data
    'data: ...'


**By default, urllib3 does not verify your HTTPS requests**.
You'll need to supply a root certificate bundle, or use `certifi
<https://certifi.io/>`_

.. doctest ::

    >>> import urllib3, certifi
    >>> http = urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
    >>> r = http.request('GET', 'https://insecure.com/')
    Traceback (most recent call last):
      ...
    SSLError: hostname 'insecure.com' doesn't match 'svn.nmap.org'

For more on making secure SSL/TLS HTTPS requests, read the :ref:`Security
section <security>`.


urllib3's responses respect the :mod:`io` framework from Python's
standard library, allowing use of these standard objects for purposes
like buffering:

.. doctest ::

    >>> http = urllib3.PoolManager()
    >>> r = http.urlopen('GET','http://example.com/', preload_content=False)
    >>> b = io.BufferedReader(r, 2048)
    >>> firstpart = b.read(100)
    >>> # ... your internet connection fails momentarily ...
    >>> secondpart = b.read()


The response can be treated as a file-like object.
A file can be downloaded directly to a local file in a context without
being saved in memory.

.. doctest ::

    >>> url = 'http://example.com/file'
    >>> http = urllib3.PoolManager()
    >>> with http.request('GET', url, preload_content=False) as r, open('filename', 'wb') as fp:
    >>> ....    shutil.copyfileobj(r, fp)


Upgrading & Versioning
----------------------

urllib3 uses a compatibility-based versioning scheme (let's call it
*compatver*). For the user, they indicate the required decision for upgrading.

Given a version ``A.B.C``:

``C.`` Strictly backwards-compatible, usually a bug-fix. **Always upgrade.**

``B.`` Possibly partially incompatible, usually a new feature or a minor API
improvement. **Read the changelog and upgrade when ready.**

``A.`` Major rewrite and possibly breaks everything. Not really an upgrade,
basically a new library under the same namespace, decide if you want to switch.

For example, when going from urllib3 v1.2.3 to v1.2.4, you should always
upgrade without hesitation. When going from v1.2 to v1.3, you should read the
changes to make sure they're not going to affect you.


Components
==========

:mod:`urllib3` tries to strike a fine balance between power, extendability, and
sanity. To achieve this, the codebase is a collection of small reusable
utilities and abstractions composed together in a few helpful layers.


PoolManager
-----------

The highest level is the :doc:`PoolManager(...) <managers>`.

The :class:`~urllib3.poolmanagers.PoolManager` will take care of reusing
connections for you whenever you request the same host. This should cover most
scenarios without significant loss of efficiency, but you can always drop down
to a lower level component for more granular control.

.. doctest ::

    >>> import urllib3
    >>> http = urllib3.PoolManager(10)
    >>> r1 = http.request('GET', 'http://example.com/')
    >>> r2 = http.request('GET', 'http://httpbin.org/')
    >>> r3 = http.request('GET', 'http://httpbin.org/get')
    >>> len(http.pools)
    2

A :class:`~urllib3.poolmanagers.PoolManager` is a proxy for a collection of
:class:`ConnectionPool` objects. They both inherit from
:class:`~urllib3.request.RequestMethods` to make sure that their API is
similar, so that instances of either can be passed around interchangeably.


.. _proxymanager:

ProxyManager
------------

HTTP Proxy
~~~~~~~~~~

The :class:`~urllib3.poolmanagers.ProxyManager` is an HTTP proxy-aware
subclass of :class:`~urllib3.poolmanagers.PoolManager`. It produces a single
:class:`~urllib3.connectionpool.HTTPConnectionPool` instance for all HTTP
connections and individual per-``server:port``
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


SOCKS Proxy
~~~~~~~~~~~

The :ref:`contrib module <socks>` includes support for a :class:`SOCKSProxyManager <urllib3.contrib.socks.SOCKSProxyManager>`.


ConnectionPool
--------------

The next layer is the :doc:`ConnectionPool(...) <pools>`.

The :class:`~urllib3.connectionpool.HTTPConnectionPool` and
:class:`~urllib3.connectionpool.HTTPSConnectionPool` classes allow you to
define a pool of connections to a single host and make requests against this
pool with automatic **connection reusing** and **thread safety**.

When the :mod:`ssl` module is available, then
:class:`~urllib3.connectionpool.HTTPSConnectionPool` objects can be configured
to check SSL certificates against specific provided certificate authorities.

.. doctest ::

    >>> import urllib3
    >>> conn = urllib3.connection_from_url('http://httpbin.org/')
    >>> r1 = conn.request('GET', 'http://httpbin.org/')
    >>> r2 = conn.request('GET', '/user-agent')
    >>> r3 = conn.request('GET', 'http://example.com')
    Traceback (most recent call last):
      ...
    urllib3.exceptions.HostChangedError: HTTPConnectionPool(host='httpbin.org', port=None): Tried to open a foreign host with url: http://example.com

Again, a ConnectionPool is a pool of connections to a specific host. Trying to
access a different host through the same pool will raise a ``HostChangedError``
exception unless you specify ``assert_same_host=False``. Do this at your own
risk as the outcome is completely dependent on the behaviour of the host server.

If you need to access multiple hosts and don't want to manage your own
collection of :class:`~urllib3.connectionpool.ConnectionPool` objects, then you
should use a :class:`~urllib3.poolmanager.PoolManager`.

A :class:`~urllib3.connectionpool.ConnectionPool` is composed of a collection
of :class:`httplib.HTTPConnection` objects.


Timeout
-------

A timeout can be set to abort socket operations on individual connections after
the specified duration. The timeout can be defined as a float or an instance of
:class:`~urllib3.util.timeout.Timeout` which gives more granular configuration
over how much time is allowed for different stages of the request. This can be
set for the entire pool or per-request.

.. doctest ::

    >>> from urllib3 import PoolManager, Timeout

    >>> # Manager with 3 seconds combined timeout.
    >>> http = PoolManager(timeout=3.0)
    >>> r = http.request('GET', 'http://httpbin.org/delay/1')

    >>> # Manager with 2 second timeout for the read phase, no limit for the rest.
    >>> http = PoolManager(timeout=Timeout(read=2.0))
    >>> r = http.request('GET', 'http://httpbin.org/delay/1')

    >>> # Manager with no timeout but a request with a timeout of 1 seconds for
    >>> # the connect phase and 2 seconds for the read phase.
    >>> http = PoolManager()
    >>> r = http.request('GET', 'http://httpbin.org/delay/1', timeout=Timeout(connect=1.0, read=2.0))

    >>> # Same Manager but request with a 5 second total timeout.
    >>> r = http.request('GET', 'http://httpbin.org/delay/1', timeout=Timeout(total=5.0))

See the :class:`~urllib3.util.timeout.Timeout` definition for more details.


Retry
-----

Retries can be configured by passing an instance of
:class:`~urllib3.util.retry.Retry`, or disabled by passing ``False``, to the
``retries`` parameter.

Redirects are also considered to be a subset of retries but can be configured or
disabled individually.

::

    >>> from urllib3 import PoolManager, Retry

    >>> # Allow 3 retries total for all requests in this pool. These are the same:
    >>> http = PoolManager(retries=3)
    >>> http = PoolManager(retries=Retry(3))
    >>> http = PoolManager(retries=Retry(total=3))

    >>> r = http.request('GET', 'http://httpbin.org/redirect/2')
    >>> # r.status -> 200

    >>> # Disable redirects for this request.
    >>> r = http.request('GET', 'http://httpbin.org/redirect/2', retries=Retry(3, redirect=False))
    >>> # r.status -> 302

    >>> # No total limit, but only do 5 connect retries, for this request.
    >>> r = http.request('GET', 'http://httpbin.org/', retries=Retry(connect=5))


See the :class:`~urllib3.util.retry.Retry` definition for more details.


Stream
------

You may also stream your response and get data as they come (e.g. when using
``transfer-encoding: chunked``). In this case, method
:func:`~urllib3.response.HTTPResponse.stream` will return generator.

::

    >>> import urllib3
    >>> http = urllib3.PoolManager()

    >>> r = http.request("GET", "http://httpbin.org/stream/3")
    >>> r.getheader("transfer-encoding")
    'chunked'

    >>> for chunk in r.stream():
    ... print chunk
    {"url": "http://httpbin.org/stream/3", ..., "id": 0, ...}
    {"url": "http://httpbin.org/stream/3", ..., "id": 1, ...}
    {"url": "http://httpbin.org/stream/3", ..., "id": 2, ...}
    >>> r.closed
    True

Completely consuming the stream will auto-close the response and release
the connection back to the pool. If you're only partially consuming the
consuming a stream, make sure to manually call ``r.close()`` on the
response.

Foundation
----------

At the very core, just like its predecessors, :mod:`urllib3` is built on top of
:mod:`httplib` -- the lowest level HTTP library included in the Python
standard library.

To aid the limited functionality of the :mod:`httplib` module, :mod:`urllib3`
provides various helper methods which are used with the higher level components
but can also be used independently.

* :ref:`helpers`
* :ref:`exceptions`


Contrib Modules
---------------

These modules implement various extra features, that may not be ready for
prime time or that require optional third-party dependencies.

* :ref:`contrib-modules`


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


Sponsorship
===========

Please consider sponsoring urllib3 development, especially if your company
benefits from this library.

We welcome your patronage on `Bountysource <https://www.bountysource.com/teams/urllib3>`_:

* `Contribute a recurring amount to the team <https://salt.bountysource.com/checkout/amount?team=urllib3>`_
* `Place a bounty on a specific feature <https://www.bountysource.com/teams/urllib3>`_

Your contribution will go towards adding new features to urllib3 and making
sure all functionality continues to meet our high quality standards.


Project Grant
-------------

A grant for contiguous full-time development has the biggest impact for
progress. Periods of 3 to 10 days allow a contributor to tackle substantial
complex issues which are otherwise left to linger until somebody can't afford
to not fix them.

Contact `@shazow <https://github.com/shazow>`_ to arrange a grant for a core
contributor.

Huge thanks to all the companies and individuals who financially contributed to
the development of urllib3. Please send a PR if you've donated and would like
to be listed.

* `Stripe <https://stripe.com/>`_ (June 23, 2014)

.. * [Company] ([date])

=====================
urllib4 Documentation
=====================

.. toctree::
   :hidden:

   pools
   managers
   security
   helpers
   collections
   contrib
   security


Highlights
==========

- Re-use the same socket connection for multiple requests, with optional
  client-side certificate verification. See:
  :class:`~urllib4.connectionpool.HTTPConnectionPool` and
  :class:`~urllib4.connectionpool.HTTPSConnectionPool`

- File posting. See:
  :func:`~urllib4.filepost.encode_multipart_formdata`

- Built-in redirection and retries (optional).

- Supports gzip and deflate decoding. See:
  :func:`~urllib4.response.decode_gzip` and
  :func:`~urllib4.response.decode_deflate`

- Thread-safe and sanity-safe.

- Tested on Python 2.6+ and Python 3.2+, 100% unit test coverage.

- Works with AppEngine, gevent, eventlib, and the standard library :mod:`io` module.

- Small and easy to understand codebase perfect for extending and building upon.
  For a more comprehensive solution, have a look at
  `Requests <http://python-requests.org/>`_ which is also powered by urllib4.


Getting Started
===============

Installing
----------

``pip install urllib4`` or fetch the latest source from
`github.com/shazow/urllib4 <https://github.com/shazow/urllib4>`_.

Usage
-----

.. doctest ::

    >>> import urllib4
    >>> http = urllib4.PoolManager()
    >>> r = http.request('GET', 'http://example.com/')
    >>> r.status
    200
    >>> r.headers['server']
    'ECS (iad/182A)'
    >>> 'data: ' + r.data
    'data: ...'


**By default, urllib4 does not verify your HTTPS requests**.
You'll need to supply a root certificate bundle, or use `certifi
<https://certifi.io/>`_

.. doctest ::

    >>> import urllib4, certifi
    >>> http = urllib4.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=certifi.where())
    >>> r = http.request('GET', 'https://insecure.com/')
    Traceback (most recent call last):
      ...
    SSLError: hostname 'insecure.com' doesn't match 'svn.nmap.org'

For more on making secure SSL/TLS HTTPS requests, read the :ref:`Security
section <security>`.


urllib4's responses respect the :mod:`io` framework from Python's
standard library, allowing use of these standard objects for purposes
like buffering:

.. doctest ::

    >>> http = urllib4.PoolManager()
    >>> r = http.urlopen('GET','http://example.com/', preload_content=False)
    >>> b = io.BufferedReader(r, 2048)
    >>> firstpart = b.read(100)
    >>> # ... your internet connection fails momentarily ...
    >>> secondpart = b.read()


Components
==========

:mod:`urllib4` tries to strike a fine balance between power, extendability, and
sanity. To achieve this, the codebase is a collection of small reusable
utilities and abstractions composed together in a few helpful layers.


PoolManager
-----------

The highest level is the :doc:`PoolManager(...) <managers>`.

The :class:`~urllib4.poolmanagers.PoolManager` will take care of reusing
connections for you whenever you request the same host. This should cover most
scenarios without significant loss of efficiency, but you can always drop down
to a lower level component for more granular control.

.. doctest ::

    >>> import urllib4
    >>> http = urllib4.PoolManager(10)
    >>> r1 = http.request('GET', 'http://example.com/')
    >>> r2 = http.request('GET', 'http://httpbin.org/')
    >>> r3 = http.request('GET', 'http://httpbin.org/get')
    >>> len(http.pools)
    2

A :class:`~urllib4.poolmanagers.PoolManager` is a proxy for a collection of
:class:`ConnectionPool` objects. They both inherit from
:class:`~urllib4.request.RequestMethods` to make sure that their API is
similar, so that instances of either can be passed around interchangeably.


ProxyManager
------------

The :class:`~urllib4.poolmanagers.ProxyManager` is an HTTP proxy-aware
subclass of :class:`~urllib4.poolmanagers.PoolManager`. It produces a single
:class:`~urllib4.connectionpool.HTTPConnectionPool` instance for all HTTP
connections and individual per-server:port
:class:`~urllib4.connectionpool.HTTPSConnectionPool` instances for tunnelled
HTTPS connections:

::

    >>> proxy = urllib4.ProxyManager('http://localhost:3128/')
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

The :class:`~urllib4.connectionpool.HTTPConnectionPool` and
:class:`~urllib4.connectionpool.HTTPSConnectionPool` classes allow you to
define a pool of connections to a single host and make requests against this
pool with automatic **connection reusing** and **thread safety**.

When the :mod:`ssl` module is available, then
:class:`~urllib4.connectionpool.HTTPSConnectionPool` objects can be configured
to check SSL certificates against specific provided certificate authorities.

.. doctest ::

    >>> import urllib4
    >>> conn = urllib4.connection_from_url('http://httpbin.org/')
    >>> r1 = conn.request('GET', 'http://httpbin.org/')
    >>> r2 = conn.request('GET', '/user-agent')
    >>> r3 = conn.request('GET', 'http://example.com')
    Traceback (most recent call last):
      ...
    urllib4.exceptions.HostChangedError: HTTPConnectionPool(host='httpbin.org', port=None): Tried to open a foreign host with url: http://example.com

Again, a ConnectionPool is a pool of connections to a specific host. Trying to
access a different host through the same pool will raise a ``HostChangedError``
exception unless you specify ``assert_same_host=False``. Do this at your own
risk as the outcome is completely dependent on the behaviour of the host server.

If you need to access multiple hosts and don't want to manage your own
collection of :class:`~urllib4.connectionpool.ConnectionPool` objects, then you
should use a :class:`~urllib4.poolmanager.PoolManager`.

A :class:`~urllib4.connectionpool.ConnectionPool` is composed of a collection
of :class:`httplib.HTTPConnection` objects.


Timeout
-------

A timeout can be set to abort socket operations on individual connections after
the specified duration. The timeout can be defined as a float or an instance of
:class:`~urllib4.util.timeout.Timeout` which gives more granular configuration
over how much time is allowed for different stages of the request. This can be
set for the entire pool or per-request.

.. doctest ::

    >>> from urllib4 import PoolManager, Timeout

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

See the :class:`~urllib4.util.timeout.Timeout` definition for more details.


Retry
-----

Retries can be configured by passing an instance of
:class:`~urllib4.util.retry.Retry`, or disabled by passing ``False``, to the
``retries`` parameter.

Redirects are also considered to be a subset of retries but can be configured or
disabled individually.

::

    >>> from urllib4 import PoolManager, Retry

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


See the :class:`~urllib4.util.retry.Retry` definition for more details.


Stream
------

You may also stream your response and get data as they come (e.g. when using
``transfer-encoding: chunked``). In this case, method
:func:`~urllib4.response.HTTPResponse.stream` will return generator.

::

    >>> from urllib4 import PoolManager
    >>> http = urllib4.PoolManager()

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

At the very core, just like its predecessors, :mod:`urllib4` is built on top of
:mod:`httplib` -- the lowest level HTTP library included in the Python
standard library.

To aid the limited functionality of the :mod:`httplib` module, :mod:`urllib4`
provides various helper methods which are used with the higher level components
but can also be used independently.

.. toctree::

   helpers
   exceptions


Contrib Modules
---------------

These modules implement various extra features, that may not be ready for
prime time.

.. toctree::

   contrib


Contributing
============

#. `Check for open issues <https://github.com/shazow/urllib4/issues>`_ or open
   a fresh issue to start a discussion around a feature idea or a bug. There is
   a *Contributor Friendly* tag for issues that should be ideal for people who
   are not very familiar with the codebase yet.
#. Fork the `urllib4 repository on Github <https://github.com/shazow/urllib4>`_
   to start making your changes.
#. Write a test which shows that the bug was fixed or that the feature works
   as expected.
#. Send a pull request and bug the maintainer until it gets merged and published.
   :) Make sure to add yourself to ``CONTRIBUTORS.txt``.


Sponsorship
===========

Please consider sponsoring urllib4 development, especially if your company
benefits from this library.

* **Project Grant**: A grant for contiguous full-time development has the
  biggest impact for progress. Periods of  3 to 10 days allow a contributor to
  tackle substantial complex issues which are otherwise left to linger until
  somebody can't afford to not fix them.

  Contact `@shazow <https://github.com/shazow>`_ to arrange a grant for a core
  contributor.

* **One-off**: Development will continue regardless of funding, but donations help move
  things further along quicker as the maintainer can allocate more time off to
  work on urllib4 specifically.

  .. raw:: html

    <a href="https://donorbox.org/personal-sponsor-urllib4" style="background-color:#1275ff;color:#fff;text-decoration:none;font-family:Verdana,sans-serif;display:inline-block;font-size:14px;padding:7px 16px;border-radius:5px;margin-right:2em;vertical-align:top;border:1px solid rgba(160,160,160,0.5);background-image:linear-gradient(#7dc5ee,#008cdd 85%,#30a2e4);box-shadow:inset 0 1px 0 rgba(255,255,255,0.25);">Sponsor with Credit Card</a>

    <a class="coinbase-button" data-code="137087702cf2e77ce400d53867b164e6" href="https://coinbase.com/checkouts/137087702cf2e77ce400d53867b164e6">Sponsor with Bitcoin</a><script src="https://coinbase.com/assets/button.js" type="text/javascript"></script>

* **Recurring**: You're welcome to `support the maintainer on Gittip
  <https://www.gittip.com/shazow/>`_.


Recent Sponsors
---------------

Huge thanks to all the companies and individuals who financially contributed to
the development of urllib4. Please send a PR if you've donated and would like
to be listed.

* `Stripe <https://stripe.com/>`_ (June 23, 2014)

.. * [Company] ([optional tagline]), [optional description of grant] ([date])

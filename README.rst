=======
urllib3
=======

.. image:: https://travis-ci.org/shazow/urllib3.png?branch=master
        :target: https://travis-ci.org/shazow/urllib3

.. image:: https://www.bountysource.com/badge/tracker?tracker_id=192525
        :target: https://www.bountysource.com/trackers/192525-urllib3?utm_source=192525&utm_medium=shield&utm_campaign=TRACKER_BADGE


Highlights
==========

- Re-use the same socket connection for multiple requests
  (``HTTPConnectionPool`` and ``HTTPSConnectionPool``)
  (with optional client-side certificate verification).
- File posting (``encode_multipart_formdata``).
- Built-in redirection and retries (optional).
- Supports gzip and deflate decoding.
- Proxy over HTTP or SOCKS.
- Thread-safe and sanity-safe.
- Works with AppEngine, gevent, and eventlib.
- Tested on Python 2.6+, Python 3.3+, and PyPy, with 100% unit test coverage.
- Small and easy to understand codebase perfect for extending and building upon.
  For a more comprehensive solution, have a look at
  `Requests <http://python-requests.org/>`_ which is also powered by ``urllib3``.


You might already be using urllib3!
===================================

``urllib3`` powers `many great Python libraries
<https://sourcegraph.com/search?q=package+urllib3>`_, including ``pip`` and
``requests``.


What's wrong with urllib and urllib2?
=====================================

There are two critical features missing from the Python standard library:
Connection re-using/pooling and file posting. It's not terribly hard to
implement these yourself, but it's much easier to use a module that already
did the work for you.

The Python standard libraries ``urllib`` and ``urllib2`` have little to do
with each other. They were designed to be independent and standalone, each
solving a different scope of problems, and ``urllib3`` follows in a similar
vein.


Why do I want to reuse connections?
===================================

Performance. When you normally do a urllib call, a separate socket
connection is created with each request. By reusing existing sockets
(supported since HTTP 1.1), the requests will take up less resources on the
server's end, and also provide a faster response time at the client's end.
With some simple benchmarks (see `test/benchmark.py
<https://github.com/shazow/urllib3/blob/master/test/benchmark.py>`_
), downloading 15 URLs from google.com is about twice as fast when using
HTTPConnectionPool (which uses 1 connection) than using plain urllib (which
uses 15 connections).

This library is perfect for:

- Talking to an API
- Crawling a website
- Any situation where being able to post files, handle redirection, and
  retrying is useful. It's relatively lightweight, so it can be used for
  anything!


Examples
========

Go to `urllib3.readthedocs.org <https://urllib3.readthedocs.io>`_
for more nice syntax-highlighted examples.

But, long story short::

  import urllib3

  http = urllib3.PoolManager()

  r = http.request('GET', 'http://google.com/')

  print r.status, r.data

The ``PoolManager`` will take care of reusing connections for you whenever
you request the same host. For more fine-grained control of your connection
pools, you should look at `ConnectionPool
<https://urllib3.readthedocs.io/#connectionpool>`_.


Run the tests
=============

We use some external dependencies, multiple interpreters and code coverage
analysis while running test suite. Our ``Makefile`` handles much of this for
you as long as you're running it `inside of a virtualenv
<http://docs.python-guide.org/en/latest/dev/virtualenvs/>`_::

  $ make test
  [... magically installs dependencies and runs tests on your virtualenv]
  Ran 182 tests in 1.633s

  OK (SKIP=6)

Note that code coverage less than 100% is regarded as a failing run. Some
platform-specific tests are skipped unless run in that platform.  To make sure
the code works in all of urllib3's supported platforms, you can run our ``tox``
suite::

  $ make test-all
  [... tox creates a virtualenv for every platform and runs tests inside of each]
  py26: commands succeeded
  py27: commands succeeded
  py32: commands succeeded
  py33: commands succeeded
  py34: commands succeeded

Our test suite `runs continuously on Travis CI
<https://travis-ci.org/shazow/urllib3>`_ with every pull request.


Contributing
============

Thank you for giving back to urllib3. Please meet our jolly team
of code-sherpas:

Maintainers
-----------

- `@lukasa <https://github.com/lukasa>`_ (Cory Benfield)
- `@sigmavirus24 <https://github.com/sigmavirus24>`_ (Ian Cordasco)
- `@shazow <https://github.com/shazow>`_ (Andrey Petrov)

👋

Getting Started
---------------

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

If your company benefits from this library, please consider `sponsoring its
development <https://urllib3.readthedocs.io/en/latest/#sponsorship>`_.

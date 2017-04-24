urllib3
=======

.. image:: https://travis-ci.org/shazow/urllib3.svg?branch=master
        :alt: Build status on Travis
        :target: https://travis-ci.org/shazow/urllib3

.. image:: https://img.shields.io/appveyor/ci/shazow/urllib3/master.svg
        :alt: Build status on AppVeyor
        :target: https://ci.appveyor.com/project/shazow/urllib3

.. image:: https://readthedocs.org/projects/urllib3/badge/?version=latest
        :alt: Documentation Status
        :target: https://urllib3.readthedocs.io/en/latest/
        
.. image:: https://img.shields.io/codecov/c/github/shazow/urllib3.svg
        :alt: Coverage Status
        :target: https://codecov.io/gh/shazow/urllib3

.. image:: https://img.shields.io/pypi/v/urllib3.svg?maxAge=86400
        :alt: PyPI version
        :target: https://pypi.python.org/pypi/urllib3

.. image:: https://www.bountysource.com/badge/tracker?tracker_id=192525
        :alt: Bountysource
        :target: https://www.bountysource.com/trackers/192525-urllib3?utm_source=192525&utm_medium=shield&utm_campaign=TRACKER_BADGE

urllib3 is a powerful, *sanity-friendly* HTTP client for Python. Much of the
Python ecosystem already uses urllib3 and you should too.
urllib3 brings many critical features that are missing from the Python
standard libraries:

- Thread safety.
- Connection pooling.
- Client-side SSL/TLS verification.
- File uploads with multipart encoding.
- Helpers for retrying requests and dealing with HTTP redirects.
- Support for gzip and deflate encoding.
- Proxy support for HTTP and SOCKS.
- 100% test coverage.

urllib3 is powerful and easy to use::

    >>> import urllib3
    >>> http = urllib3.PoolManager()
    >>> r = http.request('GET', 'http://httpbin.org/robots.txt')
    >>> r.status
    200
    >>> r.data
    'User-agent: *\nDisallow: /deny\n'

Installing
----------

urllib3 can be installed with `pip <https://pip.pypa.io>`_::

    $ pip install urllib3

Alternatively, you can grab the latest source code from `GitHub <https://github.com/shazow/urllib3>`_::

    $ git clone git://github.com/shazow/urllib3.git
    $ python setup.py install


Documentation
-------------

urllib3 has usage and reference documentation at `urllib3.readthedocs.io <https://urllib3.readthedocs.io>`_.


Contributing
------------

urllib3 happily accepts contributions. Please see our
`contributing documentation <https://urllib3.readthedocs.io/en/latest/contributing.html>`_
for some tips on getting started.

Maintainers
-----------

- `@lukasa <https://github.com/lukasa>`_ (Cory Benfield)
- `@sigmavirus24 <https://github.com/sigmavirus24>`_ (Ian Cordasco)
- `@shazow <https://github.com/shazow>`_ (Andrey Petrov)

👋

Sponsorship
-----------

If your company benefits from this library, please consider `sponsoring its
development <https://urllib3.readthedocs.io/en/latest/contributing.html#sponsorship>`_.

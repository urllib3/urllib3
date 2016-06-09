urllib3
=======

.. toctree::
   :hidden:
   :maxdepth: 2

   user-guide
   advanced-usage
   reference/index
   contributing

Urllib3 is a *sanity-friendly* HTTP client for Python. It helps you avoid the
inevitable heartache and frustration of lower-level HTTP clients. It is the
magic beneath the fantastic `Requests <http://python-requests.org/>`_ library.
Notable features include:

- Thread safe.
- Connection pooling.
- Client-side SSL/TLS verification.
- File uploads with multipart encoding.
- Helpers for retrying requests and dealing with HTTP redirects.
- Support for gzip and deflate encoding.
- Proxy support for HTTP and SOCKS.
- 100% test coverage.

Urllib3 is both easy to use and powerful::

    >>> import urllib3
    >>> http = urllib3.PoolManager()
    >>> r = http.request('GET', 'http://httpbin.org/robots.txt')
    >>> r.status
    200
    >>> r.data
    'User-agent: *\nDisallow: /deny\n'

Installing
----------

Urllib3 can installed with `pip <https://pip.pypa.io>`_::

    $ pip install urllib3

Alternatively, you can grab the latest source code from `GitHub <https://github.com/shazow/urllib3>`_::

    $ git clone git://github.com/shazow/urllib3.git
    $ python setup.py install

Usage
-----

The :doc:`user-guide` is the place to go to learn how to use the library and
accomplish common tasks. The more in-depth :doc:`advanced-usage` guide is the place to go for lower-level tweaking.

The :doc:`reference/index` documentation provides API-level documentation.


License
-------

Urllib3 is made available under the MIT License. For more details, see `LICENSE.txt <https://github.com/shazow/urllib3/blob/master/LICENSE.txt>`_.

Contributing
------------

We happily welcome contributions, please see :doc:`contributing` for details.

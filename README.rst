urllib3
=======

.. image:: https://travis-ci.org/urllib3/urllib3.svg?branch=master
        :alt: Build status on Travis
        :target: https://travis-ci.org/urllib3/urllib3

.. image:: https://img.shields.io/appveyor/ci/urllib3/urllib3/master.svg
        :alt: Build status on AppVeyor
        :target: https://ci.appveyor.com/project/urllib3/urllib3

.. image:: https://readthedocs.org/projects/urllib3/badge/?version=latest
        :alt: Documentation Status
        :target: https://urllib3.readthedocs.io/en/latest/
        
.. image:: https://img.shields.io/codecov/c/github/urllib3/urllib3.svg
        :alt: Coverage Status
        :target: https://codecov.io/gh/urllib3/urllib3

.. image:: https://img.shields.io/pypi/v/urllib3.svg?maxAge=86400
        :alt: PyPI version
        :target: https://pypi.org/project/urllib3/

.. image:: https://badges.gitter.im/python-urllib3/Lobby.svg
        :alt: Gitter
        :target: https://gitter.im/python-urllib3/Lobby?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge

.. image:: https://tidelift.com/badges/github/urllib3/urllib3
        :alt: Tidelift Dependencies
        :target: https://tidelift.com/subscription/pkg/pypi-urllib3?utm_source=pypi-urllib3&utm_medium=referral&utm_campaign=docs

urllib3 is a powerful, *sanity-friendly* HTTP client for Python. Much of the
Python ecosystem already uses urllib3 and you should too.
urllib3 brings many critical features that are missing from the Python
standard libraries:

- Thread safety.
- Connection pooling.
- Client-side SSL/TLS verification.
- File uploads with multipart encoding.
- Helpers for retrying requests and dealing with HTTP redirects.
- Support for gzip, deflate, and brotli encoding.
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

Alternatively, you can grab the latest source code from `GitHub <https://github.com/urllib3/urllib3>`_::

    $ git clone git://github.com/urllib3/urllib3.git
    $ python setup.py install


Documentation
-------------

urllib3 has usage and reference documentation at `urllib3.readthedocs.io <https://urllib3.readthedocs.io>`_.


Contributing
------------

urllib3 happily accepts contributions. Please see our
`contributing documentation <https://urllib3.readthedocs.io/en/latest/contributing.html>`_
for some tips on getting started.


Security Disclosures
--------------------

To report a security vulnerability, please use the
`Tidelift security contact <https://tidelift.com/security>`_.
Tidelift will coordinate the fix and disclosure with maintainers.

Maintainers
-----------

- `@theacodes <https://github.com/theacodes>`_ (Thea Flowers)
- `@sethmlarson <https://github.com/sethmlarson>`_ (Seth M. Larson)
- `@haikuginger <https://github.com/haikuginger>`_ (Jesse Shapiro)
- `@lukasa <https://github.com/lukasa>`_ (Cory Benfield)
- `@sigmavirus24 <https://github.com/sigmavirus24>`_ (Ian Cordasco)
- `@shazow <https://github.com/shazow>`_ (Andrey Petrov)

👋


Sponsorship
-----------

.. |tideliftlogo| image:: https://nedbatchelder.com/pix/Tidelift_Logos_RGB_Tidelift_Shorthand_On-White_small.png
   :width: 75
   :alt: Tidelift

.. list-table::
   :widths: 10 100

   * - |tideliftlogo|
     - Professional support for urllib3 is available as part of the `Tidelift
       Subscription`_.  Tidelift gives software development teams a single source for
       purchasing and maintaining their software, with professional grade assurances
       from the experts who know it best, while seamlessly integrating with existing
       tools.

.. _Tidelift Subscription: https://tidelift.com/subscription/pkg/pypi-urllib3?utm_source=pypi-urllib3&utm_medium=referral&utm_campaign=readme

If your company benefits from this library, please consider `sponsoring its
development <https://urllib3.readthedocs.io/en/latest/contributing.html#sponsorship-project-grants>`_.

Sponsors include:

- Google Cloud Platform (2018-present), sponsors `@theacodes <https://github.com/theacodes>`_'s work on an ongoing basis
- Abbott (2018-present), sponsors `@sethmlarson <https://github.com/sethmlarson>`_'s work on an ongoing basis
- Akamai (2017-present), sponsors `@haikuginger <https://github.com/haikuginger>`_'s work on an ongoing basis
- Hewlett Packard Enterprise (2016-2017), sponsored `@Lukasa’s <https://github.com/Lukasa>`_ work on urllib3

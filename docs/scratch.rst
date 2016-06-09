
Installing
~~~~~~~~~~

``pip install urllib3`` or fetch the latest source from
`github.com/shazow/urllib3 <https://github.com/shazow/urllib3>`_.

Usage
~~~~~

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

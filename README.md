<h1 align="center">

![urllib3](https://github.com/urllib3/urllib3/raw/main/docs/_static/banner_github.svg)

</h1>

<p align="center">
  <a href="https://pypi.org/project/urllib3"><img alt="PyPI Version" src="https://img.shields.io/pypi/v/urllib3.svg?maxAge=86400" /></a>
  <a href="https://pypi.org/project/urllib3"><img alt="Python Versions" src="https://img.shields.io/pypi/pyversions/urllib3.svg?maxAge=86400" /></a>
  <a href="https://discord.gg/urllib3"><img alt="Join our Discord" src="https://img.shields.io/discord/756342717725933608?color=%237289da&label=discord" /></a>
  <a href="https://github.com/urllib3/urllib3/actions?query=workflow%3ACI"><img alt="Coverage Status" src="https://img.shields.io/badge/coverage-100%25-success" /></a>
  <a href="https://github.com/urllib3/urllib3/actions?query=workflow%3ACI"><img alt="Build Status on GitHub" src="https://github.com/urllib3/urllib3/workflows/CI/badge.svg" /></a>
  <a href="https://urllib3.readthedocs.io"><img alt="Documentation Status" src="https://readthedocs.org/projects/urllib3/badge/?version=latest" /></a>
</p>

urllib3 is a powerful, *user-friendly* HTTP client for Python. Much of the
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

urllib3 is powerful and easy to use:

```python3
>>> import urllib3
>>> http = urllib3.PoolManager()
>>> resp = http.request("GET", "http://httpbin.org/robots.txt")
>>> resp.status
200
>>> resp.data
b"User-agent: *\nDisallow: /deny\n"
```

## Installing

urllib3 can be installed with [pip](https://pip.pypa.io):

```bash
$ python -m pip install urllib3
```

Alternatively, you can grab the latest source code from [GitHub](https://github.com/urllib3/urllib3):

```bash
$ git clone https://github.com/urllib3/urllib3.git
$ cd urllib3
$ pip install .
```


## Documentation

urllib3 has usage and reference documentation at [urllib3.readthedocs.io](https://urllib3.readthedocs.io).


## Community

urllib3 has a [community Discord channel](https://discord.gg/urllib3) for asking questions and
collaborating with other contributors. Drop by and say hello 👋


## Contributing

urllib3 happily accepts contributions. Please see our
[contributing documentation](https://urllib3.readthedocs.io/en/latest/contributing.html)
for some tips on getting started.


## Security Disclosures

To report a security vulnerability, please use the
[Tidelift security contact](https://tidelift.com/security).
Tidelift will coordinate the fix and disclosure with maintainers.


## Maintainers

- [@sethmlarson](https://github.com/sethmlarson) (Seth M. Larson)
- [@pquentin](https://github.com/pquentin) (Quentin Pradet)
- [@theacodes](https://github.com/theacodes) (Thea Flowers)
- [@haikuginger](https://github.com/haikuginger) (Jess Shapiro)
- [@lukasa](https://github.com/lukasa) (Cory Benfield)
- [@sigmavirus24](https://github.com/sigmavirus24) (Ian Stapleton Cordasco)
- [@shazow](https://github.com/shazow) (Andrey Petrov)

👋


## Sponsorship

If your company benefits from this library, please consider [sponsoring its
development](https://urllib3.readthedocs.io/en/latest/sponsors.html).


## For Enterprise

Professional support for urllib3 is available as part of the [Tidelift
Subscription][1].  Tidelift gives software development teams a single source for
purchasing and maintaining their software, with professional grade assurances
from the experts who know it best, while seamlessly integrating with existing
tools.

[1]: https://tidelift.com/subscription/pkg/pypi-urllib3?utm_source=pypi-urllib3&utm_medium=referral&utm_campaign=readme

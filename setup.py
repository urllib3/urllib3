#!/usr/bin/env python
# This file is protected via CODEOWNERS

import os
import re
import sys

from setuptools import setup

CURRENT_PYTHON = sys.version_info[:2]
REQUIRED_PYTHON = (3, 7)

# This check and everything above must remain compatible with Python 2.7.
if CURRENT_PYTHON < REQUIRED_PYTHON:
    sys.stderr.write(
        """
==========================
Unsupported Python version
==========================
This version of urllib3 requires Python {}.{}, but you're trying to
install it on Python {}.{}.
This may be because you are using a version of pip that doesn't
understand the python_requires classifier. Make sure you
have pip >= 9.0 and setuptools >= 24.2, then try again:
    $ python -m pip install --upgrade pip setuptools
    $ python -m pip install urllib3
This will install the latest version of urllib3 which works on your
version of Python. If you can't upgrade your pip (or Python), request
an older version of urllib3:
    $ python -m pip install "urllib3<2"
""".format(
            *(REQUIRED_PYTHON + CURRENT_PYTHON)
        )
    )
    sys.exit(1)


base_path = os.path.dirname(__file__)

# Get the version (borrowed from SQLAlchemy)
with open(os.path.join(base_path, "src", "urllib3", "_version.py")) as fp:
    VERSION = (
        re.compile(r""".*__version__ = ["'](.*?)['"]""", re.S).match(fp.read()).group(1)
    )


with open("README.rst", encoding="utf-8") as fp:
    # Remove reST raw directive from README as they're not allowed on PyPI
    # Those blocks start with a newline and continue until the next newline
    mode = None
    lines = []
    for line in fp:
        if line.startswith(".. raw::"):
            mode = "ignore_nl"
        elif line == "\n":
            mode = "wait_nl" if mode == "ignore_nl" else None

        if mode is None:
            lines.append(line)
    readme = "".join(lines)

with open("CHANGES.rst", encoding="utf-8") as fp:
    changes = fp.read()

version = VERSION

setup(
    name="urllib3",
    version=version,
    description="HTTP library with thread-safe connection pooling, file post, and more.",
    long_description="\n\n".join([readme, changes]),
    long_description_content_type="text/x-rst",
    classifiers=[
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Software Development :: Libraries",
    ],
    keywords="urllib httplib threadsafe filepost http https ssl pooling",
    author="Andrey Petrov",
    author_email="andrey.petrov@shazow.net",
    url="https://urllib3.readthedocs.io",
    project_urls={
        "Documentation": "https://urllib3.readthedocs.io",
        "Code": "https://github.com/urllib3/urllib3",
        "Issue tracker": "https://github.com/urllib3/urllib3/issues",
    },
    license="MIT",
    packages=[
        "urllib3",
        "urllib3.contrib",
        "urllib3.contrib._securetransport",
        "urllib3.multipart",
        "urllib3.util",
    ],
    package_data={
        "urllib3": ["py.typed"],
    },
    package_dir={"": "src"},
    requires=[],
    python_requires=">=3.7, <4",
    extras_require={
        "brotli": [
            "brotli>=1.0.9; platform_python_implementation == 'CPython'",
            "brotlicffi>=0.8.0; platform_python_implementation != 'CPython'",
        ],
        "secure": [
            "pyOpenSSL>=0.14",
            "cryptography>=1.3.4",
            "idna>=2.0.0",
            "certifi",
        ],
        "socks": ["PySocks>=1.5.6,<2.0,!=1.5.7"],
    },
)

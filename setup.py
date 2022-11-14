#!/usr/bin/env python
# This file is protected via CODEOWNERS

import sys

from setuptools import setup

sys.stderr.write(
    """
===============================
Unsupported installation method
===============================

This version of urllib3 has dropped support for Python 2.7 and no longer supports
installation with `python setup.py install`.

Please use `python -m pip install .` instead.
"""
)
sys.exit(1)


# The below code will never execute, however GitHub is particularly
# picky about where it finds Python packaging metadata.
# See: https://github.com/github/feedback/discussions/6456

setup(
    name="urllib3",
    requires=[],
)

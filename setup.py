#!/usr/bin/env python
# This file is protected via CODEOWNERS

import sys

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

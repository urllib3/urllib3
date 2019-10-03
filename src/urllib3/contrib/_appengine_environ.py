"""
This module provides means to detect the App Engine environment.
"""

import os


def is_appengine():
    return "APPENGINE_RUNTIME" in os.environ


def is_appengine_sandbox():
    """Deprecated. Use is_appengine instead."""
    return is_appengine()


def is_local_appengine():
    return is_appengine() and os.environ.get("SERVER_SOFTWARE", "").startswith(
        "Development/"
    )


def is_prod_appengine():
    return is_appengine() and os.environ.get("SERVER_SOFTWARE", "").startswith(
        "Google App Engine/"
    )


def is_prod_appengine_mvms():
    """Deprecated."""
    return False

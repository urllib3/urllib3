"""
This module provides means to detect the App Engine environment.
"""

import os


def is_appengine():
    return (is_local_appengine() or
            is_prod_appengine() or
            is_prod_appengine_mvms())


def is_appengine_sandbox():
    return is_appengine() and not is_prod_appengine_mvms()


def is_local_appengine():
    return ('SERVER_SOFTWARE' not in os.environ or
            os.environ['SERVER_SOFTWARE'].startswith('Development'))


def is_prod_appengine():
    return not is_local_appengine()


def is_prod_appengine_mvms():
    return os.environ.get('GAE_VM', False) == 'true'

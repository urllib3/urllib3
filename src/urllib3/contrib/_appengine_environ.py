"""
This module provides means to detect the App Engine environment.
"""

import os


def is_appengine():
    try:
        from google.appengine.tools.devappserver2.python import instance_factory
        return True
    except ImportError:
        return False


def is_appengine_sandbox():
    return is_appengine() and not is_prod_appengine_mvms()


def is_local_appengine():
    return is_appengine() and \
           ('SERVER_SOFTWARE' not in os.environ or
            os.environ.get('SERVER_SOFTWARE', '').startswith('Development'))


def is_prod_appengine():
    return is_appengine() and \
           ('APPENGINE_RUNTIME' in os.environ and
            not os.environ.get('SERVER_SOFTWARE', '').startswith('Development') and
            not is_prod_appengine_mvms())


def is_prod_appengine_mvms():
    return os.environ.get('GAE_VM', False) == 'true'

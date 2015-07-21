.. _contrib-modules:

Contrib Modules
===============

These modules implement various extra features, that may not be ready for
prime time.

.. _contrib-pyopenssl:

SNI-support for Python 2
------------------------

.. automodule:: urllib3.contrib.pyopenssl


.. _gae:

Google App Engine 
-----------------

The :mod:`urllib3.contrib.appengine` module provides a pool manager that
uses Google App Engine's `URLFetch Service <https://cloud.google.com/appengine/docs/python/urlfetch>`_.

Example usage::

    from urllib3 import PoolManager
    from urllib3.contrib.appengine import AppEngineManager, is_appengine_sandbox

    # This substitution will be done automagically once appengine code
    # graduates from the contrib module.
    if is_appengine_sandbox():
        # AppEngineManager uses AppEngine's URLFetch API behind the scenes
        http = AppEngineManager()
    else:
        # PoolManager uses a socket-level API behind the scenes
        http = PoolManager()

    # The client API should be consistent across managers, though some features are not available
    # in URLFetch and you'll get warnings when you try to use them (like granular timeouts).
    r = http.request('GET', 'https://google.com/')


There are `limitations <https://cloud.google.com/appengine/docs/python/urlfetch/#Python_Quotas_and_limits>`_ to the URLFetch service and it may not be the best choice for your application. App Engine provides three options for urllib3 users:

1. You can use :class:`AppEngineManager` with URLFetch. URLFetch is cost-effective in many circumstances as long as your usage is within the limitations.
2. You can use a normal :class:`PoolManager` by enabling sockets. Sockets also have `limitations and restrictions <https://cloud.google.com/appengine/docs/python/sockets/#limitations-and-restrictions>`_ and have a lower free quota than URLFetch. To use sockets, be sure to specify the following in your ``app.yaml``::
    
    env_variables:
        GAE_USE_SOCKETS_HTTPLIB : 'true'

3. If you are using `Managed VMs <https://cloud.google.com/appengine/docs/managed-vms/>`_, you can use the standard :class:`PoolManager` without any configuration or special environment variables.

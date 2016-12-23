"""
Initialize RequestMethods - provides .request(), .request_encode_url(), .request_encode_body()
Stick the ConnectionPool kwargs in a dict
Save a set of ConnectionPools in a RecentlyUsedContainer
Set the scheme -> pool class table
Set the function to derive a pool key


<RequestMethods stuff>
Parse the URL
Retrieve the connection by URL
Set assert_same_host = False
Set redirect = False
Set headers to have instance value if not present
<ConnectionPool stuff>
* Check for a redirect location
    |                   |
Set new method, etc     YAY! Return!
    |
Back down from the top...


Going down                                      Going up
MultiHostPipelineElement
                                                RedirectPipelineElement
ParseUrlPipelineElement
SelectConnectionPipelineElement
UrlOpenPipelineElement

"""
from __future__ import absolute_import, unicode_literals

import collections
import functools
from logging import getLogger

from urllib3._collections import RecentlyUsedContainer
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool, port_by_scheme
from urllib3.exceptions import LocationValueError, MaxRetryError, ProxySchemeUnknown
from urllib3.packages.six.moves.urllib.parse import urljoin
from urllib3.pipeline import DefinedPipeline, HttpPipelineElement, ReverseResponse
from urllib3.util.retry import Retry
from urllib3.util.url import parse_url

log = getLogger(__name__)

SSL_KEYWORDS = ('key_file', 'cert_file', 'cert_reqs', 'ca_certs',
                'ssl_version', 'ca_cert_dir', 'ssl_context')

# The base fields to use when determining what pool to get a connection from;
# these do not rely on the ``connection_pool_kw`` and can be determined by the
# URL and potentially the ``urllib3.connection.port_by_scheme`` dictionary.
#
# All custom key schemes should include the fields in this key at a minimum.
BasePoolKey = collections.namedtuple('BasePoolKey', ('scheme', 'host', 'port'))

# The fields to use when determining what pool to get a HTTP and HTTPS
# connection from. All additional fields must be present in the PoolManager's
# ``connection_pool_kw`` instance variable.
HTTPPoolKey = collections.namedtuple(
    'HTTPPoolKey', BasePoolKey._fields + ('timeout', 'retries',
                                          'block', 'source_address')
)
HTTPSPoolKey = collections.namedtuple(
    'HTTPSPoolKey', HTTPPoolKey._fields + SSL_KEYWORDS
)

def _default_key_normalizer(key_class, request_context):
    """
    Create a pool key of type ``key_class`` for a request.

    According to RFC 3986, both the scheme and host are case-insensitive.
    Therefore, this function normalizes both before constructing the pool
    key for an HTTPS request. If you wish to change this behaviour, provide
    alternate callables to ``key_fn_by_scheme``.

    :param key_class:
        The class to use when constructing the key. This should be a namedtuple
        with the ``scheme`` and ``host`` keys at a minimum.

    :param request_context:
        A dictionary-like object that contain the context for a request.
        It should contain a key for each field in the :class:`HTTPPoolKey`
    """
    context = {}
    for key in key_class._fields:
        context[key] = request_context.get(key)
    context['scheme'] = context['scheme'].lower()
    context['host'] = context['host'].lower()
    return key_class(**context)


# A dictionary that maps a scheme to a callable that creates a pool key.
# This can be used to alter the way pool keys are constructed, if desired.
# Each PoolManager makes a copy of this dictionary so they can be configured
# globally here, or individually on the instance.
key_fn_by_scheme = {
    'http': functools.partial(_default_key_normalizer, HTTPPoolKey),
    'https': functools.partial(_default_key_normalizer, HTTPSPoolKey),
}

pool_classes_by_scheme = {
    'http': HTTPConnectionPool,
    'https': HTTPSConnectionPool,
}


class MultiHostPipelineElement(HttpPipelineElement):

    def __init__(self, headers=None):
        self.headers = headers or {}
        super(MultiHostPipelineElement, self).__init__()

    def apply(self, context, **kwargs):
        kwargs['assert_same_host'] = False
        headers = self.headers.copy()
        headers.update(kwargs.get('headers', {}))
        kwargs['headers'] = headers
        return kwargs


class RedirectPipelineElement(HttpPipelineElement):

    def __init__(self, default=True, kw_override=None):
        self.redirect_default = default
        self.kw_override = kw_override
        super(RedirectPipelineElement, self).__init__()

    def get_retries_object(self, context):
        retries = context.get('retries', None)
        redirect = context.get('redirect', self.redirect_default)
        if not isinstance(retries, Retry):
            retries = Retry.from_int(retries, redirect=redirect)
        context.save('retries', retries)
        return retries

    def apply(self, context, **kwargs):
        # Get a redirect value; get the default otherwise
        redirect = kwargs.pop('redirect', self.redirect_default)
        # Save the retries value and the redirect value
        context.save('redirect', redirect)
        context.save('retries', kwargs.pop('retries', None))
        # Get a real retries object, saving it to the context
        retries = self.get_retries_object(context)
        # Override the kwarg-retrieved redirect and retries values
        kwargs['redirect'] = self.kw_override if self.kw_override is not None else redirect
        kwargs['retries'] = retries
        # Save the original kwargs to the context
        context.save('kwargs', kwargs)
        # Return the kwargs
        return kwargs

    def resolve(self, context, response):
        # Return if no redirect is necessary
        redirect_location = context.get('redirect') and response.get_redirect_location()
        if not redirect_location:
            return response

        # Get the original values out of the context
        retries = self.get_retries_object(context)
        redirect = context.get('redirect', self.redirect_default)
        kwargs = context.get('kwargs').copy()

        # Support relative URLs for redirecting.
        redirect_location = urljoin(kwargs['url'], redirect_location)

        if response.status == 303:
            kwargs['method'] = 'GET'

        try:
            retries = retries.increment(kwargs['method'], kwargs['url'], response=response, _pool=self)
        except MaxRetryError:
            if retries.raise_on_redirect:
                raise
            return response

        kwargs['retries'] = retries
        log.info("Redirecting %s -> %s", kwargs['url'], redirect_location)
        kwargs['url'] = redirect_location
        return ReverseResponse(value=kwargs)


class ConnectionSelectorPipelineElement(HttpPipelineElement):

    def __init__(self, num_pools=10, **connection_pool_kw):
        self.connection_pool_kw = connection_pool_kw
        self.pools = RecentlyUsedContainer(num_pools, dispose_func=lambda p: p.close())
        self.pool_classes_by_scheme = pool_classes_by_scheme
        self.key_fn_by_scheme = key_fn_by_scheme.copy()
        super(ConnectionSelectorPipelineElement, self).__init__()

    def _new_pool(self, scheme, host, port):
        """
        Create a new :class:`ConnectionPool` based on host, port and scheme.

        This method is used to actually create the connection pools handed out
        by :meth:`connection_from_url` and companion methods. It is intended
        to be overridden for customization.
        """
        pool_cls = self.pool_classes_by_scheme[scheme]
        kwargs = self.connection_pool_kw
        if scheme == 'http':
            kwargs = self.connection_pool_kw.copy()
            for kw in SSL_KEYWORDS:
                kwargs.pop(kw, None)

        return pool_cls(host, port, **kwargs)

    def clear(self):
        """
        Empty our store of pools and direct them all to close.

        This will not affect in-flight connections, but they will not be
        re-used after completion.
        """
        self.pools.clear()

    def connection_from_host(self, host, port=None, scheme='http'):
        """
        Get a :class:`ConnectionPool` based on the host, port, and scheme.

        If ``port`` isn't given, it will be derived from the ``scheme`` using
        ``urllib3.connectionpool.port_by_scheme``.
        """

        if not host:
            raise LocationValueError("No host specified.")

        request_context = self.connection_pool_kw.copy()
        request_context['scheme'] = scheme or 'http'
        if not port:
            port = port_by_scheme.get(request_context['scheme'].lower(), 80)
        request_context['port'] = port
        request_context['host'] = host

        return self.connection_from_context(request_context)

    def connection_from_context(self, request_context):
        """
        Get a :class:`ConnectionPool` based on the request context.

        ``request_context`` must at least contain the ``scheme`` key and its
        value must be a key in ``key_fn_by_scheme`` instance variable.
        """
        scheme = request_context['scheme'].lower()
        pool_key_constructor = self.key_fn_by_scheme[scheme]
        pool_key = pool_key_constructor(request_context)

        return self.connection_from_pool_key(pool_key)

    def connection_from_pool_key(self, pool_key):
        """
        Get a :class:`ConnectionPool` based on the provided pool key.

        ``pool_key`` should be a namedtuple that only contains immutable
        objects. At a minimum it must have the ``scheme``, ``host``, and
        ``port`` fields.
        """
        with self.pools.lock:
            # If the scheme, host, or port doesn't match existing open
            # connections, open a new ConnectionPool.
            pool = self.pools.get(pool_key)
            if pool:
                return pool

            # Make a fresh ConnectionPool of the desired type
            pool = self._new_pool(pool_key.scheme, pool_key.host, pool_key.port)
            self.pools[pool_key] = pool

        return pool

    def apply(self, context, **kwargs):
        url = parse_url(kwargs['url'])
        kwargs['connection'] = self.connection_from_host(
            url.host,
            port=url.port,
            scheme=url.scheme
        )
        return kwargs

class UrlopenPipelineElement(HttpPipelineElement):

    def apply(self, context, **kwargs):
        conn = kwargs.pop('connection')
        return conn.urlopen(**kwargs)


class PoolManagerPipeline(DefinedPipeline):
    
    elements = [
        MultiHostPipelineElement,
        RedirectPipelineElement(kw_override=False),
        ConnectionSelectorPipelineElement,
        UrlopenPipelineElement
    ]


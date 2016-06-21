from .util.retry import Retry
from .request import RequestMethods, Request
from .util.sessioncontext import SessionContext


class SessionManager(RequestMethods):
    """
    Allows arbitrary requests while maintaining session context across
    those requests. Currently, that context consists of automatic
    cookie storage and retrieval.

    :param manager:
        An appropriate :class:`urllib3.poolmanager.PoolManager` or
        :class:`urllib3.poolmanager.ProxyManager` object
        to handle HTTP requests for the SessionManager

    :param context:
        A predefined :class:`urllib3.util.context.SessionContext` object to use in the session;
        if not provided, a new one will be created.

    :param headers:
        A set of headers to include with all requests, unless other
        headers are given explicitly.

    Example::

        >>> manager = SessionManager(PoolManager())
        >>> manager.context.handlers[0].cookie_jar
        <CookieJar[]>
        >>> len(manager.context.handlers[0].cookie_jar)
        0
        >>> manager.request('GET', 'http://google.com')
        >>> manager.request('GET', 'http://yahoo.com')
        >>> len(manager.context.handlers[0].cookie_jar)
        2

    """
    def __init__(self, manager, context=None, headers=None, **context_kw):
        super(SessionManager, self).__init__(headers=headers)
        self.manager = manager
        self.context = context or SessionContext(**context_kw)

    def urlopen(self, method, url, body=None, redirect=True,
                retries=None, redirect_from=None, **kw):
        """
        Same as :meth:`urllib2.poolmanager.PoolManager.urlopen` with added
        request-context-managing special sauce. The received ``url`` param
        must be an absolute path.

        This is a low-level method; use :func:`urllib3.request.RequestMethods.request`
        instead.
        """
        headers = kw.pop('headers', self.headers)

        if not isinstance(retries, Retry):
            retries = Retry.from_int(retries, redirect=redirect)

        # Build a mock Request object to work with
        request_object = Request(url=url, method=method, headers=headers)
        self.context.apply_to(request_object)

        # Ensure that redirects happen at this level only
        kw['redirect'] = False
        request_kw = request_object.get_kwargs()
        request_kw.update(kw)
        response = self.manager.urlopen(retries=retries, **request_kw)

        # Retrieve any context from the response
        self.context.extract_from(response, request_object)

        # Redirect as necessary, and return.
        if redirect and response.get_redirect_location():
            kw['redirect'] = redirect
            kw['headers'] = headers
            return self.redirect(response=response, method=method,
                                 retries=retries, url=url, **kw)
        return response

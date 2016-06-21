from ..contexthandlers import CookieHandler

class SessionContext(object):
    """
    Extensible class encapsulated by :class:`.SessionManager`; currently
    used to manage cookies.

    :param cookie_jar:
        Used to pass a prebuilt :class:`CookieJar` into the
        context to be used instead of an empty jar.
    """

    def __init__(self, handlers=None):
        # We unfortunately have to do it this way; empty cookie jars
        # evaluate as falsey.
        if handlers is not None:
            self.handlers = handlers
        else:
            self.handlers = [CookieHandler()]

    def apply_to(self, request):
        """
        Applies changes from the context to the supplied :class:`.request.Request`.
        """
        for handler in self.handlers:
            if hasattr(handler, 'apply_to'):
                handler.apply_to(request) 

    def extract_from(self, response, request):
        """
        Extracts context modifications (new cookies, etc) from the response and stores them.
        """
        for handler in self.handlers:
            if hasattr(handler, 'extract_from'):
                handler.extract_from(response, request)

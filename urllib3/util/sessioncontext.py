from ..contexthandlers import CookieHandler


class SessionContext(object):
    """
    Extensible class encapsulated by :class:`.SessionManager`; currently
    used to manage cookies.

    :param handlers:
        Takes a list of ContextHandler objects that will be able to mutate in-flight
        requests and get information back from responses.
    """

    def __init__(self, handlers=None):
        # We want to be able to have an empty list passed to handlers; that way
        # we can have a SessionContext with no handlers.
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

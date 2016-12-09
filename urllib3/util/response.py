from __future__ import absolute_import

from ..exceptions import HeaderParsingError


def is_fp_closed(obj):
    """
    Checks whether a given file-like object is closed.

    :param obj:
        The file-like object to check.
    """

    try:
        # Check `isclosed()` first, in case Python3 doesn't set `closed`.
        # GH Issue #928
        return obj.isclosed()
    except AttributeError:
        pass

    try:
        # Check via the official file-like-object way.
        return obj.closed
    except AttributeError:
        pass

    try:
        # Check if the object is a container for another file-like object that
        # gets released on exhaustion (e.g. HTTPResponse).
        return obj.fp is None
    except AttributeError:
        pass

    raise ValueError("Unable to determine whether fp is closed.")


def is_response_to_head(response):
    """
    Checks whether the request of a response has been a HEAD-request.
    Handles the quirks of AppEngine.

    :param conn:
    :type conn: :class:`httplib.HTTPResponse`
    """
    # FIXME: Can we do this somehow without accessing private httplib _method?
    method = response._method
    if isinstance(method, int):  # Platform-specific: Appengine
        return method == 3
    return method.upper() == 'HEAD'

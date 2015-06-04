from collections import namedtuple
try:
    import http.client as httplib
except ImportError:
    import httplib


class HeaderParsingErrors(
        namedtuple('_HeaderParsingErrors', ['defects', 'unparsed_data'])):

    def __bool__(self):
        return bool(self.defects or self.unparsed_data)

    def __nonzero__(self):  # Platform-specific: Python 2.
        return self.__bool__()


def is_fp_closed(obj):
    """
    Checks whether a given file-like object is closed.

    :param obj:
        The file-like object to check.
    """

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


def extract_parsing_errors(headers):
    """
    Extracts encountered errors from the result of parsing headers.

    Only works on Python 3 (and PyPy 2).

    :param headers: Headers to extract errors from.
    :type headers: `httplib.HTTPMessage`.

    :returns: Defects encountered while parsing headers and unparsed header
              data.
    :rtype: HeaderParsingErrors
    """

    # This will fail silently if we pass in the wrong kind of parameter.
    # To make debugging easier add a explicit check.
    if not isinstance(headers, httplib.HTTPMessage):
        raise TypeError('expected httplib.Message, got {}.'.format(
            type(headers)))

    defects = getattr(headers, 'defects', None)
    get_payload = getattr(headers, 'get_payload', None)

    if get_payload:  # Platform-specific: Implementation dependent.
        unparsed_data = get_payload()
    else:  # Platform-specific
        unparsed_data = None

    return HeaderParsingErrors(defects=defects, unparsed_data=unparsed_data)

import logging

log = logging.getLogger(__name__)


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


def validate_headers(headers):
    """
    Checks whether headers have been successfully and completely parsed.

    Only works on Python 3.

    :param headers: Headers to check.
    :type headers: `httplib.HTTPMessage`.

    :returns: Whether any errors occured during header parsing.
    :rtype: bool
    """
    result = False
    defects = getattr(headers, 'defects', None)

    if defects:
        log.error('Errors while parsing headers: %s', defects)
        result = True

    get_payload = getattr(headers, 'get_payload', None)

    if get_payload:
        unparsed_headers = get_payload()
        if unparsed_headers:
            log.error('Unparsed headers: %s', repr(unparsed_headers))
            result = True

    return result

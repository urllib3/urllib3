def is_fp_closed(obj):
    """
    Checks whether a given file-like object is closed.

    :param obj:
        The file-like object to check.
    """

    try:
        # check via the official file-like-object way
        return obj.closed
    except AttributeError:
        pass

    if hasattr(obj, 'fp'):
        # Object is a container for another file-like object that gets released
        # on exhaustion (e.g. HTTPResponse)
        return obj.fp is None

    raise ValueError("unable to determine whether fp is closed")

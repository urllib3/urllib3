from .. import util

__all__ = ["is_readable", "LoopAbort"]


def is_readable(sock):
    return util.wait_for_read(timeout=0)


class LoopAbort(Exception):
    """
    Tell backends that enough bytes have been consumed
    """
    pass

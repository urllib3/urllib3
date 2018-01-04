from urllib3.packages import six
from .sync_backend import SyncBackend

__all__ = [SyncBackend]

if six.PY3:
    from .twisted_backend import TwistedBackend
    from .trio_backend import TrioBackend
    __all__ += [TwistedBackend, TrioBackend]

from urllib3.packages import six
from .sync_backend import SyncBackend

__all__ = ['SyncBackend']

if six.PY3:
    from .trio_backend import TrioBackend
    from .twisted_backend import TwistedBackend
    __all__ += ['TrioBackend', 'TwistedBackend']

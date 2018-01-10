from urllib3.packages import six
from .sync_backend import SyncBackend

__all__ = ['SyncBackend']

if six.PY3:
    from .._async.backends.trio_backend import TrioBackend
    from .._async.backends.twisted_backend import TwistedBackend
    __all__ += ['TrioBackend', 'TwistedBackend']

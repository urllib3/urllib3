from urllib3.packages import six
from .._sync.backends.sync_backend import SyncBackend

__all__ = ['SyncBackend']

if six.PY3:
    from .._async.backends.twisted_backend import TwistedBackend
    from .._async.backends.trio_backend import TrioBackend
    __all__ += ['TwistedBackend', 'TrioBackend']

import sys

from ..backends import Backend


class Loader:

    def __init__(self, name, loader, is_async):
        self.name = name
        self.loader = loader
        self.is_async = is_async

    def __call__(self, *args, **kwargs):
        return self.loader(kwargs)


def load_sync_backend(kwargs):
    from .sync_backend import SyncBackend
    return SyncBackend(**kwargs)


def load_trio_backend(kwargs):
    from .trio_backend import TrioBackend
    return TrioBackend(**kwargs)


def load_twisted_backend(kwargs):
    from .twisted_backend import TwistedBackend
    return TwistedBackend(**kwargs)


def backend_directory():
    """
    We defer any heavy duty imports until the last minute.
    """
    loaders = [
        Loader(
            name="sync",
            loader=load_sync_backend,
            is_async=False,
        ),
        Loader(
            name="trio",
            loader=load_trio_backend,
            is_async=True,
        ),
        Loader(
            name="twisted",
            loader=load_twisted_backend,
            is_async=True,
        ),
    ]
    return {
        loader.name: loader for loader in loaders
    }


def async_supported():
    """
    Tests if the async keyword is supported.
    """
    async def f():
        """
        Functions with an `async` prefix return a coroutine.
        This is removed by the bleaching code, which will change this function to return None.
        """
        return None

    obj = f()
    if obj is None:
        return False
    else:
        obj.close()  # prevent unawaited coroutine warning
        return True


def normalize_backend(backend):
    if backend is None:
        backend = Backend(name="sync")  # sync backend is the default
    elif not isinstance(backend, Backend):
        backend = Backend(name=backend)

    loaders_by_name = backend_directory()
    if backend.name not in loaders_by_name:
        raise ValueError("unknown backend specifier {}".format(backend.name))

    loader = loaders_by_name[backend.name]

    is_async_supported = async_supported()
    if is_async_supported and not loader.is_async:
        raise ValueError("{} backend requires urllib3 to be built without async support".format(loader.name))

    if not is_async_supported and loader.is_async:
        raise ValueError("{} backend requires urllib3 to be built with async support".format(loader.name))

    return backend


def load_backend(backend):
    loaders_by_name = backend_directory()
    loader = loaders_by_name[backend.name]
    return loader(backend.kwargs)

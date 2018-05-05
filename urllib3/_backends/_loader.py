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


def user_specified_unknown_backend(backend_name):
    backend_names = [loader.name for loader in backend_directory().values()]
    return "Unknown backend specifier {backend_name}. Choose one of: {known_backend_names}".format(
        backend_name=backend_name,
        known_backend_names=", ".join(backend_names)
    )


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


def user_specified_incompatible_backend(backend_name, is_async_supported, is_async_backend):
    lib_kind = "async" if is_async_supported else "sync"
    loader_kind = "an async backend" if is_async_backend else "a sync backend"
    return "{name} is {loader_kind} which is incompatible with the {lib_kind} version of urllib3.".format(
        name=backend_name,
        loader_kind=loader_kind,
        lib_kind=lib_kind,
    )


def normalize_backend(backend):
    if backend is None:
        backend = Backend(name="sync")  # sync backend is the default
    elif not isinstance(backend, Backend):
        backend = Backend(name=backend)

    loaders_by_name = backend_directory()
    if backend.name not in loaders_by_name:
        raise ValueError(user_specified_unknown_backend(backend.name))

    loader = loaders_by_name[backend.name]

    is_async_supported = async_supported()
    if is_async_supported != loader.is_async:
        raise ValueError(user_specified_incompatible_backend(loader.name, is_async_supported, loader.is_async))

    return backend


def load_backend(backend):
    loaders_by_name = backend_directory()
    loader = loaders_by_name[backend.name]
    return loader(backend.kwargs)

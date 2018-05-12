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


def normalize_backend(backend, async_mode):
    if backend is None:
        backend = Backend(name="sync")  # sync backend is the default
    elif not isinstance(backend, Backend):
        backend = Backend(name=backend)

    loaders_by_name = backend_directory()
    if backend.name not in loaders_by_name:
        raise ValueError("unknown backend specifier {}".format(backend.name))

    loader = loaders_by_name[backend.name]

    if async_mode and not loader.is_async:
        raise ValueError("{} backend needs to be run in sync mode".format(
            loader.name))

    if not async_mode and loader.is_async:
        raise ValueError("{} backend needs to be run in async mode".format(
            loader.name))

    return backend


def load_backend(backend):
    loaders_by_name = backend_directory()
    loader = loaders_by_name[backend.name]
    return loader(backend.kwargs)

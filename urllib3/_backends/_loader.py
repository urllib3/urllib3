import sys

from ..backends import Backend as UserSpecifiedBackend


def check_for_python_3_5():
    if sys.version_info < (3, 5):
        raise ValueError("This backend requires Python 3.5 or greater.")


def load_dummy_backend(kwargs):
    """
    This function is called by unit tests.
    It asserts that urllib3 can be used without having a specific backend installed.
    The .dummy_backend module should not exist.
    """
    from .dummy_backend import DummyBackend
    return DummyBackend(**kwargs)


def load_sync_backend(kwargs):
    from .sync_backend import SyncBackend
    return SyncBackend(**kwargs)


def load_trio_backend(kwargs):
    check_for_python_3_5()
    from .trio_backend import TrioBackend
    return TrioBackend(**kwargs)


def load_twisted_backend(kwargs):
    check_for_python_3_5()
    from .twisted_backend import TwistedBackend
    return TwistedBackend(**kwargs)


def backend_directory():
    """
    We defer any heavy duty imports until the last minute.
    """
    return {
        "dummy": load_dummy_backend,
        "sync": load_sync_backend,
        "trio": load_trio_backend,
        "twisted": load_twisted_backend,
    }


def user_specified_unknown_backend(backend_name):
    known_backend_names = sorted(backend_directory().keys())
    return "Unknown backend specifier {backend_name}. Choose one of: {known_backend_names}".format(
        backend_name=backend_name,
        known_backend_names=", ".join(known_backend_names)
    )


def load_backend(user_specified_backend):
    if not isinstance(user_specified_backend, UserSpecifiedBackend):
        user_specified_backend = UserSpecifiedBackend(name=user_specified_backend)

    available_loaders = backend_directory()
    if user_specified_backend.name not in available_loaders:
        raise ValueError(user_specified_unknown_backend(user_specified_backend.name))

    loader = available_loaders[user_specified_backend.name]
    return loader(user_specified_backend.kwargs)

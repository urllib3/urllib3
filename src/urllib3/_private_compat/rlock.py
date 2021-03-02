"""
In this module, we shim out a context manager to be used as a compatibility
layer if the system `threading` module doesn't have a real `RLock` available.
"""


class RLock:
    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        pass

class RLock:  # Python 3.6
    # We shim out a context manager to be used as a compatibility layer
    # if the system `threading` module doesn't have a real `RLock` available.
    def __enter__(self) -> None:
        pass

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        pass

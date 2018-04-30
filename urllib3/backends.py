class Backend:
    """
    Specifies the desired backend and any argumnets passed to it's constructor.

    Projects that use urllib3 can subclass this interface to expose it to users.
    """
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs

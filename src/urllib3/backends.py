class Backend:
    """
    Specifies the desired backend and any arguments passed to its constructor.

    Projects that use urllib3 can subclass this interface to expose it to users.
    """
    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs

    def __eq__(self, other):
        return self.name == other.name and self.kwargs == other.kwargs

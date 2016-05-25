try:
    from typing import (
        Generic,  # noqa: unused in this module
        TypeVar,  # noqa: unused in this module
        MutableMapping,  # noqa: unused in this module
        List,  # noqa: unused in this module
        Union,  # noqa: unused in this module
        Tuple,  # noqa: unused in this module
        Callable,  # noqa: unused in this module
        Optional,  # noqa: unused in this module
        Iterable,  # noqa: unused in this module
        Iterator,  # noqa: unused in this module
        Set,  # noqa: unused in this module
        Any,  # noqa: unused in this module
    )
except ImportError:
    from urllib3.packages import six

    class _NoopGetItem(type):
        def __getitem__(self, _):
            return object

    class Generic(six.with_metaclass(_NoopGetItem)):
        pass

    class MutableMapping(six.with_metaclass(_NoopGetItem)):
        pass

    class List(six.with_metaclass(_NoopGetItem)):
        pass

    class Union(six.with_metaclass(_NoopGetItem)):
        pass

    class Tuple(six.with_metaclass(_NoopGetItem)):
        pass

    class Callable(six.with_metaclass(_NoopGetItem)):
        pass

    class Optional(six.with_metaclass(_NoopGetItem)):
        pass

    class Iterable(six.with_metaclass(_NoopGetItem)):
        pass

    class Iterator(six.with_metaclass(_NoopGetItem)):
        pass

    class Set(six.with_metaclass(_NoopGetItem)):
        pass

    class Any:
        pass

    def TypeVar(*args):
        pass

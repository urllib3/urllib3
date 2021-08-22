import pickle

import pytest

from urllib3.connection import HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool
from urllib3.exceptions import (
    ClosedPoolError,
    ConnectTimeoutError,
    EmptyPoolError,
    HeaderParsingError,
    HostChangedError,
    HTTPError,
    LocationParseError,
    MaxRetryError,
    NewConnectionError,
    ReadTimeoutError,
)


class TestPickle:
    @pytest.mark.parametrize(
        "exception",
        [
            HTTPError(None),
            MaxRetryError(None, None, None),
            LocationParseError(None),
            ConnectTimeoutError(None),
            HTTPError("foo"),
            HTTPError("foo", IOError("foo")),
            MaxRetryError(HTTPConnectionPool("localhost"), "/", None),
            LocationParseError("fake location"),
            ClosedPoolError(HTTPConnectionPool("localhost"), None),
            EmptyPoolError(HTTPConnectionPool("localhost"), None),
            HostChangedError(HTTPConnectionPool("localhost"), "/", None),
            ReadTimeoutError(HTTPConnectionPool("localhost"), "/", None),
        ],
    )
    def test_exceptions(self, exception):
        result = pickle.loads(pickle.dumps(exception))
        assert isinstance(result, type(exception))


class TestFormat:
    def test_header_parsing_errors(self):
        hpe = HeaderParsingError("defects", "unparsed_data")

        assert "defects" in str(hpe)
        assert "unparsed_data" in str(hpe)


class TestNewConnectionError:
    def test_pool_property_deprecation_warning(self):
        err = NewConnectionError(HTTPConnection("localhost"), "test")
        with pytest.warns(DeprecationWarning) as records:
            err.pool

        assert err.pool is err.conn
        msg = (
            "The 'pool' property is deprecated and will be removed "
            "in a later urllib3 v2.x release. use 'conn' instead."
        )
        assert any(record.message.args[0] == msg for record in records)

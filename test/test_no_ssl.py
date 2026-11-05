"""
Test what happens if Python was built without SSL

* Everything that does not involve HTTPS should still work
* HTTPS requests must fail with an error that points at the ssl module
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("without_ssl")


class TestImportWithoutSSL:
    def test_cannot_import_ssl(self) -> None:
        with pytest.raises(ImportError):
            import ssl  # noqa: F401

    def test_import_urllib3(self) -> None:
        from urllib3.connection import DummyConnection, HTTPSConnection

        assert HTTPSConnection is DummyConnection  # type: ignore[comparison-overlap]

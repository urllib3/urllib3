# -*- coding: utf-8 -*-
import mock


class TestSecureTransportBigSur(object):
    """
    Tests for macOS Big Sur's dynamic linker
    """

    @mock.patch("platform.mac_ver", return_value=("10.16", ("", "", ""), "x86_64"))
    def test_import_current_version(self, mock_mac_ver):
        try:
            import urllib3.contrib.securetransport as securetransport

        except ImportError:
            securetransport = None
        assert securetransport

    @mock.patch("platform.mac_ver", return_value=("11.0", ("", "", ""), "x86_64"))
    def test_import_future_version(self, mock_mac_ver):
        try:
            import urllib3.contrib.securetransport as securetransport

        except ImportError:
            securetransport = None
        assert securetransport

import os
import sys
import unittest
import pytest


def activate_sandbox():
    """
    Enables parts of the GAE sandbox that are relevant.

    Inserts the stub module import hook which causes the usage of appengine-specific
    httplib, httplib2, socket, etc.
    """
    from google.appengine.tools.devappserver2.python import sandbox
    from google.appengine.ext import testbed

    for name in list(sys.modules):
        if name in sandbox.dist27.MODULE_OVERRIDES:
            del sys.modules[name]
    sys.meta_path.insert(0, sandbox.StubModuleImportHook())
    sys.path_importer_cache = {}

    bed = testbed.Testbed()
    bed.activate()
    bed.init_urlfetch_stub()

    return bed


def deactivate_sandbox(bed):
    from google.appengine.tools.devappserver2.python import sandbox

    sys.meta_path = [
        x for x in sys.meta_path if not isinstance(x, sandbox.StubModuleImportHook)]
    sys.path_importer_cache = {}

    # Delete any instances of sandboxed modules.
    for name in list(sys.modules):
        if name in sandbox.dist27.MODULE_OVERRIDES:
            del sys.modules[name]

    if bed is not None:
        bed.deactivate()


class AppEngineSandboxTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        try:
            import dev_appserver
            dev_appserver.fix_sys_path()
        except ImportError:
            pytest.skip("App Engine SDK not available.")

        if sys.version_info[:2] != (2, 7):
            pytest.skip("App Engine only tests on py2.7")

    def setUp(self):
        try:
            self.bed = activate_sandbox()
        except ImportError:
            pytest.skip("App Engine SDK not available.")

    def tearDown(self):
        try:
            deactivate_sandbox(self.bed)
        except ImportError:
            pass


class MockResponse(object):
    def __init__(self, content, status_code, content_was_truncated, final_url, headers):
        import httplib
        from StringIO import StringIO

        self.content = content
        self.status_code = status_code
        self.content_was_truncated = content_was_truncated
        self.final_url = final_url
        self.header_msg = httplib.HTTPMessage(StringIO(''.join(
            ["%s: %s\n" % (k, v) for k, v in headers.iteritems()] + ["\n"])))
        self.headers = self.header_msg.items()

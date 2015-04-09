"""
Test what happens if Python was built without SSL

* Everything that does not involve HTTPS should still work
* HTTPS requests must fail with an error that points at the ssl module
"""

import sys
import unittest


class ImportBlocker(object):
    """
    Block Imports

    To be placed on ``sys.meta_path``. This ensures that the modules
    specified cannot be imported, even if they are a builtin.
    """
    def __init__(self, *namestoblock):
        self.namestoblock = namestoblock

    def find_module(self, fullname, path=None):
        if fullname in self.namestoblock:
            return self
        return None

    def load_module(self, fullname):
        raise ImportError('import of {0} is blocked'.format(fullname))


ssl_blocker = ImportBlocker('ssl', '_ssl')


class TestWithoutSSL(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        sys.modules.pop('ssl', None)
        sys.modules.pop('_ssl', None)
        sys.meta_path.insert(0, ssl_blocker)

    @classmethod
    def tearDownClass(cls):
        assert sys.meta_path.pop(0) == ssl_blocker

    def test_cannot_import_ssl(self):
        # python26 has neither contextmanagers (for assertRaises) nor
        # importlib.
        # 'import' inside 'lambda' is invalid syntax.
        def import_ssl():
            import ssl

        self.assertRaises(ImportError, import_ssl)

    def test_import_urllib3(self):
        import urllib3

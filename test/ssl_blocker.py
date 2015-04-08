"""
This module blocks importing SSL
"""

import sys


if any(name.startswith('urllib3') for name in sys.modules.keys()):
    raise ImportError('you must import the ssl_blocker before urllib3')


# Nosetest will have implicitly imported ssl by now
sys.modules.pop('ssl', None)
sys.modules.pop('_ssl', None)


class ImportBlocker(object):
    """
    Block Imports

    To be placed on ``sys.meta_path``. This ensures that the modules
    specified cannot be imported, even if they are a builtin.
    """
    def __init__(self, *namestoblock):
        self.namestoblock = dict.fromkeys(namestoblock)
        
    def find_module(self, fullname, path=None):
        if fullname in self.namestoblock:
            return self
        return None
    
    def load_module(self, fullname):
        raise ImportError('import of {0} is blocked'.format(fullname))


sys.meta_path.insert(0, ImportBlocker('ssl', '_ssl'))

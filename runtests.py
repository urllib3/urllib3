#!/usr/bin/env python

# Simple (too simple!) test running script, to tide us over until we get tox
# etc. working properly.
#
# 1) Creates a venv named like 'test-venv-py36', and tries to install the
#    required stuff into it. If you delete this it'll be recreated.
# 2) Rebuilds the _sync version of our code, and puts it into urllib3/_sync.
#    Yes, directly inside your source directory! We run the tests directly
#    against the source tree! (This is kinda handy though b/c it leaves the
#    source tree in an importable state for any manual testing you need to
#    do.)
# 3) Runs the tests. Any arguments are passed on to pytest.

import os.path
import sys
import subprocess
import shutil

def run(cmd):
    print(cmd)
    return subprocess.check_call(cmd)

venv = "test-venv-py{}{}".format(sys.version_info[0], sys.version_info[1])

if not os.path.exists(venv):
    print("-- Creating venv in {} --".format(venv))
    run([sys.executable, "-m", "venv", venv])

run([venv + "/bin/pip", "install", "-r", "dev-requirements.txt"])
# XX get rid of this:
run([venv + "/bin/pip", "install", "trio", "twisted[tls]"])

print("-- Rebuilding urllib3/_sync in source tree --")
run([sys.executable, "setup.py", "build"])
try:
    shutil.rmtree("urllib3/_sync")
except FileNotFoundError:
    pass
shutil.copytree("build/lib/urllib3/_sync", "urllib3/_sync")

print("-- Running tests --")
run([venv + "/bin/python", "-m", "pytest"] + list(sys.argv)[1:])

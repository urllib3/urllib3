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

from os.path import exists, join
import sys
import subprocess
import shutil

def run(cmd):
    print(cmd)
    return subprocess.check_call(cmd)

venv = "test-venv-py{}{}".format(sys.version_info[0], sys.version_info[1])

if not exists(venv):
    print("-- Creating venv in {} --".format(venv))
    run([sys.executable, "-m", "virtualenv", "-p", sys.executable, venv])

python_candidates = [
    join(venv, "bin", "python"),
    join(venv, "Scripts", "python.exe"),
]
for python_candidate in python_candidates:
    if exists(python_candidate):
        python = python_candidate
        break
else:
    raise RuntimeError("I don't understand this platform's virtualenv layout")

run([python, "-m", "pip", "install", "-r", "dev-requirements.txt"])
# XX get rid of this:
run([python, "-m", "pip", "install", "trio", "twisted[tls]"])

print("-- Rebuilding urllib3/_sync in source tree --")
run([python, "setup.py", "build"])
try:
    shutil.rmtree("urllib3/_sync")
except FileNotFoundError:
    pass
shutil.copytree("build/lib/urllib3/_sync", "urllib3/_sync")

print("-- Running tests --")
run([python, "-m", "pytest"] + list(sys.argv)[1:])

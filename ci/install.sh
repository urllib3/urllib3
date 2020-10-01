#!/bin/bash

set -exo pipefail


# Linux Setup
# Even when testing on Python 2, we need Python 3 for Nox. This detects if
# we're in one of the Travis Python 2 sessions and sets up the Python 3 install
# for Nox.
if ! python3 -m pip --version; then
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
    sudo python3 get-pip.py
    # https://github.com/theacodes/nox/issues/328
    sudo python3 -m pip install nox==2019.11.9
else
    # We're not in "dual Python" mode, so we can just install Nox normally.
    python3 -m pip install nox
fi

if [[ "${NOX_SESSION}" == "app_engine" ]]; then
    python -m pip install gcp-devrel-py-tools
    gcp-devrel-py-tools download-appengine-sdk "$(dirname ${GAE_SDK_PATH})"
fi

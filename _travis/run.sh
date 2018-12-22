#!/bin/bash

set -e
set -x

if [[ "$(uname -s)" == "Darwin" && "$TOXENV" == "py27" ]]; then
    export PATH="/Library/Frameworks/Python.framework/Versions/2.7/bin":$PATH
fi

if [ -n "${TOXENV}" ]; then
    python -m pip install tox
    tox
else
    downstream_script="${TRAVIS_BUILD_DIR}/_travis/downstream/${DOWNSTREAM}.sh"
    if [ ! -x "$downstream_script" ]; then
        exit 1
    fi
    $downstream_script install
    python -m pip install .
    $downstream_script run
fi

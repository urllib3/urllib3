#!/bin/bash

set -exo pipefail

if [ -n "${NOX_SESSION}" ]; then
    if [[ "$(uname -s)" == 'Darwin' ]]; then
        # Explicitly use python3 on macOS as `nox` is not in the PATH
        python3 -m nox -s "${NOX_SESSION}"
    else
        nox -s "${NOX_SESSION}"
    fi
else
    downstream_script="${TRAVIS_BUILD_DIR}/_travis/downstream/${DOWNSTREAM}.sh"
    if [ ! -x "$downstream_script" ]; then
        exit 1
    fi
    $downstream_script install
    python -m pip install .
    $downstream_script run
fi

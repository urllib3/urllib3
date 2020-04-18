#!/bin/bash

set -exo pipefail

if [ -n "${NOX_SESSION}" ]; then
    nox -s "${NOX_SESSION}"
else
    downstream_script="${TRAVIS_BUILD_DIR}/_travis/downstream/${DOWNSTREAM}.sh"
    if [ ! -x "$downstream_script" ]; then
        exit 1
    fi
    $downstream_script install
    python -m pip install .
    $downstream_script run
fi

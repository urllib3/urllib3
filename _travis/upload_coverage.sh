#!/bin/bash

set -exo pipefail

if [[ -e .coverage ]]; then
    python3 -m pip install codecov
    codecov --env TRAVIS_OS_NAME,NOX_SESSION
fi

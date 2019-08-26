#!/bin/bash

set -exo pipefail

if [[ -e .coverage ]]; then
    python -m pip install codecov
    pythom -m codecov --env TRAVIS_OS_NAME,NOX_SESSION
fi

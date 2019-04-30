#!/bin/bash

set -exo pipefail

if [[ -e .coverage ]]; then
    source .tox/${TOXENV}/bin/activate
    pip install codecov
    codecov --env TRAVIS_OS_NAME,TOXENV
fi

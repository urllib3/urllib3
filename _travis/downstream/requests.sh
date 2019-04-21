#!/bin/bash

set -exo pipefail

case "${1}" in
    install)
        git clone --depth 1 https://github.com/kennethreitz/requests
        cd requests
        git rev-parse HEAD
        python -m pip install -r ${TRAVIS_BUILD_DIR}/_travis/downstream/requests-requirements.txt
        ;;
    run)
        cd requests
        pytest tests/
        ;;
    *)
        exit 1
        ;;
esac

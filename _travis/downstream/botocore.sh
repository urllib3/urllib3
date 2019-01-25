#!/bin/bash

set -exo pipefail

case "${1}" in
    install)
        git clone --depth 1 https://github.com/boto/botocore
        cd botocore
        git rev-parse HEAD
        python scripts/ci/install
        ;;
    run)
        cd botocore
        python scripts/ci/run-tests
        ;;
    *)
        exit 1
        ;;
esac

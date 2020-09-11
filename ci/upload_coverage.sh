#!/bin/bash

set -exo pipefail

# Cribbed from Trio's ci.sh
function curl-harder() {
    for BACKOFF in 0 1 2 4 8 15 15 15 15; do
        sleep $BACKOFF
        if curl -fL --connect-timeout 5 "$@"; then
            return 0
        fi
    done
    return 1
}

if [ "$JOB_NAME" = "" ]; then
    JOB_NAME="${TRAVIS_OS_NAME}-${TRAVIS_PYTHON_VERSION:-unknown}"
fi

curl-harder -o codecov.sh https://codecov.io/bash
bash codecov.sh -f coverage.xml -n $JOB_NAME

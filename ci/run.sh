#!/bin/bash

set -exo pipefail

downstream_script="${TRAVIS_BUILD_DIR}/ci/downstream/${DOWNSTREAM}.sh"
if [ ! -x "$downstream_script" ]; then
    exit 1
fi
$downstream_script install
python -m pip install .
$downstream_script run

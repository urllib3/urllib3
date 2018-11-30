#!/bin/bash

set -e
set -x

if [[ "$(uname -s)" == "Darwin" && "$TOXENV" == "py27" ]]; then
    export PATH="/Library/Frameworks/Python.framework/Versions/2.7/bin":$PATH
fi

tox

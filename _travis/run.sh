#!/bin/bash

set -e
set -x

if [[ "$(uname -s)" == "Darwin" ]]; then
    case "${TOXENV}" in
        py27) MINOR=2.7 ;;
        py34) MINOR=3.4 ;;
        py35) MINOR=3.5 ;;
        py36) MINOR=3.6 ;;
        py37) MINOR=3.7 ;;
    esac
    export PATH="/Library/Frameworks/Python.framework/Versions/$MINOR/bin":$PATH
fi

tox --version
tox -- -v

#!/bin/bash

set -e
set -x

case "${1}" in
    install)
        git clone --depth 1 https://github.com/requests/requests
        cd requests
        git rev-parse HEAD
        python -m pip install pipenv
        pipenv install --dev --skip-lock
        ;;
    run)
        cd requests
        pipenv run py.test -n 8 --boxed
        ;;
    *)
        exit 1
        ;;
esac

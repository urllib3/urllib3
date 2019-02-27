#!/bin/bash

set -exo pipefail

case "${1}" in
    install)
        git clone --depth 1 https://github.com/kennethreitz/requests
        cd requests
        git rev-parse HEAD
        python -m pip install --upgrade pipenv
        pipenv install --dev --skip-lock
        
        # See: kennethreitz/requests/5004
        python -m pip install pytest-httpbin<1.0.0
        ;;
    run)
        cd requests
        pipenv run py.test -n 8 --boxed
        ;;
    *)
        exit 1
        ;;
esac

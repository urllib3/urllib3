#!/bin/bash

set -exo pipefail

case "${1}" in
    install)
        # Because Google's 'Brotli' package shares an importable name with
        # 'brotlipy' we need to make sure both implementations don't break.
        python -m pip install Brotli
        ;;
    run)
        pytest tests/
        ;;
    *)
        exit 1
        ;;
esac

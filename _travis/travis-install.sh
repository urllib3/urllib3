#!/bin/bash

set -ev

pip install tox

if [[ "${TOXENV}" == "gae" && ! -d ${GAE_PYTHONPATH} ]]; then
    python _travis/fetch_gae_sdk.py `dirname ${GAE_PYTHONPATH}`
fi

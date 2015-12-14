#!/bin/bash

set -ev

pip install tox==2.1.1

if [[ "${TOXENV}" == "gae" && ! -d ${GAE_PYTHONPATH} ]]; then
    python _travis/fetch_gae_sdk.py `dirname ${GAE_PYTHONPATH}`
fi

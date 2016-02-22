#!/bin/bash

set -ev

pip install tox==2.1.1

# Workaround Travis' old PyPy release. If Travis updates, we can remove this
# code.
if [[ "${TOXENV}" == pypy* ]]; then
    git clone https://github.com/yyuu/pyenv.git ~/.pyenv
    PYENV_ROOT="$HOME/.pyenv"
    PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"
    pyenv install pypy-4.0.1
    pyenv global pypy-4.0.1
    pyenv rehash
fi

if [[ "${TOXENV}" == "gae" && ! -d ${GAE_PYTHONPATH} ]]; then
    python _travis/fetch_gae_sdk.py `dirname ${GAE_PYTHONPATH}`
fi

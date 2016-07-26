#!/bin/bash

set -ev

pip install tox==2.1.1

# Workaround Travis' old PyPy releases. If Travis updates, we can remove this
# code.
if [[ "${TOXENV}" == pypy* ]]; then
    git clone https://github.com/yyuu/pyenv.git ~/.pyenv
    PYENV_ROOT="$HOME/.pyenv"
    PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"
    if [[ "${TOXENV}" == pypy3 ]]; then
        pypyver=pypy3.3-5.2-alpha1
    else
        pypyver=pypy-4.0.1
    fi
    pyenv install $pypyver
    pyenv global $pypyver
    pyenv rehash
fi

if [[ "${TOXENV}" == "gae" && ! -d ${GAE_PYTHONPATH} ]]; then
    python _travis/fetch_gae_sdk.py `dirname ${GAE_PYTHONPATH}`
fi

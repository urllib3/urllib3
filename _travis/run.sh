#!/bin/bash

set -e
set -x

if [[ "$(uname -s)" == "Darwin" ]]; then
    # initialize our pyenv
    PYENV_ROOT="$HOME/.pyenv"
    PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"

    # Use the good OpenSSL
    export LDFLAGS="-L$(brew --prefix openssl)/lib"
    export CFLAGS="-I$(brew --prefix openssl)/include"
fi

tox

#!/bin/bash

set -e
set -x

if [[ "$(uname -s)" == "Darwin" ]]; then
    # initialize our pyenv
    PYENV_ROOT="$HOME/.pyenv"
    PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"

    # Use the good OpenSSL for PyOpenSSL. This also links it statically into
    # cryptography, which more accurately reflects the way the wheel is used.
    export CRYPTOGRAPHY_OSX_NO_LINK_FLAGS="1"
    export LDFLAGS="$(brew --prefix openssl@1.1)/lib/libcrypto.a $(brew --prefix openssl@1.1)/lib/libssl.a"
    export CFLAGS="-I$(brew --prefix openssl@1.1)/include"
fi

tox

#!/bin/bash

set -e
set -x

if [[ "$(uname -s)" == 'Darwin' ]]; then
    sw_vers
    brew update || brew update

    brew outdated openssl || brew upgrade openssl
    brew install openssl@1.1

    # install pyenv
    git clone --depth 1 https://github.com/yyuu/pyenv.git ~/.pyenv
    PYENV_ROOT="$HOME/.pyenv"
    PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"

    case "${TOXENV}" in
        py26)
            pyenv install 2.6.9
            pyenv global 2.6.9
            ;;
        py27)
            curl -O https://bootstrap.pypa.io/get-pip.py
            python get-pip.py --user
            ;;
        py33)
            pyenv install 3.3.6
            pyenv global 3.3.6
            ;;
        py34)
            pyenv install 3.4.5
            pyenv global 3.4.5
            ;;
        py35)
            pyenv install 3.5.2
            pyenv global 3.5.2
            ;;
        py36)
            pyenv install 3.6.0
            pyenv global 3.6.0
            ;;
        pypy*)
            pyenv install "pypy-5.4.1"
            pyenv global "pypy-5.4.1"
            ;;
    esac
    pyenv rehash
    pip install -U setuptools
    pip install --user virtualenv
else
    pip install virtualenv
fi

pip install tox

if [[ "${TOXENV}" == "gae" ]]; then
    pip install gcp-devrel-py-tools
    gcp-devrel-py-tools download-appengine-sdk "$(dirname ${GAE_SDK_PATH})"
fi

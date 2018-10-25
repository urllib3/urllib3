#!/bin/bash

set -e
set -x

if [[ "$(uname -s)" == 'Darwin' ]]; then
    sw_vers
    brew update || brew update

    # https://github.com/travis-ci/travis-ci/issues/8826
    brew cask uninstall oclint

    brew outdated openssl || brew upgrade openssl
    brew install openssl@1.1

    # install pyenv
    git clone --depth 1 https://github.com/yyuu/pyenv.git ~/.pyenv
    PYENV_ROOT="$HOME/.pyenv"
    PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init -)"

    case "${TOXENV}" in
        py27)
            pyenv install 2.7.14
            pyenv global 2.7.14
            ;;
        py34)
            pyenv install 3.4.7
            pyenv global 3.4.7
            ;;
        py35)
            pyenv install 3.5.4
            pyenv global 3.5.4
            ;;
        py36)
            pyenv install 3.6.3
            pyenv global 3.6.3
            ;;
        py37)
            pyenv install 3.7-dev
            pyenv global 3.7-dev
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

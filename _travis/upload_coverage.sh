#!/bin/bash

set -e
set -x

source .tox/${TOXENV}/bin/activate
pip install codecov
codecov --env TRAVIS_OS_NAME,TOXENV

#!/bin/bash

set -exo pipefail

source .tox/${TOXENV}/bin/activate
pip install codecov
codecov --env TRAVIS_OS_NAME,TOXENV

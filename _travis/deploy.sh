#!/bin/bash

set -e
set -x

python -m pip install -U twine
python setup.py sdist bdist_wheel
twine upload dist/* -u $PYPI_USERNAME -p $PYPI_PASSWORD --skip-existing

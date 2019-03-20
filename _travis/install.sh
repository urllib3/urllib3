#!/bin/bash

set -exo pipefail

if [[ "$(uname -s)" == 'Darwin' ]]; then
    case "${TOXENV}" in
        py27) MACPYTHON=2.7.15 ;;
        py34) MACPYTHON=3.4.4 ;;
        py35) MACPYTHON=3.5.4 ;;
        py36) MACPYTHON=3.6.7 ;;
        py37) MACPYTHON=3.7.1 ;;
    esac

    MINOR=$(echo $MACPYTHON | cut -d. -f1,2)

    curl -Lo macpython.pkg https://www.python.org/ftp/python/${MACPYTHON}/python-${MACPYTHON}-macosx10.6.pkg
    sudo installer -pkg macpython.pkg -target /
    ls /Library/Frameworks/Python.framework/Versions/$MINOR/bin/
    PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/$MINOR/bin/python$MINOR
    # The pip in older MacPython releases doesn't support a new enough TLS
    curl https://bootstrap.pypa.io/get-pip.py | sudo $PYTHON_EXE
    $PYTHON_EXE -m pip install virtualenv

    # Enable TLS 1.3 on macOS
    sudo defaults write /Library/Preferences/com.apple.networkd tcp_connect_enable_tls13 1
else
    python -m pip install virtualenv
fi

if [[ "${TOXENV}" == "gae" ]]; then
    python -m pip install gcp-devrel-py-tools
    gcp-devrel-py-tools download-appengine-sdk "$(dirname ${GAE_SDK_PATH})"
fi

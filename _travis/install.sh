#!/bin/bash

set -exo pipefail


install_mac_python() {
    local FULL=$1
    local MINOR=$(echo $FULL | cut -d. -f1,2)
    local PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/${MINOR}/bin/python${MINOR}
    if [[ "$MINOR" == "3.5" ]]; then
        # The 3.5 python.org macOS build is only compiled with macOS 10.6
        local COMPILER=10.6
    else
        local COMPILER=10.9
    fi

    curl -Lo macpython.pkg https://www.python.org/ftp/python/${FULL}/python-${FULL}-macosx${COMPILER}.pkg
    sudo installer -pkg macpython.pkg -target /

    # The pip in older MacPython releases doesn't support a new enough TLS
    curl https://bootstrap.pypa.io/get-pip.py | sudo $PYTHON_EXE
    $PYTHON_EXE -m pip install virtualenv
}


if [[ "$(uname -s)" == 'Darwin' ]]; then
    # Mac OS setup.
    case "${NOX_SESSION}" in
        test-2.7) MACPYTHON=2.7.17 ;;
        test-3.5) MACPYTHON=3.5.4 ;;  # last binary release
        test-3.6) MACPYTHON=3.6.8 ;;  # last binary release
        test-3.7) MACPYTHON=3.7.6 ;;
        test-3.8) MACPYTHON=3.8.1 ;;
    esac

    install_mac_python $MACPYTHON

    # Install Nox
    python3 -m pip install nox

else
    # Linux Setup
    # Even when testing on Python 2, we need Python 3 for Nox. This detects if
    # we're in one of the Travis Python 2 sessions and sets up the Python 3 install
    # for Nox.
    if ! python3 -m pip --version; then
        curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
        sudo python3 get-pip.py
        sudo python3 -m pip install nox
    else
        # We're not in "dual Python" mode, so we can just install Nox normally.
        python3 -m pip install nox
    fi
fi

if [[ "${NOX_SESSION}" == "app_engine" ]]; then
    python -m pip install gcp-devrel-py-tools
    gcp-devrel-py-tools download-appengine-sdk "$(dirname ${GAE_SDK_PATH})"
fi

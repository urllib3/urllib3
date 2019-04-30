#!/bin/bash

set -exo pipefail


install_mac_python() {
    local FULL=$1
    local MINOR=$(echo $FULL | cut -d. -f1,2)
    local PYTHON_EXE=/Library/Frameworks/Python.framework/Versions/${MINOR}/bin/python${MINOR}

    # Already installed.
    if [[ -f "${PYTHON_EXE}" ]]; then
        return 0;
    fi

    curl -Lo macpython.pkg https://www.python.org/ftp/python/${FULL}/python-${FULL}-macosx10.6.pkg
    sudo installer -pkg macpython.pkg -target /

    # The pip in older MacPython releases doesn't support a new enough TLS
    curl https://bootstrap.pypa.io/get-pip.py | sudo $PYTHON_EXE
    $PYTHON_EXE -m pip install virtualenv
}


if [[ "$(uname -s)" == 'Darwin' ]]; then
    # Mac OS setup.
    case "${NOX_SESSION}" in
        test-2.7) MACPYTHON=2.7.15 ;;
        test-3.4) MACPYTHON=3.4.4 ;;
        test-3.5) MACPYTHON=3.5.4 ;;
        test-3.6) MACPYTHON=3.6.7 ;;
        test-3.7) MACPYTHON=3.7.1 ;;
    esac

    # Install additional versions as needed.
    install_mac_python $MACPYTHON

    # Always install 3.6 for Nox
    install_mac_python "3.6.7"

    # Enable TLS 1.3 on macOS
    sudo defaults write /Library/Preferences/com.apple.networkd tcp_connect_enable_tls13 1

    # Install Nox
    python3.6 -m pip install nox

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

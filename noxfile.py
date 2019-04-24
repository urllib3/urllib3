import shutil

import nox


def tests_impl(session, extras="socks,secure,brotli"):
    # Install deps and the package itself.
    session.install("-r", "dev-requirements.txt")
    session.install(".[{extras}]".format(extras=extras))

    # Show the pip version.
    session.run("pip", "--version")
    # Print the Python version and bytesize.
    session.run("python", "--version")
    session.run("python", "-c", "import struct; print(struct.calcsize('P') * 8)")
    # Print OpenSSL information.
    session.run("python", "-m", "OpenSSL.debug")

    # Inspired from https://github.com/pyca/cryptography
    # We use parallel mode and then combine here so that coverage.py will take
    # the paths like .tox/pyXY/lib/pythonX.Y/site-packages/urllib3/__init__.py
    # and collapse them into src/urllib3/__init__.py.

    session.run(
        "coverage", "run", "--parallel-mode", "-m",
        "pytest", "-r", "sx", "test",
        *session.posargs,
        env={
            "PYTHONWARNINGS": "always::DeprecationWarning"
        })
    session.run("coverage", "combine")
    session.run("coverage", "report", "-m")


@nox.session(python=["2.7", "3.4", "3.5", "3.6", "3.7", "3.8", "pypy"])
def test(session):
    tests_impl(session)


@nox.session(python=["2", "3"])
def no_brotli(session):
    tests_impl(session, extras="socks,secure")


@nox.session(python="2.7")
def app_engine(session):
    session.install("-r", "dev-requirements.txt")
    session.install(".")
    session.run(
            "coverage", "run", "--parallel-mode", "-m",
            "pytest", "-r", "sx", "test/appengine",
            *session.posargs)
    session.run("coverage", "combine")
    session.run("coverage", "report", "-m")


@nox.session
def lint(session):
    session.install("flake8")
    session.run("flake8", "--version")
    session.run("flake8", "setup.py", "docs", "dummyserver", "src", "test")


@nox.session
def docs(session):
    session.install("-r", "docs/requirements.txt")
    session.install(".[socks,secure,brotli]")

    session.chdir("docs")
    shutil.rmtree("_build")
    session.run("sphinx-build", "-W", ".", "_build/html")

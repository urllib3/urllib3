import os
import shutil
import subprocess

import nox

# Whenever type-hints are completed on a file it should be added here so that
# this file will continue to be checked by mypy. Errors from other files are
# ignored.
TYPED_FILES = {
    "src/urllib3/contrib/__init__.py",
    "src/urllib3/exceptions.py",
    "src/urllib3/fields.py",
    "src/urllib3/filepost.py",
    "src/urllib3/packages/__init__.py",
    "src/urllib3/packages/six.py",
    "src/urllib3/packages/ssl_match_hostname/__init__.py",
    "src/urllib3/packages/ssl_match_hostname/_implementation.py",
    "src/urllib3/util/queue.py",
    "src/urllib3/util/url.py",
}
SOURCE_FILES = [
    "docs/",
    "dummyserver/",
    "src/",
    "test/",
    "noxfile.py",
    "setup.py",
]


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
        "coverage",
        "run",
        "--parallel-mode",
        "-m",
        "pytest",
        "-r",
        "a",
        "--tb=native",
        "--no-success-flaky-report",
        *(session.posargs or ("test/",)),
        env={"PYTHONWARNINGS": "always::DeprecationWarning"},
    )
    session.run("coverage", "combine")
    session.run("coverage", "report", "-m")
    session.run("coverage", "xml")


@nox.session(python=["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "pypy"])
def test(session):
    tests_impl(session)


@nox.session(python=["2", "3"])
def google_brotli(session):
    # https://pypi.org/project/Brotli/ is the Google version of brotli, so
    # install it separately and don't install our brotli extra (which installs
    # brotlipy).
    session.install("brotli")
    tests_impl(session, extras="socks,secure")


@nox.session(python="2.7")
def app_engine(session):
    session.install("-r", "dev-requirements.txt")
    session.install(".")
    session.run(
        "coverage",
        "run",
        "--parallel-mode",
        "-m",
        "pytest",
        "-r",
        "sx",
        "test/appengine",
        *session.posargs,
    )
    session.run("coverage", "combine")
    session.run("coverage", "report", "-m")
    session.run("coverage", "xml")


@nox.session()
def format(session):
    """Run code formatters."""
    session.install("black", "isort")
    session.run("black", *SOURCE_FILES)
    session.run("isort", "--profile", "black", *SOURCE_FILES)

    lint(session)


@nox.session
def lint(session):
    session.install("flake8", "flake8-2020", "black", "isort", "mypy")
    session.run("flake8", "--version")
    session.run("black", "--version")
    session.run("isort", "--version")
    session.run("mypy", "--version")
    session.run("black", "--check", *SOURCE_FILES)
    session.run("isort", "--profile", "black", "--check", *SOURCE_FILES)
    session.run("flake8", *SOURCE_FILES)

    session.log("mypy --strict src/urllib3")
    all_errors, errors = [], []
    process = subprocess.run(
        ["mypy", "--strict", "src/urllib3"],
        env=session.env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Ensure that mypy itself ran successfully
    assert process.returncode in (0, 1)

    for line in process.stdout.split("\n"):
        all_errors.append(line)
        filepath = line.partition(":")[0]
        if filepath.replace(".pyi", ".py") in TYPED_FILES:
            errors.append(line)
    session.log("all errors count: {}".format(len(all_errors)))
    if errors:
        session.error("\n" + "\n".join(sorted(set(errors))))


@nox.session
def docs(session):
    session.install("-r", "docs/requirements.txt")
    session.install(".[socks,secure,brotli]")

    session.chdir("docs")
    if os.path.exists("_build"):
        shutil.rmtree("_build")
    session.run("sphinx-build", "-b", "html", "-W", ".", "_build/html")

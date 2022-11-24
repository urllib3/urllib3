from __future__ import annotations

import os
import shutil
import subprocess
import sys

import nox

SOURCE_FILES = [
    "docs/",
    "dummyserver/",
    "src/",
    "test/",
    "noxfile.py",
    "setup.py",
]


def tests_impl(
    session: nox.Session,
    extras: str = "socks,secure,brotli,zstd",
    byte_string_comparisons: bool = True,
) -> None:
    # Install deps and the package itself.
    session.install("-r", "dev-requirements.txt")
    session.install(f".[{extras}]")

    # Show the pip version.
    session.run("pip", "--version")
    # Print the Python version and bytesize.
    session.run("python", "--version")
    session.run("python", "-c", "import struct; print(struct.calcsize('P') * 8)")
    # Print OpenSSL information.
    session.run("python", "-m", "OpenSSL.debug")

    memray_supported = True
    if sys.implementation.name != "cpython" or sys.version_info < (3, 8):
        memray_supported = False  # pytest-memray requires CPython 3.8+
    elif sys.platform == "win32":
        memray_supported = False

    # Inspired from https://hynek.me/articles/ditch-codecov-python/
    # We use parallel mode and then combine in a later CI step
    session.run(
        "python",
        *(("-bb",) if byte_string_comparisons else ()),
        "-m",
        "coverage",
        "run",
        "--parallel-mode",
        "-m",
        "pytest",
        *("--memray", "--hide-memray-summary") if memray_supported else (),
        "-v",
        "-ra",
        f"--color={'yes' if 'GITHUB_ACTIONS' in os.environ else 'auto'}",
        "--tb=native",
        "--no-success-flaky-report",
        "--durations=10",
        "--strict-config",
        "--strict-markers",
        *(session.posargs or ("test/",)),
        env={"PYTHONWARNINGS": "always::DeprecationWarning"},
    )


@nox.session(python=["3.7", "3.8", "3.9", "3.10", "3.11", "pypy"])
def test(session: nox.Session) -> None:
    tests_impl(session)


@nox.session(python=["2.7"])
def unsupported_setup_py(session: nox.Session) -> None:
    # Can't check both returncode and output with session.run
    process = subprocess.run(
        ["python", "setup.py", "install"],
        env={**session.env},
        text=True,
        capture_output=True,
    )
    assert process.returncode == 1
    print(process.stderr)
    assert "Please use `python -m pip install .` instead." in process.stderr


@nox.session(python=["3"])
def test_brotlipy(session: nox.Session) -> None:
    """Check that if 'brotlipy' is installed instead of 'brotli' or
    'brotlicffi' that we still don't blow up.
    """
    session.install("brotlipy")
    tests_impl(session, extras="socks,secure", byte_string_comparisons=False)


def git_clone(session: nox.Session, git_url: str) -> None:
    """We either clone the target repository or if already exist
    simply reset the state and pull.
    """
    expected_directory = git_url.split("/")[-1]

    if expected_directory.endswith(".git"):
        expected_directory = expected_directory[:-4]

    if not os.path.isdir(expected_directory):
        session.run("git", "clone", "--depth", "1", git_url, external=True)
    else:
        session.run(
            "git", "-C", expected_directory, "reset", "--hard", "HEAD", external=True
        )
        session.run("git", "-C", expected_directory, "pull", external=True)


@nox.session()
def downstream_botocore(session: nox.Session) -> None:
    root = os.getcwd()
    tmp_dir = session.create_tmp()

    session.cd(tmp_dir)
    git_clone(session, "https://github.com/boto/botocore")
    session.chdir("botocore")
    for patch in [
        "0001-Mark-100-Continue-tests-as-failing.patch",
        "0002-Stop-relying-on-removed-DEFAULT_CIPHERS.patch",
    ]:
        session.run("git", "apply", f"{root}/ci/{patch}", external=True)
    session.run("git", "rev-parse", "HEAD", external=True)
    session.run("python", "scripts/ci/install")

    session.cd(root)
    session.install(".", silent=False)
    session.cd(f"{tmp_dir}/botocore")

    session.run("python", "-c", "import urllib3; print(urllib3.__version__)")
    session.run("python", "scripts/ci/run-tests")


@nox.session()
def downstream_requests(session: nox.Session) -> None:
    root = os.getcwd()
    tmp_dir = session.create_tmp()

    session.cd(tmp_dir)
    git_clone(session, "https://github.com/psf/requests")
    session.chdir("requests")
    session.run(
        "git", "apply", f"{root}/ci/0003-requests-removed-warnings.patch", external=True
    )
    session.run(
        "git", "apply", f"{root}/ci/0004-requests-chunked-requests.patch", external=True
    )
    session.run("git", "rev-parse", "HEAD", external=True)
    session.install(".[socks]", silent=False)
    session.install("-r", "requirements-dev.txt", silent=False)

    session.cd(root)
    session.install(".", silent=False)
    session.cd(f"{tmp_dir}/requests")

    session.run("python", "-c", "import urllib3; print(urllib3.__version__)")
    session.run("pytest", "tests")


@nox.session()
def format(session: nox.Session) -> None:
    """Run code formatters."""
    lint(session)


@nox.session
def lint(session: nox.Session) -> None:
    session.install("pre-commit")
    session.run("pre-commit", "run", "--all-files")

    mypy(session)


@nox.session(python="3.8")
def mypy(session: nox.Session) -> None:
    """Run mypy."""
    session.install("-r", "mypy-requirements.txt")
    session.run("mypy", "--version")
    session.run(
        "mypy",
        "dummyserver",
        "noxfile.py",
        "src/urllib3",
        "test",
    )


@nox.session
def docs(session: nox.Session) -> None:
    session.install("-r", "docs/requirements.txt")
    session.install(".[socks,secure,brotli,zstd]")

    session.chdir("docs")
    if os.path.exists("_build"):
        shutil.rmtree("_build")
    session.run("sphinx-build", "-b", "html", "-W", ".", "_build/html")

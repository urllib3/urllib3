import os
import shutil
import subprocess

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
    extras: str = "socks,secure,brotli",
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

    # Inspired from https://github.com/pyca/cryptography
    # We use parallel mode and then combine here so that coverage.py will take
    # the paths like .tox/pyXY/lib/pythonX.Y/site-packages/urllib3/__init__.py
    # and collapse them into src/urllib3/__init__.py.

    session.run(
        "python",
        *(("-bb",) if byte_string_comparisons else ()),
        "-m",
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


@nox.session(python=["3.7", "3.8", "3.9", "3.10", "3.11", "pypy"])
def test(session: nox.Session) -> None:
    tests_impl(session)


@nox.session(python=["2.7"])
def unsupported_python2(session: nox.Session) -> None:
    # Can't check both returncode and output with session.run
    process = subprocess.run(
        ["python", "setup.py", "install"],
        env={**session.env},
        text=True,
        capture_output=True,
    )
    assert process.returncode == 1
    print(process.stderr)
    assert "Unsupported Python version" in process.stderr


@nox.session(python=["3"])
def test_brotlipy(session: nox.Session) -> None:
    """Check that if 'brotlipy' is installed instead of 'brotli' or
    'brotlicffi' that we still don't blow up.
    """
    session.install("brotlipy")
    tests_impl(session, extras="socks,secure", byte_string_comparisons=False)


def git_clone(session: nox.Session, git_url: str) -> None:
    session.run("git", "clone", "--depth", "1", git_url, external=True)


@nox.session()
def downstream_botocore(session: nox.Session) -> None:
    root = os.getcwd()
    tmp_dir = session.create_tmp()

    session.cd(tmp_dir)
    git_clone(session, "https://github.com/boto/botocore")
    session.chdir("botocore")
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
    session.run("git", "apply", f"{root}/ci/requests.patch", external=True)
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
    session.install("pre-commit")
    session.run("pre-commit", "--version")

    process = subprocess.run(
        ["pre-commit", "run", "--all-files"],
        env=session.env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Ensure that pre-commit itself ran successfully
    assert process.returncode in (0, 1)

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
    session.install(".[socks,secure,brotli]")

    session.chdir("docs")
    if os.path.exists("_build"):
        shutil.rmtree("_build")
    session.run("sphinx-build", "-b", "html", "-W", ".", "_build/html")

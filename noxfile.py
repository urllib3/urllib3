from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import nox

nox.options.error_on_missing_interpreters = True


def tests_impl(
    session: nox.Session,
    extras: str = "socks,brotli,zstd,h2",
    # hypercorn dependency h2 compares bytes and strings
    # https://github.com/python-hyper/h2/issues/1236
    byte_string_comparisons: bool = False,
    integration: bool = False,
    pytest_extra_args: list[str] = [],
) -> None:
    # Retrieve sys info from the Python implementation under test
    # to avoid enabling memray when nox runs under CPython but tests PyPy
    session_python_info = session.run(
        "python",
        "-c",
        "import sys; print(sys.implementation.name, sys.version_info.releaselevel)",
        silent=True,
    ).strip()  # type: ignore[union-attr] # mypy doesn't know that silent=True  will return a string
    implementation_name, release_level = session_python_info.split(" ")

    # Install deps and the package itself.
    session.install("-r", "dev-requirements.txt")
    if len(extras) > 0:
        session.install(f".[{extras}]")
    else:
        session.install(".")
    # Show the pip version.
    session.run("pip", "--version")
    # Print the Python version and bytesize.
    session.run("python", "--version")
    session.run("python", "-c", "import struct; print(struct.calcsize('P') * 8)")
    # Print OpenSSL information.
    session.run("python", "-m", "OpenSSL.debug")

    memray_supported = True
    if implementation_name != "cpython" or release_level != "final":
        memray_supported = False
    elif sys.platform == "win32":
        memray_supported = False

    # Environment variables being passed to the pytest run.
    pytest_session_envvars = {
        "PYTHONWARNINGS": "always::DeprecationWarning",
        "COVERAGE_CORE": "sysmon",
    }

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
        *(("--integration",) if integration else ()),
        "--tb=native",
        "--durations=10",
        "--strict-config",
        "--strict-markers",
        "--disable-socket",
        "--allow-unix-socket",
        "--allow-hosts=localhost,127.0.0.1,::1,127.0.0.0,240.0.0.0",  # See `TARPIT_HOST`
        *pytest_extra_args,
        *(session.posargs or ("test/",)),
        env=pytest_session_envvars,
    )


@nox.session(
    python=[
        "3.9",
        "3.10",
        "3.11",
        "3.12",
        "3.13",
        "3.14",
        "pypy3.10",
    ]
)
def test(session: nox.Session) -> None:
    tests_impl(session)


@nox.session(python="3")
def test_integration(session: nox.Session) -> None:
    """Run integration tests"""
    tests_impl(session, integration=True)


@nox.session(python="3")
def test_brotlipy(session: nox.Session) -> None:
    """Check that if 'brotlipy' is installed instead of 'brotli' or
    'brotlicffi' that we still don't blow up.
    """
    session.install("brotlipy")
    tests_impl(session, extras="socks", byte_string_comparisons=False)


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


@nox.session(python="3.12")
def lint(session: nox.Session) -> None:
    session.install("pre-commit")
    session.run("pre-commit", "run", "--all-files")

    mypy(session)


@nox.session(python="3.12")
def pyodideconsole(session: nox.Session) -> None:
    # build wheel into dist folder
    session.install("build")
    session.run("python", "-m", "build")
    session.run(
        "cp",
        "test/contrib/emscripten/templates/pyodide-console.html",
        "dist/index.html",
        external=True,
    )
    session.cd("dist")
    session.run("python", "-m", "http.server")


@nox.session(python="3.12")
@nox.parametrize(
    "runner", ["node", "firefox", "chrome"], ids=["node", "firefox", "chrome"]
)
def emscripten(session: nox.Session, runner: str) -> None:
    """Test on Emscripten with Pyodide & Chrome / Firefox / Node.js"""
    if runner == "node":
        print(
            "Node version:",
            session.run("node", "--version", silent=True, external=True),
        )
    session.install("-r", "emscripten-requirements.txt")
    # make sure we have a dist dir for pyodide
    dist_dir = None
    if "PYODIDE_ROOT" in os.environ:
        # we have a pyodide build tree checked out
        # use the dist directory from that
        dist_dir = Path(os.environ["PYODIDE_ROOT"]) / "dist"
    else:
        # we don't have a build tree
        pyodide_version = "0.26.3"

        pyodide_artifacts_path = Path(session.cache_dir) / f"pyodide-{pyodide_version}"
        if not pyodide_artifacts_path.exists():
            print("Fetching pyodide build artifacts")
            session.run(
                "curl",
                "-L",
                f"https://github.com/pyodide/pyodide/releases/download/{pyodide_version}/pyodide-{pyodide_version}.tar.bz2",
                "--output-dir",
                session.cache_dir,
                "-O",
                external=True,
            )
            pyodide_artifacts_path.mkdir(parents=True)
            session.run(
                "tar",
                "-xjf",
                f"{pyodide_artifacts_path}.tar.bz2",
                "-C",
                str(pyodide_artifacts_path),
                "--strip-components",
                "1",
                external=True,
            )

        dist_dir = pyodide_artifacts_path
    session.run("python", "-m", "build")
    assert dist_dir is not None
    assert dist_dir.exists()
    tests_impl(
        session,
        extras="",
        pytest_extra_args=[
            "-x",
            "--runtime",
            f"{runner}-no-host",
            "--dist-dir",
            str(dist_dir),
            "test/contrib/emscripten",
            "-v",
        ],
    )


@nox.session(python="3.12")
def mypy(session: nox.Session) -> None:
    """Run mypy."""
    session.install("-r", "mypy-requirements.txt")
    session.run("mypy", "--version")
    session.run(
        "mypy",
        "-p",
        "dummyserver",
        "-m",
        "noxfile",
        "-p",
        "urllib3",
        "-p",
        "test",
    )


@nox.session
def docs(session: nox.Session) -> None:
    session.install("-r", "docs/requirements.txt")
    session.install(".[socks,brotli,zstd]")

    session.chdir("docs")
    if os.path.exists("_build"):
        shutil.rmtree("_build")
    session.run("sphinx-build", "-b", "html", "-W", ".", "_build/html")

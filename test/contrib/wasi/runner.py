from __future__ import annotations

import os
import subprocess
import sys
import tempfile

current_directory = os.path.dirname(os.path.abspath(__file__))
wit_path = os.path.join(current_directory, "../../../wasi-tools/wit")


def python_component(body: str) -> str:
    return f"""\
from wit_world import exports
import traceback
import sys
import json
import urllib3

class Run(exports.Run):
    def run(self) -> None:
        try:
{body}
        except Exception:
            sys.exit(f"error: {{traceback.format_exc()}}")
"""


def run_python_component(body: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        component_file = os.path.join(tmpdir, "main.py")
        wasm_file = os.path.join(tmpdir, "component.wasm")
        # generate python script implementing cli world
        with open(component_file, "w") as f:
            f.write(python_component(body))

        # generate wasm
        def run_componentize_py() -> None:
            args = [
                "componentize-py",
                "--import-interface-name",
                '"wasi:http/types@0.2.0"="types"',
                "--import-interface-name",
                '"wasi:http/outgoing-handler@0.2.0"="outgoing_handler"',
                "--wit-path",
                wit_path,
                "-w component",
                "componentize",
            ]

            # make sure we can find urllib in the component
            for path in sys.path:
                args += ["-p", path]

            args += ["-p", tmpdir, "-o", wasm_file, "main"]

            assert subprocess.run(args).returncode == 0

        run_componentize_py()
        # run using wasmtime
        assert (
            subprocess.run(["wasmtime", "run", "-S" "http=y", wasm_file]).returncode
            == 0
        )

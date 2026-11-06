#!/usr/bin/env python3
"""Read the pinned engine's literal NDK requirement without importing SCons modules."""

import ast
from pathlib import Path
import re
import sys


def ndk_version(engine: Path) -> str:
    module = ast.parse((engine / "platform/android/detect.py").read_text())
    function = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "get_ndk_version")
    values = [ast.literal_eval(node.value) for node in function.body if isinstance(node, ast.Return)]
    if len(values) != 1 or not isinstance(values[0], str) or not re.fullmatch(r"\d+\.\d+\.\d+", values[0]):
        raise ValueError("Expected one literal NDK version in engine get_ndk_version()")
    return values[0]


if __name__ == "__main__":
    print(ndk_version(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "godot"))

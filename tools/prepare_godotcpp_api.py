#!/usr/bin/env python3
"""Prepare the Godot API dump for the pinned godot-cpp generator.

The Migeran godot-cpp 4.5 generator emits the integer-limit globals that are
already provided by <cstdint>.  On Apple SDKs those names are macros, so the
generated C++ header is not compilable.  They are redundant in godot-cpp and
are removed from the derived API input while the original engine dump remains
unchanged.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


LIMIT_CONSTANTS = {
    "UINT8_MAX",
    "UINT16_MAX",
    "UINT32_MAX",
    "INT8_MIN",
    "INT8_MAX",
    "INT16_MIN",
    "INT16_MAX",
    "INT32_MIN",
    "INT32_MAX",
    "INT64_MIN",
    "INT64_MAX",
}

SUPPORTED_META = {
    "int8",
    "int16",
    "int32",
    "int64",
    "uint8",
    "uint16",
    "uint32",
    "uint64",
    "float",
    "double",
    "char16",
    "char32",
}


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {sys.argv[0]} INPUT OUTPUT", file=sys.stderr)
        return 2

    source = Path(sys.argv[1])
    destination = Path(sys.argv[2])
    api = json.loads(source.read_text(encoding="utf-8"))
    before = len(api.get("global_constants", []))
    api["global_constants"] = [
        constant
        for constant in api.get("global_constants", [])
        if constant.get("name") not in LIMIT_CONSTANTS
    ]
    removed = before - len(api["global_constants"])

    ignored_meta = 0

    def normalize_meta(value: object) -> None:
        nonlocal ignored_meta
        if isinstance(value, dict):
            if "meta" in value and value["meta"] not in SUPPORTED_META:
                del value["meta"]
                ignored_meta += 1
            for child in value.values():
                normalize_meta(child)
        elif isinstance(value, list):
            for child in value:
                normalize_meta(child)

    normalize_meta(api)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(api, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Prepared godot-cpp API: "
        f"removed {removed} redundant integer-limit globals and "
        f"ignored {ignored_meta} unsupported metadata fields."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check each Android C++ SDK slice against its API builtin layouts."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ABIS = {
    "arm64-v8a": ("float_64", 8, "aarch64-linux-android24"),
    "armeabi-v7a": ("float_32", 4, "armv7a-linux-androideabi24"),
}


def check_headers(api: dict, headers: Path, abi: str) -> dict:
    configuration, pointer_bytes, _ = ABIS[abi]
    sizes = next(item["sizes"] for item in api["builtin_class_sizes"]
                 if item["build_configuration"] == configuration)
    expected = {item["name"]: item["size"] for item in sizes}
    generator = runpy.run_path(str(ROOT / "godot-cpp/binding_generator.py"))
    generated = [item["name"] for item in api["builtin_classes"]
                 if not generator["is_pod_type"](item["name"])
                 and not generator["is_included_type"](item["name"])]
    if not {"String", "StringName"}.issubset(generated):
        raise ValueError("API does not describe the required String/StringName wrappers")
    if expected["String"] != pointer_bytes or expected["StringName"] != pointer_bytes:
        raise ValueError(f"Invalid pointer-sized API layouts for {abi}")
    for name in [*generated, "Variant"]:
        if name == "Variant":
            filename = "variant_size.hpp"
            pattern = r"^#define GODOT_CPP_VARIANT_SIZE\s+(\d+)\s*$"
        else:
            filename = generator["camel_to_snake"](name) + ".hpp"
            pattern = r"static constexpr size_t \w+_SIZE\s*=\s*(\d+)\s*;"
        header = headers / "godot_cpp/variant" / filename
        match = re.search(pattern, header.read_text(), re.MULTILINE)
        if not match or int(match[1]) != expected[name]:
            actual = match[1] if match else "missing"
            raise ValueError(f"{abi} {name}: header size {actual}, API {configuration} requires {expected[name]}")
    return {"abi": abi, "build_configuration": configuration,
            "pointer_bytes": pointer_bytes, "builtin_sizes": expected}


def layout_source(api: dict, sizes: dict, abi: str) -> str:
    generator = runpy.run_path(str(ROOT / "godot-cpp/binding_generator.py"))
    names = [item["name"] for item in api["builtin_classes"]
             if not generator["is_pod_type"](item["name"])] + ["Variant"]
    lines = ["#include <godot_cpp/variant/variant.hpp>", "#include <libgodot_android.h>",
             f'static_assert(sizeof(void *) == {ABIS[abi][1]}, "wrong compiler target");']
    for name in names:
        lines.append(f'static_assert(sizeof(godot::{name}) == {sizes[name]}, "{abi}: {name} layout mismatch");')
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", type=Path, required=True)
    parser.add_argument("--headers", type=Path, required=True)
    parser.add_argument("--abi", choices=ABIS, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        api = json.loads(args.api.read_text())
        result = check_headers(api, args.headers, args.abi)
        if args.compiler:
            subprocess.run([str(args.compiler), "--target=" + ABIS[args.abi][2],
                            "-std=c++17", "-fsyntax-only", "-I", str(args.headers), "-x", "c++", "-"],
                           input=layout_source(api, result["builtin_sizes"], args.abi), text=True, check=True)
        if not args.library.is_file() or not args.library.stat().st_size:
            raise ValueError(f"Missing or empty C++ library: {args.library}")
        with args.library.open("rb") as stream:
            library_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result.update(api_sha256=hashlib.sha256(args.api.read_bytes()).hexdigest(),
                      library_sha256=library_digest)
        if args.verify:
            if json.loads(args.manifest.read_text()) != result:
                raise ValueError("ABI layout manifest differs from API or library")
        else:
            args.manifest.write_text(json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Android C++ ABI check failed: {error}\n")
    print(f"Android C++ builtin layouts PASS: {args.abi}")


if __name__ == "__main__":
    main()

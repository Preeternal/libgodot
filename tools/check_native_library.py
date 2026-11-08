#!/usr/bin/env python3
"""Use the pinned engine's C-export validator with the actual slice architecture."""

import argparse
import json
from pathlib import Path
import runpy


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--platform", required=True)
parser.add_argument("--target", required=True)
parser.add_argument("--library-type", required=True)
parser.add_argument("--architecture", default="arm64", choices=("arm64", "arm32"))
parser.add_argument("--revision", required=True)
parser.add_argument("--library", type=Path, required=True)
parser.add_argument("--symbols", type=Path, required=True)
parser.add_argument("--manifest", type=Path, required=True)
parser.add_argument("--verify", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
validator = runpy.run_path(str(root / "godot/tests/libgodot/check_library.py"))["library_manifest"]
result = validator(args.library, args.symbols, args.platform, args.revision, args.target, args.library_type)
# The engine validator defaults to arm64; readelf/lipo checks the actual slice in CI.
result["architecture"] = args.architecture
if args.verify:
    if json.loads(args.manifest.read_text()) != result:
        raise SystemExit("Native library manifest differs from uploaded library")
else:
    args.manifest.write_text(json.dumps(result, indent=2) + "\n")
print(f"Native library exports/digest PASS: {args.library}")

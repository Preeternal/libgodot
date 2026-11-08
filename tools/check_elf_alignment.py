#!/usr/bin/env python3
"""Check ELF LOAD alignment: 16 KiB for Android arm64, 4 KiB for arm32."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program_headers", type=Path)
    parser.add_argument("--arch", required=True, choices=("arm32", "arm64"))
    args = parser.parse_args()
    minimum = 0x4000 if args.arch == "arm64" else 0x1000
    label = f"{args.arch} {minimum // 1024} KiB LOAD alignment"

    alignments = []
    for line in args.program_headers.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s*LOAD\s", line):
            alignments.append(int(line.split()[-1], 0))
    if not alignments or min(alignments) < minimum:
        print(f"{label} check failed: {alignments}")
        return 1
    print(f"{label}: PASS ({alignments})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

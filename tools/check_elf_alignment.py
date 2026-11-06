#!/usr/bin/env python3
"""Require 16 KiB alignment for every ELF LOAD segment."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} READelf_PROGRAM_HEADERS", file=sys.stderr)
        return 2

    alignments = []
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        if re.match(r"^\s*LOAD\s", line):
            alignments.append(int(line.split()[-1], 0))
    if not alignments or min(alignments) < 0x4000:
        print(f"16 KiB LOAD alignment check failed: {alignments}", file=sys.stderr)
        return 1
    print(f"16 KiB LOAD alignment: PASS ({alignments})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

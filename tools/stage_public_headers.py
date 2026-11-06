#!/usr/bin/env python3
"""Stage standalone C headers from the pinned engine and its dumped interface."""

import argparse
from pathlib import Path
import shutil


def stage_headers(engine: Path, interface: Path, output: Path, android: bool = False) -> None:
    output.mkdir(parents=True, exist_ok=True)
    header = (engine / "core/extension/libgodot.h").read_text()
    header = header.replace('"core/extension/gdextension_interface.gen.h"', '"gdextension_interface.h"')
    (output / "libgodot.h").write_text(header)
    shutil.copyfile(interface, output / "gdextension_interface.h")
    if android:
        shutil.copyfile(engine / "platform/android/libgodot_android.h", output / "libgodot_android.h")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--engine", type=Path, default=Path("godot"))
    parser.add_argument("--interface", type=Path, default=Path("build/gdextension/gdextension_interface.h"))
    parser.add_argument("--android", action="store_true")
    args = parser.parse_args()
    stage_headers(args.engine, args.interface, args.output, args.android)

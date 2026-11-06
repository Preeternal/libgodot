#!/usr/bin/env python3
"""Verify device Metal and Simulator OpenGL evidence without claiming runtime support."""

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess


DRIVERS = ("RenderingDeviceDriverMetal", "RenderingContextDriverMetal")
GL_DRIVERS = ("GLManagerApple", "RasterizerGLES3")
POLICY = {
    "device": {"driver": "metal", "rendering_method": "mobile",
               "expected_build_flags": {"metal": True, "opengl3": True, "vulkan": False}},
    "simulator": {"driver": "opengl3", "rendering_method": "gl_compatibility",
                  "expected_build_flags": {"metal": False, "opengl3": True, "vulkan": False}},
}


def driver_symbols(text: str, slice_name: str) -> dict:
    # Undefined references, RTTI and unrelated Metal helpers are not providers.
    defined = [parts[-1] for line in text.splitlines()
               if len(parts := line.split()) >= 3 and parts[-2] in ("T", "t")]
    drivers = DRIVERS if slice_name == "device" else GL_DRIVERS
    evidence = {driver: sorted(name for name in defined
                              if re.search(r"__?ZNK?" + str(len(driver)) + driver + r"\d", name))
                for driver in drivers}
    if missing := [name for name, symbols in evidence.items() if not symbols]:
        raise ValueError(f"Missing defined {POLICY[slice_name]['driver']} driver methods: {', '.join(missing)}")
    return evidence


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def archive_record(library: Path, symbols: Path, slice_name: str) -> dict:
    return {"slice": slice_name, **POLICY[slice_name], "binary_sha256": digest(library),
            "defined_driver_methods": driver_symbols(symbols.read_text(), slice_name),
            "evidence": "compiled driver methods only", "runtime": "UNVERIFIED"}


def build_version(load_commands: str, slice_name: str) -> str:
    blocks = re.findall(r"cmd LC_BUILD_VERSION\n(.*?)(?=Load command|\Z)", load_commands, re.DOTALL)
    expected = {"device": {"2", "IOS"}, "simulator": {"7", "IOSSIMULATOR"}}[slice_name]
    if len(blocks) != 1:
        raise ValueError("Expected one Mach-O LC_BUILD_VERSION for the selected architecture")
    platform = re.search(r"^\s*platform\s+(\S+)", blocks[0], re.MULTILINE)
    minimum = re.search(r"^\s*minos\s+(\S+)", blocks[0], re.MULTILINE)
    if not platform or platform[1] not in expected or not minimum:
        raise ValueError(f"Mach-O platform/deployment metadata does not match {slice_name}")
    return minimum[1]


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE)


def xcframework_record(directory: Path, required_slices=("device", "simulator")) -> dict:
    info = plistlib.loads((directory / "Info.plist").read_bytes())
    result = []
    for library in info["AvailableLibraries"]:
        if library["SupportedPlatform"] != "ios":
            raise ValueError("Expected iOS-only XCFramework")
        variant = library.get("SupportedPlatformVariant")
        if variant not in (None, "simulator"):
            raise ValueError(f"Unsupported iOS variant: {variant}")
        slice_name = "simulator" if variant else "device"
        identifier = library["LibraryIdentifier"]
        framework = directory / identifier / library["LibraryPath"]
        binary = framework / framework.stem
        architectures = command("lipo", "-archs", str(binary)).split()
        if sorted(architectures) != sorted(library["SupportedArchitectures"]):
            raise ValueError(f"XCFramework architecture metadata differs from binary: {identifier}")
        for arch in architectures:
            symbols = command("nm", "-arch", arch, "-gU", str(binary))
            minimum = build_version(command("otool", "-arch", arch, "-l", str(binary)), slice_name)
            dependencies = command("otool", "-arch", arch, "-L", str(binary))
            backend_framework = "Metal" if slice_name == "device" else "OpenGLES"
            if f"/{backend_framework}.framework/" not in dependencies or "/QuartzCore.framework/" not in dependencies:
                raise ValueError(f"Missing linked {backend_framework}/QuartzCore framework: {identifier}/{arch}")
            if slice_name == "device":
                evidence = {"defined_methods": driver_symbols(symbols, slice_name)}
            else:
                # strip -x removes local GL methods. Retained C++ type identities
                # plus EAGL/GL imports prove compiled GL code, not a successful frame.
                types = command("strings", "-arch", arch, "-a", str(binary)).splitlines()
                required_types = [str(len(name)) + name for name in GL_DRIVERS]
                if not set(required_types).issubset(types):
                    raise ValueError(f"Missing compiled GL backend type identities: {identifier}/{arch}")
                imports = command("nm", "-arch", arch, "-u", str(binary))
                required_imports = ("_OBJC_CLASS_$_EAGLContext", "_OBJC_CLASS_$_CAEAGLLayer", "_glGetError")
                if not set(required_imports).issubset(imports.split()):
                    raise ValueError(f"Missing EAGL/OpenGL imports: {identifier}/{arch}")
                evidence = {"type_identities": required_types, "system_imports": list(required_imports)}
            result.append({"slice": slice_name, "identifier": identifier, "architecture": arch,
                           "minimum_os": minimum, "binary_sha256": digest(binary),
                           **POLICY[slice_name], "compiled_evidence": evidence,
                           "linked_frameworks": re.findall(r"/([^/]+\.framework)/", dependencies),
                           "runtime": "UNVERIFIED"})
    if not set(required_slices).issubset({entry["slice"] for entry in result}):
        raise ValueError(f"iOS delivery requires slices: {', '.join(required_slices)}")
    return {"schema": "libgodot-ios-renderers/v1", "slices": result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--library", type=Path)
    source.add_argument("--xcframework", type=Path)
    parser.add_argument("--symbols", type=Path)
    parser.add_argument("--slice", choices=("device", "simulator"))
    parser.add_argument("--require-slice", action="append", choices=("device", "simulator"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.library and (not args.symbols or not args.slice):
        parser.error("--library requires --symbols and --slice")
    try:
        result = (xcframework_record(args.xcframework, args.require_slice or ("device", "simulator")) if args.xcframework
                  else archive_record(args.library, args.symbols, args.slice))
        if args.verify:
            if json.loads(args.manifest.read_text()) != result:
                raise ValueError("Renderer slice manifest differs from the binary evidence")
        else:
            args.manifest.write_text(json.dumps(result, indent=2) + "\n")
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"iOS renderer check failed: {error}\n")
    print("iOS compiled renderer evidence PASS; runtime remains UNVERIFIED")


if __name__ == "__main__":
    main()

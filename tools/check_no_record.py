#!/usr/bin/env python3
"""Check native playback references and reject microphone APIs in mobile binaries."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
import io
import xml.etree.ElementTree as ET


FORBIDDEN = {
    "ios": (b"AVAudioApplication", b"requestRecordPermission", b"recordPermission",
            b"AVAudioSessionCategoryRecord", b"AVAudioSessionCategoryPlayAndRecord",
            b"AVAudioSessionCategoryMultiRoute", b"AVMediaTypeAudio", b"AudioUnitRender\0"),
    "android": (b"SL_IID_RECORD\0", b"RECORD_AUDIO"),
}
PLAYBACK = {
    "ios": (b"AudioOutputUnitStart", b"AudioUnitInitialize"),
    "android": (b"slCreateEngine", b"SL_IID_PLAY\0"),
}


def inspect(data: bytes, platform: str, name: str) -> dict:
    if not data.startswith((b"!<arch>\n", b"\x7fELF", b"\xcf\xfa\xed\xfe",
                            b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe",
                            b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf")):
        raise ValueError(f"Not a native library: {name}")
    forbidden = [token.rstrip(b"\0").decode() for token in FORBIDDEN[platform] if token in data]
    missing = [token.rstrip(b"\0").decode() for token in PLAYBACK[platform] if token not in data]
    if forbidden or missing:
        raise ValueError(f"{name}: microphone references={forbidden}; missing playback references={missing}")
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
            "playback_references": [token.rstrip(b"\0").decode() for token in PLAYBACK[platform]]}


def inspect_aar(data: bytes, name: str) -> list:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        libraries = sorted(n for n in archive.namelist() if n.startswith("jni/") and n.endswith("/libgodot_android.so"))
        expected = {"jni/arm64-v8a/libgodot_android.so", "jni/armeabi-v7a/libgodot_android.so"}
        if set(libraries) != expected:
            raise ValueError(f"{name}: expected ARM32 and ARM64 engine libraries, got {libraries}")
        return [inspect(archive.read(n), "android", f"{name}!{n}") for n in libraries]


def inspect_library(path: Path, platform: str) -> dict:
    data = path.read_bytes()
    if platform == "ios" and data.startswith(b"!<arch>\n"):
        # Archives may contain LLVM bitcode and DWARF declarations of unused SDK
        # APIs. Inspect imports here; scan selectors in the final linked framework.
        imports = subprocess.check_output(["nm", "-u", str(path)], stderr=subprocess.PIPE)
        record = inspect(b"!<arch>\n" + imports.replace(b"\n", b"\0"), platform, path.name)
        record.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
                      inspection_scope="archive imports; final framework audit checks Objective-C selectors")
        return record
    return inspect(data, platform, path.name)


def inspect_maven(path: Path, version: str | None) -> list:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        aars = [n for n in names if n.endswith(".aar")]
        poms = [n for n in names if n.endswith(".pom")]
        if len(aars) != 1 or len(poms) != 1:
            raise ValueError(f"Expected one release AAR and POM, got {aars}, {poms}")
        if any("SNAPSHOT" in n for n in names):
            raise ValueError("Release Maven repository still contains SNAPSHOT coordinates")
        pom = ET.fromstring(archive.read(poms[0]))
        actual = pom.findtext("{*}version")
        if not actual or "SNAPSHOT" in actual or (version and actual != version):
            raise ValueError(f"Unexpected Maven POM version: {actual}; expected {version}")
        if not aars[0].endswith(f"/godot/{actual}/godot-{actual}.aar"):
            raise ValueError("Maven repository layout does not match the POM coordinate")
        return inspect_aar(archive.read(aars[0]), aars[0])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=FORBIDDEN, required=True)
    parser.add_argument("--library", type=Path, action="append", default=[])
    parser.add_argument("--xcframework", type=Path)
    parser.add_argument("--aar", type=Path)
    parser.add_argument("--maven-zip", type=Path)
    parser.add_argument("--maven-version", default=os.environ.get("GODOT_PUBLISH_VERSION"))
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    libraries = list(args.library)
    if args.xcframework:
        if args.platform != "ios":
            parser.error("--xcframework requires --platform ios")
        libraries += sorted(args.xcframework.glob("*/libgodot.framework/libgodot"))
        if not libraries:
            raise ValueError("XCFramework contains no engine binaries")
    results = []
    for path in libraries:
        record = inspect_library(path, args.platform)
        if args.xcframework:
            record["name"] = str(path.relative_to(args.xcframework))
        results.append(record)
    if args.aar or args.maven_zip:
        if args.platform != "android":
            parser.error("AAR/Maven validation requires --platform android")
        if args.aar:
            results += inspect_aar(args.aar.read_bytes(), args.aar.name)
        if args.maven_zip:
            results += inspect_maven(args.maven_zip, args.maven_version)
    if not results:
        parser.error("Provide native libraries or a package")
    manifest = {"schema": "libgodot-no-record/v1", "audio_variant": "no-record",
                "platform": args.platform, "microphone_api_references": [], "libraries": results,
                "runtime_playback": "not verified by binary inspection"}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"No-record binary audit PASS: {len(results)} libraries")


if __name__ == "__main__":
    main()

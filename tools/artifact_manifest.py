#!/usr/bin/env python3
"""Generate/verify the complete uploaded file inventory and build provenance."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from engine_config import ndk_version


ROOT = Path(__file__).resolve().parents[1]


def command(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def revisions() -> dict:
    return {name: command("git", "rev-parse", "HEAD", cwd=ROOT / directory)
            for name, directory in (("libgodot", "."), ("godot", "godot"), ("godot_cpp", "godot-cpp"))}


def inventory(directory: Path) -> dict:
    return {str(path.relative_to(directory)): {"bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path != directory / "artifacts-manifest.json"}


def verify(directory: Path) -> dict:
    manifest = json.loads((directory / "artifacts-manifest.json").read_text())
    if manifest["revisions"] != revisions():
        raise ValueError("Artifact source revisions do not match this checkout")
    for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if os.environ.get(key) and manifest["run"].get(key) != os.environ[key]:
            raise ValueError(f"Artifact is not from this run/attempt: {key}")
    if manifest["files"] != inventory(directory):
        raise ValueError("Uploaded file inventory/digests differ from manifest")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--profile")
    parser.add_argument("--flags", default="")
    parser.add_argument("--api-dir", type=Path, default=ROOT / "build/gdextension")
    args = parser.parse_args()
    if args.verify:
        verify(args.directory)
        print(f"Artifact inventory/provenance PASS: {args.directory}")
        return
    if not args.profile:
        parser.error("--profile is required when generating")
    args.directory.mkdir(parents=True, exist_ok=True)
    tools = {"python": command("python3", "--version"), "scons": command("scons", "--version"),
             "python_hash_seed": os.environ.get("PYTHONHASHSEED", "random")}
    if command("uname", "-s") == "Darwin":
        tools.update(xcode=command("xcodebuild", "-version"),
                     ios_sdk=command("xcrun", "--sdk", "iphoneos", "--show-sdk-version"),
                     simulator_sdk=command("xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"),
                     macos_sdk=command("xcrun", "--sdk", "macosx", "--show-sdk-version"))
    else:
        tools["clang"] = command("clang", "--version")
    if args.profile.startswith("android"):
        tools["ndk"] = ndk_version(ROOT / "godot")
        tools["java"] = command("java", "-version")
        tools["gradle_wrapper"] = (ROOT / "godot/platform/android/java/gradle/wrapper/gradle-wrapper.properties").read_text()
        tools["android_sdk_config"] = (ROOT / "godot/platform/android/java/app/config.gradle").read_text().split("ext.getExportPackageName")[0]
    contract = {}
    for name in ("extension_api.json", "godotcpp_extension_api.json", "gdextension_interface.h", "gdextension_interface.json"):
        path = args.api_dir / name
        if not path.is_file():
            raise ValueError(f"Missing generated contract: {path}")
        contract[name] = digest(path)
    version = json.loads((args.api_dir / "extension_api.json").read_text())["header"]
    manifest = {
        "schema": "libgodot-ci-artifacts/v1", "profile": args.profile,
        "revisions": revisions(), "run": {key: os.environ.get(key) for key in
            ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REPOSITORY")},
        "version": version, "build_flags": args.flags, "tools": tools,
        "build_scripts_sha256": {name: digest(ROOT / name) for name in
            ("build_libgodot.sh", "build_libgodot_xcframework.sh", "build_godotcpp_android.sh",
             "build_godotcpp_xcframework.sh", "tools/prepare_godotcpp_api.py",
             "tools/check_android_cpp_abi.py")},
        "contract_sha256": contract,
        "debug_symbols": "See file inventory: Android unstripped native libraries; iOS framework dSYM directories",
        "files": inventory(args.directory),
    }
    (args.directory / "artifacts-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify(args.directory)
    print(f"Artifact manifest written and verified: {args.directory}")


if __name__ == "__main__":
    main()

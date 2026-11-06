#!/usr/bin/env python3
"""Regression checks for the package include closure and artifact integrity gates."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import artifact_manifest
from stage_public_headers import stage_headers
from engine_config import ndk_version


ROOT = Path(__file__).resolve().parents[1]


class ArtifactsTest(unittest.TestCase):
    def test_ios_packaging_requires_sdl_providers_before_framework_build(self):
        # Exercise the packaging script with a real validator and inert native tools.
        # No compiler, SCons or xcodebuild is executed by this fixture.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(ROOT / "build_libgodot_xcframework.sh", root)
            checker = root / "godot/tests/libgodot/check_library.py"
            checker.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "godot/tests/libgodot/check_library.py", checker)
            archive = root / "godot/bin/libgodot.ios.template_release.arm64.a"
            archive.parent.mkdir(parents=True)
            archive.write_bytes(b"archive fixture; nm output is supplied below")
            for name in ("build/gdextension/gdextension_interface.h",
                         "godot/core/extension/libgodot.h",
                         "libgodot_framework/libgodot/placeholder"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("/* fixture */\n")
            commands = root / "commands"
            commands.mkdir()
            scripts = {
                "uname": "echo Darwin\n",
                "sysctl": "echo 2\n",
                "git": "echo " + "a" * 40 + "\n",
                "nm": 'cat "$SDL_TEST_SYMBOLS"\n',
                "xcodebuild": 'touch "$SDL_TEST_LINK_MARKER"\nexit 77\n',
                # macOS uses sed -i ''; header rewriting is unrelated to this gate.
                "sed": "exit 0\n",
            }
            for name, body in scripts.items():
                path = commands / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(0o755)
            symbols = root / "symbols.txt"
            marker = root / "framework-link-invoked"
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
                       SDL_TEST_SYMBOLS=str(symbols), SDL_TEST_LINK_MARKER=str(marker))
            exports = "0000 T _libgodot_create_godot_instance\n0000 T _libgodot_destroy_godot_instance\n"
            sdl = ("SDL_IsTablet", "SDL_IsTV", "SDL_IsIPad", "SDL_IsAppleTV")
            for missing in (("SDL_IsIPad", "SDL_IsAppleTV"), ("SDL_IsAppleTV",), ()):
                with self.subTest(missing=missing):
                    marker.unlink(missing_ok=True)
                    symbols.write_text(exports + "".join(
                        f"{' U' if name in missing else '0000 T'} _{name}\n" for name in sdl))
                    result = subprocess.run(["/bin/bash", str(root / "build_libgodot_xcframework.sh"),
                                             "--target", "template_release", "--no-sim"],
                                            env=env, capture_output=True, text=True)
                    if missing:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("Missing defined iOS SDL symbols", result.stderr)
                        self.assertFalse(marker.exists(), "Invalid archive reached framework build")
                    else:
                        self.assertEqual(result.returncode, 77, result.stdout + result.stderr)
                        self.assertTrue(marker.exists(), "Valid fixture did not reach the link step")

    def test_elf_alignment_uses_abi_specific_minimum(self):
        for arch, alignment, expected in (("arm32", 4096, 0), ("arm32", 16384, 0),
                                           ("arm32", 2048, 1), ("arm64", 4096, 1),
                                           ("arm64", 16384, 0), ("arm64", 65536, 0)):
            with self.subTest(arch=arch, alignment=alignment), tempfile.TemporaryDirectory() as tmp:
                headers = Path(tmp) / "program-headers.txt"
                headers.write_text(f"  LOAD 0x0 0x0 0x0 0x100 0x100 R E {alignment:#x}\n" * 3)
                result = subprocess.run([sys.executable, str(ROOT / "tools/check_elf_alignment.py"),
                                         str(headers), "--arch", arch], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_elf_alignment_rejects_missing_load_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            headers = Path(tmp) / "program-headers.txt"
            headers.write_text("Type Offset VirtAddr PhysAddr FileSiz MemSiz Flg Align\n")
            for arch in ("arm32", "arm64"):
                result = subprocess.run([sys.executable, str(ROOT / "tools/check_elf_alignment.py"),
                                         str(headers), "--arch", arch], capture_output=True)
                self.assertEqual(result.returncode, 1)

    def test_elf_alignment_requires_explicit_supported_architecture(self):
        for arguments in ([], ["--arch", "unknown"]):
            result = subprocess.run([sys.executable, str(ROOT / "tools/check_elf_alignment.py"),
                                     "unused.txt", *arguments], capture_output=True)
            self.assertEqual(result.returncode, 2)

    def test_ndk_query_does_not_import_engine_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp)
            source = engine / "platform/android"
            source.mkdir(parents=True)
            (source / "detect.py").write_text('import nonexistent_engine_module\ndef get_ndk_version():\n    return "29.0.14206865"\n')
            self.assertEqual(ndk_version(engine), "29.0.14206865")
        self.assertRegex(ndk_version(ROOT / "godot"), r"^\d+\.\d+\.\d+$")

    def test_inventory_retains_both_abis_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for abi, value in (("arm64-v8a", b"arm64"), ("armeabi-v7a", b"arm32")):
                (directory / abi).mkdir()
                (directory / abi / "libgodot_android.so").write_bytes(value)
            data = {"revisions": {"godot": "engine"}, "run": {},
                    "files": artifact_manifest.inventory(directory)}
            manifest = directory / "artifacts-manifest.json"
            manifest.write_text(json.dumps(data))
            with mock.patch.object(artifact_manifest, "revisions", return_value=data["revisions"]), \
                    mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(len(artifact_manifest.verify(directory)["files"]), 2)
                (directory / "arm64-v8a/libgodot_android.so").write_bytes(b"arm32")
                with self.assertRaisesRegex(ValueError, "inventory/digests"):
                    artifact_manifest.verify(directory)

    def test_rejects_other_engine_and_other_ci_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            data = {"revisions": {"godot": "old"}, "run": {"GITHUB_RUN_ID": "old"}, "files": {}}
            (directory / "artifacts-manifest.json").write_text(json.dumps(data))
            with mock.patch.object(artifact_manifest, "revisions", return_value={"godot": "new"}):
                with self.assertRaisesRegex(ValueError, "revisions"):
                    artifact_manifest.verify(directory)
            with mock.patch.object(artifact_manifest, "revisions", return_value=data["revisions"]), \
                    mock.patch.dict(os.environ, {"GITHUB_RUN_ID": "new"}):
                with self.assertRaisesRegex(ValueError, "run/attempt"):
                    artifact_manifest.verify(directory)

    def test_android_headers_are_self_contained(self):
        # Host syntax only; a tiny JNI declaration fixture does not emulate an Android build.
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            stage_headers(ROOT / "godot", ROOT / "build/gdextension/gdextension_interface.h", output, True)
            (output / "jni.h").write_text("typedef struct JNIEnv JNIEnv;\ntypedef void *jobject;\n")
            for compiler, language in (("clang", "c"), ("clang++", "c++")):
                subprocess.run([compiler, "-I", str(output), "-Wall", "-Wextra", "-Werror",
                                "-x", language, "-fsyntax-only", "-"],
                               input="#include <libgodot_android.h>\n", text=True, check=True)


if __name__ == "__main__":
    unittest.main()

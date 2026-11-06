#!/usr/bin/env python3
"""Regression checks for the package include closure and artifact integrity gates."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import artifact_manifest
from stage_public_headers import stage_headers


ROOT = Path(__file__).resolve().parents[1]


class ArtifactsTest(unittest.TestCase):
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

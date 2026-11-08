#!/usr/bin/env python3
"""Static capture/output checks and negative controls; never build the engine."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile

import artifact_manifest
from check_no_record import FORBIDDEN, PLAYBACK, inspect, inspect_aar, inspect_library, inspect_maven


ROOT = Path(__file__).resolve().parents[1]


def preprocess(name, disabled):
    # Exercise the real preprocessor branches without SDK headers or compilation.
    source = (ROOT / "godot" / name).read_text()
    source = re.sub(r"^\s*#\s*(include|import)\b[^\n]*", "", source, flags=re.M)
    source = re.sub(r"^\s*#pragma once\b[^\n]*", "", source, flags=re.M)
    definitions = ["COREAUDIO_ENABLED", "APPLE_EMBEDDED_ENABLED", "ANDROID_ENABLED", "LIBGODOT_ENABLED"]
    if disabled:
        definitions.append("AUDIO_INPUT_DISABLED")
    return subprocess.check_output(["clang", "-E", "-P", "-x", "objective-c++", "-",
                                    *["-D" + value for value in definitions]], input=source, text=True)


def fixture(platform):
    magic = b"\xcf\xfa\xed\xfe" if platform == "ios" else b"\x7fELF"
    return magic + b"\0".join(PLAYBACK[platform])


class NoRecordTest(unittest.TestCase):
    def test_ios_permissions_are_compiled_out_with_positive_control(self):
        path = "drivers/apple_embedded/os_apple_embedded.mm"
        stripped = preprocess(path, True)
        full = preprocess(path, False)
        for token in ("AVAudioApplication", "requestRecordPermissionWithCompletionHandler", "recordPermission"):
            self.assertNotIn(token, stripped)
            self.assertIn(token, full)

    def test_coreaudio_capture_is_absent_but_output_is_retained(self):
        path = "drivers/coreaudio/audio_driver_coreaudio.mm"
        stripped = preprocess(path, True)
        full = preprocess(path, False)
        for token in ("AudioDriverCoreAudio::input_callback", "AudioUnitRender(", "init_input_device(", "finish_input_device("):
            self.assertNotIn(token, stripped)
            self.assertIn(token, full)
        for token in ("AudioDriverCoreAudio::output_callback", "AudioOutputUnitStart(audio_unit)", "audio_server_process", "AudioDriverCoreAudio::input_start()"):
            self.assertIn(token, stripped)
        header = preprocess("drivers/coreaudio/audio_driver_coreaudio.h", True)
        self.assertNotIn("init_input_device", header)
        self.assertIn("input_start() override", header)

    def test_ios_session_cannot_select_record_capable_categories(self):
        path = "drivers/apple_embedded/app_delegate_service.mm"
        stripped = preprocess(path, True)
        full = preprocess(path, False)
        for token in ("AVAudioSessionCategoryRecord", "AVAudioSessionCategoryPlayAndRecord", "AVAudioSessionCategoryMultiRoute"):
            self.assertNotIn(token, stripped)
            self.assertIn(token, full)
        self.assertIn("AVAudioSessionCategoryPlayback", stripped)

    def test_android_capture_is_absent_but_output_is_retained(self):
        path = "platform/android/audio_driver_opensl.cpp"
        stripped = preprocess(path, True)
        full = preprocess(path, False)
        for token in ("CreateAudioRecorder", "SL_IID_RECORD", "RECORD_AUDIO", "AudioDriverOpenSL::_record_buffer_callback"):
            self.assertNotIn(token, stripped)
            self.assertIn(token, full)
        for token in ("CreateAudioPlayer", "SL_IID_PLAY", "AudioDriverOpenSL::_buffer_callback", "AudioDriverOpenSL::input_start()"):
            self.assertIn(token, stripped)
        self.assertNotIn("android.permission.RECORD_AUDIO", preprocess("platform/android/java_godot_lib_jni.cpp", True))

    def test_server_rejects_capture_before_marking_it_active(self):
        source = preprocess("servers/audio/audio_server.cpp", True)
        function = source.split("Error AudioServer::set_input_device_active(bool p_is_active) {", 1)[1].split("\n}", 1)[0]
        self.assertLess(function.index("return ERR_UNAVAILABLE"), function.index("input_device_active = true"))
        self.assertNotIn("--disable-audio-recording", source)

    def test_binary_gate_rejects_every_microphone_reference(self):
        for platform in FORBIDDEN:
            clean = fixture(platform)
            self.assertIn("sha256", inspect(clean, platform, "fixture"))
            for token in FORBIDDEN[platform]:
                with self.subTest(platform=platform, token=token), self.assertRaises(ValueError):
                    inspect(clean + b"\0" + token, platform, "fixture")

    def test_binary_gate_rejects_dummy_or_missing_output_and_non_binaries(self):
        for platform in PLAYBACK:
            for token in PLAYBACK[platform]:
                with self.subTest(platform=platform, token=token), self.assertRaises(ValueError):
                    inspect(fixture(platform).replace(token, b""), platform, "fixture")
            with self.assertRaises(ValueError):
                inspect(b"not a library " + fixture(platform), platform, "fixture")

    def test_aar_requires_both_clean_abis(self):
        def aar(libraries):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as archive:
                for abi, data in libraries.items():
                    archive.writestr(f"jni/{abi}/libgodot_android.so", data)
            return stream.getvalue()
        clean = fixture("android")
        self.assertEqual(len(inspect_aar(aar({"arm64-v8a": clean, "armeabi-v7a": clean}), "fixture")), 2)
        with self.assertRaises(ValueError):
            inspect_aar(aar({"arm64-v8a": clean}), "fixture")
        with self.assertRaises(ValueError):
            inspect_aar(aar({"arm64-v8a": clean, "armeabi-v7a": clean + b"SL_IID_RECORD\0"}), "fixture")

    def test_audio_unit_render_type_is_not_a_capture_function_reference(self):
        inspect(fixture("ios") + b"AudioUnitRenderActionFlags\0", "ios", "fixture")
        # The OpenSL interface type contains this field even in output-only DWARF.
        inspect(fixture("android") + b"CreateAudioRecorder\0", "android", "fixture")

    def test_archive_import_audit_ignores_unused_sdk_declarations(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "fixture.a"
            archive.write_bytes(b"!<arch>\nDWARF: AVAudioApplication recordPermission\0")
            imports = b" U _AudioOutputUnitStart\n U _AudioUnitInitialize\n"
            with mock.patch("check_no_record.subprocess.check_output", return_value=imports):
                record = inspect_library(archive, "ios")
                self.assertEqual(record["bytes"], archive.stat().st_size)
                self.assertIn("archive imports", record["inspection_scope"])
            with mock.patch("check_no_record.subprocess.check_output", return_value=imports + b" U _OBJC_CLASS_$_AVAudioApplication\n"):
                with self.assertRaises(ValueError):
                    inspect_library(archive, "ios")

    def test_maven_release_requires_matching_immutable_coordinate(self):
        aar = io.BytesIO()
        with zipfile.ZipFile(aar, "w") as archive:
            for abi in ("arm64-v8a", "armeabi-v7a"):
                archive.writestr(f"jni/{abi}/libgodot_android.so", fixture("android"))
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "maven.zip"
            expected = "4.7.2.preeternal.2"
            for version in (expected, "4.7.2.preeternal.1-SNAPSHOT", "4.7.2.preeternal.1"):
                prefix = f"com/migeran/libgodot/godot/{version}/godot-{version}"
                with zipfile.ZipFile(package, "w") as archive:
                    archive.writestr(prefix + ".aar", aar.getvalue())
                    archive.writestr(prefix + ".pom", f'<project xmlns="http://maven.apache.org/POM/4.0.0"><version>{version}</version></project>')
                if version == expected:
                    self.assertEqual(len(inspect_maven(package, expected)), 2)
                else:
                    with self.assertRaises(ValueError):
                        inspect_maven(package, expected)

    def test_older_engine_fails_before_any_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(ROOT / "build_libgodot.sh", root)
            (root / "godot").mkdir()
            (root / "godot/SConstruct").write_text("# old engine\n")
            commands = root / "commands"
            commands.mkdir()
            sysctl = commands / "sysctl"
            sysctl.write_text('#!/bin/sh\necho 2\n')
            sysctl.chmod(0o755)
            marker = root / "scons-called"
            scons = commands / "scons"
            scons.write_text(f'#!/bin/sh\ntouch "{marker}"\nexit 99\n')
            scons.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"], LIBGODOT_AUDIO_VARIANT="no-record")
            result = subprocess.run(["bash", str(root / "build_libgodot.sh"), "--target", "ios", "--no-host"], env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("lacks audio_input=no support", result.stderr)
            self.assertFalse(marker.exists())

    def test_manifest_refuses_other_variant_and_missing_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            data = {"profile": "ios-packages", "audio_variant": "with-recording", "revisions": {}, "run": {}, "files": {}}
            path = directory / "artifacts-manifest.json"
            path.write_text(json.dumps(data))
            # The synthetic artifact has no run metadata; isolate it from Actions.
            with mock.patch.object(artifact_manifest, "revisions", return_value={}), mock.patch.dict(os.environ, {"LIBGODOT_AUDIO_VARIANT": "no-record"}, clear=True):
                with self.assertRaisesRegex(ValueError, "Expected no-record"):
                    artifact_manifest.verify(directory)
                data["audio_variant"] = "no-record"
                path.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, "Missing no-record"):
                    artifact_manifest.verify(directory)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Regression coverage for mixed-width Android SDK packaging (no native builds)."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from check_android_cpp_abi import check_headers


ROOT = Path(__file__).resolve().parents[1]


def fixture_api():
    return {
        "builtin_classes": [{"name": name} for name in ("String", "StringName", "PackedByteArray")],
        "builtin_class_sizes": [
            {"build_configuration": f"float_{bits}", "sizes": [
                {"name": "String", "size": bits // 8},
                {"name": "StringName", "size": bits // 8},
                {"name": "PackedByteArray", "size": bits // 4},
                {"name": "Variant", "size": 24},
            ]} for bits in (32, 64)],
    }


def fixture_headers(root, bits):
    folder = root / "godot_cpp/variant"
    folder.mkdir(parents=True)
    for name, size in (("string", bits // 8), ("string_name", bits // 8), ("packed_byte_array", bits // 4)):
        (folder / (name + ".hpp")).write_text(f"static constexpr size_t WRAPPER_SIZE = {size};\n")
    (folder / "variant_size.hpp").write_text("#define GODOT_CPP_VARIANT_SIZE 24\n")


class AndroidCppAbiTest(unittest.TestCase):
    def test_layout_check_rejects_swapped_or_partially_corrupt_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_headers(root / "arm32", 32)
            fixture_headers(root / "arm64", 64)
            api = fixture_api()
            for abi, correct, wrong in (("arm64-v8a", "arm64", "arm32"),
                                         ("armeabi-v7a", "arm32", "arm64")):
                self.assertEqual(check_headers(api, root / correct, abi)["abi"], abi)
                with self.assertRaisesRegex(ValueError, "header size"):
                    check_headers(api, root / wrong, abi)
            header = root / "arm64/godot_cpp/variant/packed_byte_array.hpp"
            header.write_text("static constexpr size_t PACKED_BYTE_ARRAY_SIZE = 8;\n")
            with self.assertRaisesRegex(ValueError, "PackedByteArray"):
                check_headers(api, root / "arm64", "arm64-v8a")
            header.unlink()
            with self.assertRaises(OSError):
                check_headers(api, root / "arm64", "arm64-v8a")

    def test_packager_keeps_each_generators_headers_in_both_build_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(ROOT / "build_godotcpp_android.sh", root)
            for name in ("prepare_godotcpp_api.py", "engine_config.py", "stage_public_headers.py",
                         "check_android_cpp_abi.py"):
                (root / "tools").mkdir(exist_ok=True)
                shutil.copy2(ROOT / "tools" / name, root / "tools" / name)
            (root / "godot-cpp").mkdir()
            shutil.copy2(ROOT / "godot-cpp/binding_generator.py", root / "godot-cpp")
            for name, content in {
                "build/gdextension/extension_api.json": json.dumps(fixture_api()),
                "build/gdextension/gdextension_interface.h": "/* interface */\n",
                "godot/core/extension/libgodot.h": '#include "core/extension/gdextension_interface.gen.h"\n',
                "godot/platform/android/libgodot_android.h": '#include "libgodot.h"\n',
                "godot/platform/android/detect.py": 'def get_ndk_version():\n    return "29.0.14206865"\n',
                "godot-cpp/include/source-header.hpp": "/* source header */\n",
            }.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            commands = root / "commands"
            commands.mkdir()
            scons = commands / "scons"
            scons.write_text(f"#!{sys.executable}\n" + '''import pathlib, shutil, sys
args = dict(arg.split('=', 1) for arg in sys.argv[1:])
assert args['precision'] == 'single'
bits = 64 if args['arch'] == 'arm64' else 32
gen = pathlib.Path('gen/include')
shutil.rmtree(gen, ignore_errors=True)
folder = gen / 'godot_cpp/variant'
folder.mkdir(parents=True)
for name, size in [('string', bits // 8), ('string_name', bits // 8), ('packed_byte_array', bits // 4)]:
    (folder / (name + '.hpp')).write_text(f'static constexpr size_t WRAPPER_SIZE = {size};\\n')
(folder / 'variant_size.hpp').write_text('#define GODOT_CPP_VARIANT_SIZE 24\\n')
pathlib.Path('bin').mkdir(exist_ok=True)
pathlib.Path(f"bin/libgodot-cpp.android.template_release.{args['arch']}.a").write_bytes(str(bits).encode())
''')
            scons.chmod(0o755)
            sdk = root / "sdk"
            for host in ("darwin-x86_64", "linux-x86_64"):
                compiler = sdk / f"ndk/29.0.14206865/toolchains/llvm/prebuilt/{host}/bin/clang++"
                compiler.parent.mkdir(parents=True)
                # This only checks invocation/target selection, not C++ compilation.
                compiler.write_text(f"#!{sys.executable}\n" + '''import sys
source = sys.stdin.read()
bits = 8 if 'aarch64' in sys.argv[1] else 4
assert f'sizeof(void *) == {bits}' in source
assert f'sizeof(godot::StringName) == {bits}' in source
''')
                compiler.chmod(0o755)
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"], ANDROID_HOME=str(sdk))
            for order in ("arm64 arm32", "arm32 arm64"):
                with self.subTest(order=order):
                    result = subprocess.run(["/bin/bash", str(root / "build_godotcpp_android.sh"),
                                             "--target", "template_release", "--target-arch-list", order],
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    package = root / "build/godot-cpp-android/release/godot-cpp-android"
                    self.assertFalse((package / "include").exists())
                    for abi, bits in (("arm64-v8a", 64), ("armeabi-v7a", 32)):
                        folder = package / abi
                        check_headers(fixture_api(), folder / "include", abi)
                        self.assertEqual((folder / "libgodot-cpp.a").read_bytes(), str(bits).encode())
                        self.assertTrue((folder / "include/source-header.hpp").exists())
                        self.assertTrue((folder / "include/libgodot_android.h").exists())
                        self.assertEqual(json.loads((folder / "abi-layout.json").read_text())["pointer_bytes"], bits // 8)


if __name__ == "__main__":
    unittest.main()

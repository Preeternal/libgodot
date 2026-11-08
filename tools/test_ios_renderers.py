#!/usr/bin/env python3
"""Regression checks for the iOS device/Simulator renderer contract."""

from pathlib import Path
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from check_ios_renderers import build_version, driver_symbols, xcframework_record

ROOT = Path(__file__).resolve().parents[1]


METAL = ("0000 T __ZN26RenderingDeviceDriverMetal10initializeEv\n"
         "0001 T __ZN27RenderingContextDriverMetal10initializeEv\n")
GL = ("0000 t __ZN14GLManagerApple10initializeEv\n"
      "0001 T __ZN15RasterizerGLES310initializeEv\n")


class IosRendererTest(unittest.TestCase):
    def test_build_script_requests_the_renderer_for_each_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copy2(ROOT / "build_libgodot.sh", root)
            (root / "godot").mkdir()
            headers = root / "build/gdextension"
            headers.mkdir(parents=True)
            (headers / "extension_api.json").write_text("{}\n")
            (headers / "gdextension_interface.h").write_text("/* fixture */\n")
            commands = root / "commands"
            commands.mkdir()
            for name, body in {"uname": 'case "$1" in -s) echo Darwin;; *) echo arm64;; esac\n',
                               "sysctl": "echo 2\n"}.items():
                path = commands / name
                path.write_text("#!/bin/sh\n" + body)
                path.chmod(0o755)
            scons = commands / "scons"
            scons.write_text(f"#!{sys.executable}\nimport json,os,sys\n"
                             "open(os.environ['TEST_SCONS_ARGS'], 'w').write(json.dumps(sys.argv[1:]))\n")
            scons.chmod(0o755)
            log = root / "scons-arguments.json"
            env = dict(os.environ, PATH=str(commands) + os.pathsep + os.environ["PATH"],
                       TEST_SCONS_ARGS=str(log))
            for simulator in (False, True):
                args = ["/bin/bash", str(root / "build_libgodot.sh"), "--no-host", "--target", "ios",
                        "--target-arch", "arm64", "--release"] + (["--simulator"] if simulator else [])
                result = subprocess.run(args, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                flags = json.loads(log.read_text())
                self.assertIn("metal=no" if simulator else "metal=yes", flags)
                self.assertNotIn("metal=yes" if simulator else "metal=no", flags)
                self.assertIn("opengl3=yes", flags)
                self.assertIn("vulkan=no", flags)

    def test_requires_defined_methods_of_both_driver_classes(self):
        self.assertEqual(len(driver_symbols(METAL, "device")), 2)
        self.assertEqual(len(driver_symbols(GL, "simulator")), 2)
        for slice_name, good in (("device", METAL), ("simulator", GL)):
            for symbols in ("", good.replace(" T ", " U ").replace(" t ", " U "),
                            good.replace(" T ", " V ").replace(" t ", " V "), good.splitlines()[0]):
                with self.subTest(slice=slice_name, symbols=symbols), self.assertRaisesRegex(ValueError, "Missing defined"):
                    driver_symbols(symbols, slice_name)
        with self.assertRaises(ValueError):
            driver_symbols(METAL, "simulator")

    def test_rejects_wrong_platform_or_missing_deployment_metadata(self):
        for slice_name, platform in (("device", "2"), ("simulator", "7")):
            data = f"      cmd LC_BUILD_VERSION\n platform {platform}\n minos 15.0\n sdk 26.5\n"
            self.assertEqual(build_version(data, slice_name), "15.0")
            with self.assertRaisesRegex(ValueError, "platform/deployment"):
                build_version(data, "device" if slice_name == "simulator" else "simulator")
            with self.assertRaises(ValueError):
                build_version(data.replace(" minos 15.0\n", ""), slice_name)

    def test_final_package_checks_each_slice_and_retains_runtime_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            libraries = []
            for identifier, variant in (("ios-arm64", None), ("ios-arm64-simulator", "simulator")):
                framework = directory / identifier / "libgodot.framework"
                framework.mkdir(parents=True)
                (framework / "libgodot").write_bytes(identifier.encode())
                entry = {"LibraryIdentifier": identifier, "LibraryPath": "libgodot.framework",
                         "SupportedPlatform": "ios", "SupportedArchitectures": ["arm64"]}
                if variant:
                    entry["SupportedPlatformVariant"] = variant
                libraries.append(entry)
            info = directory / "Info.plist"
            info.write_bytes(plistlib.dumps({"AvailableLibraries": libraries}))
            bad_symbols = False
            bad_platform = False
            bad_dependencies = False

            def command(*args):
                simulator = "simulator" in args[-1]
                if args[0] == "lipo":
                    return "arm64\n"
                if args[0] == "nm":
                    if "-u" in args:
                        return "_OBJC_CLASS_$_EAGLContext\n_OBJC_CLASS_$_CAEAGLLayer\n_glGetError\n"
                    return GL if simulator else METAL
                if args[0] == "strings":
                    return "" if bad_symbols else "14GLManagerApple\n15RasterizerGLES3\n"
                if args[-2] == "-l":
                    platform = "2" if bad_platform or not simulator else "7"
                    return f"cmd LC_BUILD_VERSION\n platform {platform}\n minos 15.0\n sdk 26.5\n"
                return ("" if bad_dependencies else
                        "/System/Library/Frameworks/Metal.framework/Metal\n"
                        "/System/Library/Frameworks/OpenGLES.framework/OpenGLES\n"
                        "/System/Library/Frameworks/QuartzCore.framework/QuartzCore\n")

            with mock.patch("check_ios_renderers.command", side_effect=command):
                result = xcframework_record(directory)
                self.assertEqual({row["slice"] for row in result["slices"]}, {"device", "simulator"})
                self.assertTrue(all(row["minimum_os"] == "15.0" for row in result["slices"]))
                self.assertTrue(all(row["runtime"] == "UNVERIFIED" for row in result["slices"]))
                bad_symbols = True
                with self.assertRaisesRegex(ValueError, "Missing compiled GL"):
                    xcframework_record(directory)
                bad_symbols = False
                bad_platform = True
                with self.assertRaisesRegex(ValueError, "platform/deployment"):
                    xcframework_record(directory)
                bad_platform = False
                bad_dependencies = True
                with self.assertRaisesRegex(ValueError, "linked Metal/QuartzCore"):
                    xcframework_record(directory)
                bad_dependencies = False
                info.write_bytes(plistlib.dumps({"AvailableLibraries": libraries[:1]}))
                with self.assertRaisesRegex(ValueError, "requires slices"):
                    xcframework_record(directory)
                self.assertEqual(len(xcframework_record(directory, ("device",))["slices"]), 1)


if __name__ == "__main__":
    unittest.main()

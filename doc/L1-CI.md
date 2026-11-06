# L1 CI candidate

The build workflow runs for pushes to `libgodot_47`, pull requests and manual
dispatch. It checks out the exact Godot and godot-cpp gitlinks over HTTPS.
SwiftGodot and SwiftGodotKit are not used by these jobs.

One macOS host job builds the editor and dumps the API/interface. All native
jobs consume that same verified contract and use --no-host; Android arm32 and
arm64 compile in separate parallel jobs. Package jobs consume both native ABIs
and never build an editor. SCons caches are enabled for engine and godot-cpp,
including saving completed objects after later packaging failures. This avoids
the former repeated editor builds and sequential Android native builds without
dropping native, ABI, alignment, packaging or lifecycle coverage.
Python hash seed is fixed for stable generated C++ declaration ordering and
cache keys; final already-compressed iOS archives are uploaded without a second
compression pass.

The native engine jobs remain local to this workflow: G1 builds do not verify
these packaging scripts, AAR/headers, XCFrameworks or this binding pipeline.
Cross-repository binary reuse would additionally require verified engine SHA,
flags, slices, toolchains and immutable artifact provenance; it is not enabled.

The workflow produces these same-run artifacts:

| Artifact | Contents |
| --- | --- |
| libgodot-host | same-run macOS editor and generated API/interface with provenance |
| libgodot-android-arm64 / libgodot-android-arm32 | per-ABI native library, libc++ runtime, symbols and source/contract manifest |
| libgodot-android | arm64-v8a/armeabi-v7a engine libraries and per-ABI manifests, AAR, godot-cpp SDK, dumped API/interface, logs |
| libgodot-ios-device | arm64 device static library, dumped contract, tools and source manifest |
| libgodot-ios-simulator | arm64 simulator static library, dumped contract, tools and source manifest |
| libgodot-macos | arm64 template_debug shared library, editor, dumped contract, tools and source manifest |
| libgodot-ios-xcframeworks | zipped engine and godot-cpp XCFrameworks, embedded engine dSYMs, native input provenance and logs |
| libgodot-contract | API/binding compilation, public C ABI lifecycle/recreate and DNS shutdown evidence |

The native host editor uses Vulkan with Volk (dynamic loader) and Metal, so it
does not require a MoltenVK SDK to compile. The pinned engine's NDK version is
read as literal configuration by tools/engine_config.py, without importing the
engine's SCons modules from the superproject working directory.

Each successful job writes `artifacts-manifest.json` with separate engine,
build-repo and binding SHAs, run ID/attempt, tool versions, build flags and
SHA-256/size inventory of the uploaded files. Download the complete artifact
into a separate directory. From its matching superproject/submodule checkout:

```sh
python3 tools/artifact_manifest.py /absolute/path/to/downloaded-artifact --verify
```

The package and contract jobs verify native input inventories and revisions
before consuming them. CI archives are candidate inputs for the subsequent R1
task; physical-device rendering and React Native integration are separate gates.
The checked-in `l1-artifacts-manifest.json` records local preparation evidence;
it is not a checksum manifest for future GitHub builds.

Local checks without engine or mobile builds, after generating the API:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tools/test_ci_tools.py -v
python3 godot/tests/libgodot/check_api.py build/gdextension/extension_api.json
git diff --check
```

All jobs retain logs on failure. A failed job can upload incomplete diagnostics
without a manifest; that upload is not an accepted binary candidate. Re-run all
producer jobs when changing the run attempt, since consumers require matching
run ID and attempt. Release/publish operations are not part of these workflows.

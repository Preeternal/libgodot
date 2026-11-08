# Continuous integration

The [build workflow](../.github/workflows/libgodot_builds.yml) runs on pushes to
`libgodot_47`, pull requests and manual dispatch. It checks out the exact Godot
and godot-cpp submodule commits over HTTPS. These jobs do not use SwiftGodot or
SwiftGodotKit.

Mobile targets default to the [no-record audio variant](Audio-variants.md).
Manual dispatch can select `with-recording`; both variants retain playback.
The host editor and macOS contract jobs keep their regular audio configuration.

## Build pipeline

One macOS host job builds the editor and generates the extension API and
interface headers. Native jobs consume this same verified contract with
`--no-host`; Android ARM32 and ARM64 libraries build in parallel. Package jobs
use the native outputs to create the Android AAR/C++ SDK and iOS XCFrameworks.

SCons caches retain compiled objects, including when a later packaging step
fails. A fixed Python hash seed keeps generated C++ declaration ordering
consistent. Already-compressed iOS archives are uploaded without another
compression pass.

Native libraries are built in this repository's workflow so that the build
flags, generated headers, bindings and packages are checked together. Binaries
from other workflows or repositories are not reused automatically.

## Validation

- Android architecture, public exports and ELF LOAD alignment: at least 16 KiB
  for ARM64 and 4 KiB for ARM32.
- Per-ABI godot-cpp headers and builtin storage sizes, checked against the API
  dump with NDK C/C++ syntax checks.
- iOS architecture, SDL helper definitions and renderer evidence: Metal for
  devices, OpenGL ES 3 for Simulator.
- Final XCFramework architecture/platform metadata, deployment targets,
  framework dependencies and binary hashes.
- Public C headers, generated bindings, drawable contracts, instance cleanup
  and recreate smoke checks.
- Source revisions, generated contract hashes and complete artifact inventories.
- For no-record mobile builds, absence of microphone API references and retained
  audio output references in native libraries and final packages.

GPU rendering, input and lifecycle behavior must also be tested in consumer
applications on the relevant devices and renderers. Compilation and package
checks alone do not establish runtime compatibility.

## Workflow artifacts

| Artifact | Contents |
| --- | --- |
| libgodot-host | macOS editor, generated API/interface, drawable checks and provenance |
| libgodot-android-arm64 / libgodot-android-arm32 | Native library, C++ runtime, symbols and source/contract manifest for one ABI |
| libgodot-android | ARM64/ARM32 engine libraries, AAR, per-ABI C++ SDK, generated contract, manifests and logs |
| libgodot-ios-device | ARM64 device static library, generated contract, source/renderer manifests and tools |
| libgodot-ios-simulator | ARM64 Simulator static library, generated contract, source/renderer manifests and tools |
| libgodot-macos | ARM64 template_debug shared library, editor, generated contract, manifest and tools |
| libgodot-ios-xcframeworks | Engine and godot-cpp XCFramework archives, engine dSYMs, renderer metadata, native input provenance and logs |
| libgodot-contract | API/binding compilation and public C ABI lifecycle/recreate diagnostics |

All workflow artifact names above append `-no-record` or `-with-recording` to
identify the selected mobile build. Android packages include a local Maven ZIP,
the AAR and a zipped C++ SDK. Engine ZIP filenames also contain the audio variant.
The reusable contract workflow receives the same artifact suffix.

The host editor uses Vulkan with Volk and Metal, so it does not require a
MoltenVK SDK. `tools/engine_config.py` reads the pinned engine's NDK requirement
without importing its SCons modules.

## Artifact verification

Each successful job writes `artifacts-manifest.json` with engine, build-repository
and binding commits; run ID/attempt; tool versions; build flags; and SHA-256/size
inventory. Download the complete artifact into its own directory, then verify
it from the matching repository and submodule checkout:

```sh
python3 tools/artifact_manifest.py /path/to/downloaded-artifact --verify
```

Package and contract jobs verify native inputs before consuming them. Inputs
must come from the same workflow run and attempt. When retrying a workflow,
run the producers and consumers together rather than mixing attempts.

Failed jobs retain logs and may upload incomplete diagnostics without a
manifest. Such uploads are not complete binary packages.

## Local release packaging

With the required build toolchains installed:

```sh
./build_prebuilt_release.sh
python3 tools/artifact_manifest.py build/prebuilt/release/no-record --verify
```

The script builds and packages the mobile libraries and bindings, then writes
the combined manifest only after successful completion. Output is placed in
`build/prebuilt/release/<variant>`. Release publishing is a separate operation; the build
workflows do not create GitHub releases.

After generating the API, local checks can run without rebuilding the engine:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools -p 'test_*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 godot/tests/libgodot/check_drawables.py -v
python3 godot/tests/libgodot/check_api.py build/gdextension/extension_api.json
git diff --check
```

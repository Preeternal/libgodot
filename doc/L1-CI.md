# L1 CI candidate

The build workflow runs for pushes to `libgodot_47`, pull requests and manual
dispatch. It checks out the exact Godot and godot-cpp gitlinks over HTTPS.
SwiftGodot and SwiftGodotKit are not used by these jobs.

The workflow produces these same-run artifacts:

| Artifact | Contents |
| --- | --- |
| libgodot-android | arm64-v8a/armeabi-v7a engine libraries and per-ABI manifests, AAR, godot-cpp SDK, dumped API/interface, logs |
| libgodot-ios-device | arm64 device static library, dumped contract, tools and source manifest |
| libgodot-ios-simulator | arm64 simulator static library, dumped contract, tools and source manifest |
| libgodot-macos | arm64 template_debug shared library, editor, dumped contract, tools and source manifest |
| libgodot-ios-xcframeworks | zipped engine and godot-cpp XCFrameworks, embedded engine dSYMs, native input provenance and logs |
| libgodot-contract | API/binding compilation, public C ABI lifecycle/recreate and DNS shutdown evidence |

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

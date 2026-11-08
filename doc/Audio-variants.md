# Mobile audio variants

Mobile builds default to `no-record`: native audio playback remains enabled,
while microphone capture and the iOS microphone permission calls are excluded
at compile time. This differs from selecting the `Dummy` audio driver, which
also disables playback at runtime.

The engine must support the `audio_input` SCons option. Older pins fail before
building a no-record target. The host editor and macOS contract library retain
their normal audio configuration.

## Building and packaging

```sh
# Default mobile variant: playback enabled, recording excluded.
./build_libgodot.sh --target ios --release --no-record
./build_libgodot.sh --target android --release --no-record

# Explicitly include native microphone capture.
./build_libgodot.sh --target ios --release --with-recording

# Package both mobile platforms and their C++ bindings.
./build_prebuilt_release.sh
LIBGODOT_AUDIO_VARIANT=with-recording ./build_prebuilt_release.sh
```

`LIBGODOT_AUDIO_VARIANT` accepts `no-record` and `with-recording`. Mobile
targets pass `audio_input=no` or `audio_input=yes` to the engine; neither mode
disables the output driver. The public extension API remains available, but
attempting to activate audio input in a no-record build returns
`ERR_UNAVAILABLE`. Record-capable iOS session settings fall back to Playback.

Packages are written to `build/prebuilt/release/<variant>`. Engine archive
names contain `-no-record` or `-with-recording`; the XCFramework's internal
name remains `libgodot.xcframework`. C++ binding archive names are unchanged.
Use separate clean build checkouts when producing both variants: intermediate
engine and framework paths are shared, and every Simulator archive discovered
by the packager must match the selected variant.

The Maven publication version is explicit, without the automatic `SNAPSHOT`
suffix: the default coordinate is
`com.migeran.libgodot:godot:4.7.2.preeternal.2`, or
`4.7.2.preeternal.2-with-recording` for the recording-capable variant.
`GODOT_PUBLISH_VERSION` overrides the base packaging version. Use a new version
for changed binaries; do not replace previously published release assets.

## Validation

Before packaging, no-record builds scan each native library for microphone
API references and require audio output references. iOS checks cover both
device and Simulator archive imports and the final XCFramework. Archive imports
are checked separately because LLVM bitcode and debug information may describe
unused SDK APIs; the linked frameworks additionally undergo selector checks.
Android checks cover
both native ABIs and the libraries inside the final AAR/Maven ZIP. Maven ZIP
checks also validate the POM version, repository layout and absence of
`SNAPSHOT` coordinates.

```sh
python3 tools/check_no_record.py --platform ios \
  --xcframework build/libgodot/release/libgodot.xcframework \
  --manifest build/ios-no-record-audit.json

python3 tools/check_no_record.py --platform android \
  --maven-zip build/prebuilt/release/no-record/libgodot-android-no-record.zip \
  --maven-version 4.7.2.preeternal.2 \
  --manifest build/android-no-record-audit.json
```

Artifact manifests record the variant, compiled audio capabilities, source
revisions, audit files and SHA-256 inventory. No-record provenance requires a
committed engine source and matching binary audits. Verification rejects a
recording-capable or unidentified mobile input when no-record is selected.
Set `LIBGODOT_AUDIO_VARIANT=with-recording` when verifying that variant.

Binary inspection establishes API-reference checks, not audible playback.
Test music, interruption/resume and the absence of microphone prompts on real
devices. The final application should also be inspected after linking its
other dependencies.

## Consumer integration

Build defaults do not change previously published or installed binaries. A
consumer switching variants must select the corresponding release archive and
SHA-256. CocoaPods and Gradle can consume downloaded local artifacts; SwiftPM
binary targets additionally require the matching URL and checksum in
`Package.swift`. Replacing local files alone does not change a SwiftPM URL.

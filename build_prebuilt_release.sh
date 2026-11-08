#!/bin/bash

set -eux

BASE_DIR="$( cd "$(dirname "$0")" ; pwd -P )"


BUILD_DIR=$BASE_DIR/build
PREBUILT_DIR=$BUILD_DIR/prebuilt
export LIBGODOT_AUDIO_VARIANT="${LIBGODOT_AUDIO_VARIANT:-no-record}"
case "$LIBGODOT_AUDIO_VARIANT" in
    no-record) artifact_suffix="-no-record" ;;
    with-recording) artifact_suffix="-with-recording" ;;
    *) echo "Unknown audio variant: $LIBGODOT_AUDIO_VARIANT" >&2; exit 1 ;;
esac
PREBUILT_TARGET_DIR=$PREBUILT_DIR/release/$LIBGODOT_AUDIO_VARIANT
ANDROID_DIR=$BASE_DIR/godot/platform/android/java
ANDROID_LIB_BUILD_DIR=$BUILD_DIR/android/release

export SIGNING_DISABLED="true"
export OSSRH_GROUP_ID="com.migeran.libgodot"
export GODOT_VERSION_STATUS="preeternal.2"
export GODOT_PUBLISH_VERSION="${GODOT_PUBLISH_VERSION:-4.7.2.preeternal.2}"
if [[ "$LIBGODOT_AUDIO_VARIANT" == with-recording ]]; then
    export GODOT_PUBLISH_VERSION="${GODOT_PUBLISH_VERSION}-with-recording"
fi
if [[ "$GODOT_PUBLISH_VERSION" == *SNAPSHOT* ]]; then
    echo 'Release packaging requires a Maven version without SNAPSHOT.' >&2
    exit 1
fi

# Unknown SCons arguments can otherwise be ignored by an older engine.
if [[ "$LIBGODOT_AUDIO_VARIANT" == no-record ]] && \
    ! grep -q 'BoolVariable("audio_input"' "$BASE_DIR/godot/SConstruct"; then
    echo 'Pin a Godot commit with audio_input=no before starting release builds.' >&2
    exit 1
fi
if [[ -n "$(git -C "$BASE_DIR/godot" diff HEAD --name-only)" ]]; then
    echo 'Commit the engine changes and pin that commit before release packaging.' >&2
    exit 1
fi
if ! grep -q "System.getenv('GODOT_PUBLISH_VERSION')" "$BASE_DIR/godot/platform/android/java/app/config.gradle"; then
    echo 'This engine pin does not support an explicit Maven release version.' >&2
    exit 1
fi

./build_libgodot.sh --no-target --host-rebuild --host-release --update-api
./build_libgodot.sh --target ios --release --host-release
./build_libgodot.sh --target ios --simulator --release --host-release
./build_libgodot.sh --target android --release --host-release
./build_libgodot.sh --target android --release --host-release --target-arch arm32

tmp_dir=$(mktemp -d)
cd $ANDROID_DIR
export PREBUILT_REPO=$tmp_dir
./gradlew publishTemplateReleasePublicationToPrebuiltRepoRepository

cd $tmp_dir
mkdir -p $ANDROID_LIB_BUILD_DIR
rm -rf $ANDROID_LIB_BUILD_DIR/libgodot-android.zip
zip -r $ANDROID_LIB_BUILD_DIR/libgodot-android.zip *
rm -rf $tmp_dir

cd $BASE_DIR
./build_libgodot_xcframework.sh --target template_release
./build_godotcpp_xcframework.sh --target template_release

./build_godotcpp_android.sh --target template_release
BUILD_GODOT_CPP_ANDROID_DIR=$BUILD_DIR/godot-cpp-android

rm -rf $PREBUILT_TARGET_DIR
mkdir -p $PREBUILT_TARGET_DIR

cd $BUILD_DIR/libgodot/release
zip -r $PREBUILT_TARGET_DIR/libgodot${artifact_suffix}.xcframework.zip libgodot.xcframework
cp renderer-slices.json "$PREBUILT_TARGET_DIR/"

cd $BUILD_DIR/godot-cpp/release
zip -r $PREBUILT_TARGET_DIR/libgodot-cpp.xcframework.zip libgodot-cpp.xcframework

cd $BUILD_GODOT_CPP_ANDROID_DIR/release
zip -r $PREBUILT_TARGET_DIR/godot-cpp-android.zip godot-cpp-android

cp -vf "$ANDROID_LIB_BUILD_DIR/libgodot-android.zip" "$PREBUILT_TARGET_DIR/libgodot-android${artifact_suffix}.zip"
cp -vf "$BASE_DIR/godot/bin/android-template-release-native-symbols.zip" "$PREBUILT_TARGET_DIR/libgodot-android${artifact_suffix}-native-symbols.zip"

# Write provenance only after all builds and archives have completed successfully.
cd "$BASE_DIR"
if [[ "$LIBGODOT_AUDIO_VARIANT" == no-record ]]; then
    python3 tools/check_no_record.py --platform ios \
        --xcframework "$BUILD_DIR/libgodot/release/libgodot.xcframework" \
        --manifest "$PREBUILT_TARGET_DIR/ios-no-record-audit.json"
    python3 tools/check_no_record.py --platform android \
        --maven-zip "$PREBUILT_TARGET_DIR/libgodot-android${artifact_suffix}.zip" \
        --manifest "$PREBUILT_TARGET_DIR/android-no-record-audit.json"
fi
python3 tools/artifact_manifest.py "$PREBUILT_TARGET_DIR" --profile android-ios-local \
    --flags 'build_prebuilt_release.sh; host/API update; Android arm64+arm32 template_release; iOS arm64 device and available simulator slices template_release; godot-cpp template_release'
python3 tools/artifact_manifest.py "$PREBUILT_TARGET_DIR" --verify

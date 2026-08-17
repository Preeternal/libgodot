#!/bin/bash

set -eux

BASE_DIR="$( cd "$(dirname "$0")" ; pwd -P )"


BUILD_DIR=$BASE_DIR/build
PREBUILT_DIR=$BUILD_DIR/prebuilt
PREBUILT_TARGET_DIR=$PREBUILT_DIR/release
ANDROID_DIR=$BASE_DIR/godot/platform/android/java
ANDROID_LIB_BUILD_DIR=$BUILD_DIR/android/release

export SIGNING_DISABLED="true"
export OSSRH_GROUP_ID="com.migeran.libgodot"
export GODOT_VERSION_STATUS="migeran.2"

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
zip -r $PREBUILT_TARGET_DIR/libgodot.xcframework.zip libgodot.xcframework

cd $BUILD_DIR/godot-cpp/release
zip -r $PREBUILT_TARGET_DIR/libgodot-cpp.xcframework.zip libgodot-cpp.xcframework

cd $BUILD_GODOT_CPP_ANDROID_DIR/release
zip -r $PREBUILT_TARGET_DIR/godot-cpp-android.zip godot-cpp-android

cp -vf $ANDROID_LIB_BUILD_DIR/libgodot-android.zip $PREBUILT_TARGET_DIR
cp -vf $BASE_DIR/godot/bin/android-template-release-native-symbols.zip $PREBUILT_TARGET_DIR/libgodot-android-native-symbols.zip

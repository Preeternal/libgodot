#!/bin/bash

set -eux

BASE_DIR="$( cd "$(dirname "$0")" ; pwd -P )"

GODOT_DIR="$BASE_DIR/godot"
GODOT_CPP_DIR="$BASE_DIR/godot-cpp"
BUILD_DIR=$BASE_DIR/build
LIBGODOT_FRAMEWORK_DIR=$BASE_DIR/libgodot_framework

host_system="$(uname -s)"
host_arch="$(uname -m)"
target="template_debug"
build_type="debug"
config="Debug"
suffix=""
simulator=1
target_build=1

case "$host_system" in
    Darwin)
        cpus="$(sysctl -n hw.logicalcpu)"
    ;;
    *)
        echo "System $host_system is unsupported"
        exit 1
    ;;
esac


while [ "${1:-}" != "" ]
do
    case "$1" in
        --target)
            shift
            target="${1:-}"
        ;;
        --no-sim)
            simulator=0
        ;;
        --no-target)
            target_build=0
        ;;
        *)
            echo "Usage: $0 [--target <template_debug|template_dev|template_release|editor>] [--no-sim] [--no-target]"
            exit 1
        ;;
    esac
    shift
done

if [ "$target" = "template_debug" ]
then
    suffix=""
    config="Debug"
fi

if [ "$target" = "template_dev" ]
then
    suffix=".dev"
    target="template_debug"
    config="Debug"
    build_type="dev"
fi

if [ "$target" = "template_release" ]
then
    config="Release"
    build_type="release"
fi

mkdir -p $BUILD_DIR

if [ ! -f $BUILD_DIR/gdextension/gdextension_interface.h ]; then
    echo "Cannot find generated gdextension_interface.h in $BUILD_DIR/gdextension"
    echo "Run build_libgodot.sh --no-target --update-api first"
    exit 1
fi

# A static archive can contain unresolved SDL references. Require their providers
# before starting any framework build, including for locally supplied archives.
validation_dir="$(mktemp -d)"
trap 'rm -rf "$validation_dir"' EXIT
validate_ios_archive() {
    local archive="$1"
    local slice_name="$2"
    if [[ "${LIBGODOT_AUDIO_VARIANT:-no-record}" == no-record ]]; then
        python3 "$BASE_DIR/tools/check_no_record.py" --platform ios --library "$archive" \
            --manifest "$validation_dir/$slice_name-no-record-audit.json"
    fi
    nm -gU "$archive" > "$validation_dir/symbols.txt"
    python3 "$GODOT_DIR/tests/libgodot/check_library.py" \
        --platform ios --target "$target" --library-type static_library \
        --require-ios-sdl --revision "$(git -C "$GODOT_DIR" rev-parse HEAD)" \
        --library "$archive" --symbols "$validation_dir/symbols.txt" \
        --manifest "$validation_dir/manifest.json"
    nm -U "$archive" > "$validation_dir/renderer-symbols.txt"
    python3 "$BASE_DIR/tools/check_ios_renderers.py" \
        --library "$archive" --symbols "$validation_dir/renderer-symbols.txt" --slice "$slice_name" \
        --manifest "$validation_dir/renderer-manifest.json"
}
if [ "$target_build" -eq 1 ]; then
    validate_ios_archive "$GODOT_DIR/bin/libgodot.ios.$target$suffix.arm64.a" device
fi
if [ "$simulator" -eq 1 ]; then
    for simarch in arm64 x86_64; do
        archive="$GODOT_DIR/bin/libgodot.ios.$target$suffix.$simarch.simulator.a"
        if [ -f "$archive" ]; then
            validate_ios_archive "$archive" simulator
        fi
    done
fi

cp $BUILD_DIR/gdextension/gdextension_interface.h $LIBGODOT_FRAMEWORK_DIR/libgodot/gdextension_interface.h
cp $GODOT_DIR/core/extension/libgodot.h $LIBGODOT_FRAMEWORK_DIR/libgodot/libgodot.h

sed -i '' \
    -e 's|^#include "gdextension_interface.h"|#include <libgodot/gdextension_interface.h>|' \
    -e 's|^#include "core/extension/gdextension_interface.gen.h"|#include <libgodot/gdextension_interface.h>|' \
    $LIBGODOT_FRAMEWORK_DIR/libgodot/libgodot.h

if [ $target_build -eq 1 ]
then

cp -a $GODOT_DIR/bin/libgodot.ios.$target$suffix.arm64.a $LIBGODOT_FRAMEWORK_DIR/libgodot/libgodot.a

rm -rf $BUILD_DIR/libgodot.framework*
rm -rf $BUILD_DIR/ios_${target}
cd $LIBGODOT_FRAMEWORK_DIR
xcodebuild -scheme libgodot -configuration $config -destination 'generic/platform=iOS' \
    CODE_SIGNING_ALLOWED=NO ARCHS=arm64 clean build

cd $BASE_DIR
mkdir -p $BUILD_DIR/ios_${target}
mv $BUILD_DIR/libgodot.framework $BUILD_DIR/ios_${target}/
mv $BUILD_DIR/libgodot.framework.dSYM $BUILD_DIR/ios_${target}/

fi

if [ $simulator -eq 1 ]
then
    echo "Simulator build enabled"
    if [ -f $GODOT_DIR/bin/libgodot.ios.$target$suffix.arm64.simulator.a ] || [ -f $GODOT_DIR/bin/libgodot.ios.$target$suffix.x86_64.simulator.a ]
    then
        simulator_files=""
        for simarch in arm64 x86_64
        do
            if [ -f $GODOT_DIR/bin/libgodot.ios.$target$suffix.$simarch.simulator.a ]
            then
                simulator_files="$simulator_files $GODOT_DIR/bin/libgodot.ios.$target$suffix.$simarch.simulator.a"
            fi
        done
        echo "Building for Simulator"
        rm -rf $BUILD_DIR/ios_${target}_simulator
        lipo -create -output $LIBGODOT_FRAMEWORK_DIR/libgodot/libgodot.a $simulator_files
        rm -rf $BUILD_DIR/libgodot.framework*
        cd $LIBGODOT_FRAMEWORK_DIR
        simulator_archs="$(lipo -archs "$LIBGODOT_FRAMEWORK_DIR/libgodot/libgodot.a")"
        xcodebuild -scheme libgodot -configuration $config -destination 'generic/platform=iOS Simulator' \
            CODE_SIGNING_ALLOWED=NO "ARCHS=$simulator_archs" clean build

        cd $BASE_DIR
        mkdir -p $BUILD_DIR/ios_${target}_simulator
        mv $BUILD_DIR/libgodot.framework $BUILD_DIR/ios_${target}_simulator/
        mv $BUILD_DIR/libgodot.framework.dSYM $BUILD_DIR/ios_${target}_simulator/
    fi
fi

inputs=""
for d in $BUILD_DIR/ios_${target}*
do
    inputs="$inputs -framework $d/libgodot.framework"
    inputs="$inputs -debug-symbols $d/libgodot.framework.dSYM"
done

tmp_dir="$(mktemp -d)"


xcodebuild -create-xcframework \
    $inputs \
    -output "$tmp_dir/libgodot.xcframework"

if [ "$target" = "template_release" ]
then
    # Keep public symbols required by the bridge and move debugging information
    # to the dSYMs already bundled alongside the release framework slices.
    find "$tmp_dir/libgodot.xcframework" -name 'libgodot' | grep 'libgodot\.framework/libgodot$' | xargs strip -x
fi

renderer_check_args=(--manifest "$tmp_dir/renderer-slices.json")
if [ "$target_build" -eq 1 ]; then renderer_check_args+=(--require-slice device); fi
if [ "$simulator" -eq 1 ]; then renderer_check_args+=(--require-slice simulator); fi
python3 "$BASE_DIR/tools/check_ios_renderers.py" --xcframework "$tmp_dir/libgodot.xcframework" \
    "${renderer_check_args[@]}"
if [[ "${LIBGODOT_AUDIO_VARIANT:-no-record}" == no-record ]]; then
    python3 "$BASE_DIR/tools/check_no_record.py" --platform ios --xcframework "$tmp_dir/libgodot.xcframework" \
        --manifest "$tmp_dir/no-record-audit.json"
fi

BUILD_LIBGODOT_TARGET_DIR="$BUILD_DIR/libgodot/$build_type"
rm -rf $BUILD_LIBGODOT_TARGET_DIR
mkdir -p $BUILD_LIBGODOT_TARGET_DIR

cd $tmp_dir
cp -Rvf libgodot.xcframework $BUILD_LIBGODOT_TARGET_DIR
cp renderer-slices.json "$BUILD_LIBGODOT_TARGET_DIR/"
if [[ -f no-record-audit.json ]]; then cp no-record-audit.json "$BUILD_LIBGODOT_TARGET_DIR/"; fi

rm -rf $tmp_dir

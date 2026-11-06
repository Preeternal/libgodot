#!/bin/bash

set -eux

BASE_DIR="$( cd "$(dirname "$0")" ; pwd -P )"

GODOT_DIR="$BASE_DIR/godot"
GODOT_CPP_DIR="$BASE_DIR/godot-cpp"
BUILD_DIR=$BASE_DIR/build
BUILD_GODOT_CPP_DIR=$BUILD_DIR/godot-cpp-android
BUILD_GDEXTENSION_DIR=$BUILD_DIR/gdextension
CUSTOM_API_FILE=$BUILD_GDEXTENSION_DIR/godotcpp_extension_api.json

host_system="$(uname -s)"
host_arch="$(uname -m)"
target="template_debug"
target_arch_list="arm64 arm32"

while [ "${1:-}" != "" ]
do
    case "$1" in
        --target)
            shift
            target="${1:-}"
        ;;
        --target-arch-list)
            shift
            target_arch_list="${1:-}"
        ;;
        *)
            echo "Usage: $0 [--target <template_dev|template_debug|template_release|editor>] [--target-arch-list 'arch1 [arch2...]']"
            exit 1
        ;;
    esac
    shift
done

function godot_to_android_arch() {
    godot_arch="$1"
    case "$godot_arch" in
        arm64)
            echo "arm64-v8a"
            ;;
        arm32)
            echo "armeabi-v7a"
            ;;
        *)
            echo "Unsupported arch: $godot_arch"
            exit 1
    esac
}

target_build_type_dir="release"
target_template="template_release"

mkdir -p $GODOT_CPP_DIR

if [ ! -f $BUILD_GDEXTENSION_DIR/extension_api.json ]
then
    echo "Cannot find extension_api.json in $BUILD_GDEXTENSION_DIR"
    echo "Run build_libgodot.sh first"
    exit 1
fi

python3 "$BASE_DIR/tools/prepare_godotcpp_api.py" \
    "$BUILD_GDEXTENSION_DIR/extension_api.json" "$CUSTOM_API_FILE"
ndk_version="$(python3 "$BASE_DIR/tools/engine_config.py" "$GODOT_DIR")"
export SCONSFLAGS="${SCONSFLAGS:-} ndk_version=$ndk_version gdextension_dir=$BUILD_GDEXTENSION_DIR"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
prep_dir="$tmp_dir/godot-cpp-android"
mkdir -p $prep_dir

sdk_root="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [ -n "$sdk_root" ]; then
    ndk_root="$sdk_root/ndk/$ndk_version"
else
    ndk_root="${ANDROID_NDK_ROOT:?Set ANDROID_HOME, ANDROID_SDK_ROOT or ANDROID_NDK_ROOT}"
fi
case "$host_system" in
    Darwin) ndk_host=darwin-x86_64 ;;
    Linux) ndk_host=linux-x86_64 ;;
    *) echo "Unsupported Android build host: $host_system"; exit 1 ;;
esac
ndk_compiler="$ndk_root/toolchains/llvm/prebuilt/$ndk_host/bin/clang++"

cd $GODOT_CPP_DIR
for target_arch in $target_arch_list
do
    android_arch="$(godot_to_android_arch $target_arch)"

    case $target in
    template_dev)
        suffix="dev.$target_arch"
        target_build_type_dir="dev"
        target_template="template_debug"
        scons custom_api_file=$CUSTOM_API_FILE arch=$target_arch platform=android precision=single dev_build=yes debug_symbols=yes target=template_debug generate_engine_classes_bindings=no generate_bindings=yes
    ;;
    template_debug)
        suffix="$target_arch"
        target_build_type_dir="debug"
        target_template="template_debug"
        scons custom_api_file=$CUSTOM_API_FILE arch=$target_arch platform=android precision=single target=$target generate_bindings=yes
    ;;
    template_release)
        suffix="$target_arch"
        scons custom_api_file=$CUSTOM_API_FILE arch=$target_arch platform=android precision=single target=$target generate_bindings=yes
    ;;
    *)
        echo "Not supported target: $target"
        exit 1
    esac

    mkdir -p $prep_dir/$android_arch
    cp -a $GODOT_CPP_DIR/bin/libgodot-cpp.android.$target_template.$suffix.a $prep_dir/$android_arch/libgodot-cpp.a
    # The next architecture regenerates gen/include in place. Snapshot this
    # library's source/generated headers before starting that generation.
    headers_dir="$prep_dir/$android_arch/include"
    mkdir -p "$headers_dir"
    cp -a "$GODOT_CPP_DIR/include/." "$headers_dir/"
    cp -a "$GODOT_CPP_DIR/gen/include/." "$headers_dir/"
    python3 "$BASE_DIR/tools/stage_public_headers.py" "$headers_dir" \
        --engine "$GODOT_DIR" --interface "$BUILD_GDEXTENSION_DIR/gdextension_interface.h" --android
done

# Verify both snapshots after all generators have run, using their actual NDK targets.
for target_arch in $target_arch_list; do
    android_arch="$(godot_to_android_arch "$target_arch")"
    python3 "$BASE_DIR/tools/check_android_cpp_abi.py" \
        --api "$CUSTOM_API_FILE" --abi "$android_arch" \
        --headers "$prep_dir/$android_arch/include" --library "$prep_dir/$android_arch/libgodot-cpp.a" \
        --compiler "$ndk_compiler" --manifest "$prep_dir/$android_arch/abi-layout.json"
done

BUILD_GODOT_CPP_TARGET_DIR=$BUILD_GODOT_CPP_DIR/$target_build_type_dir
rm -rf $BUILD_GODOT_CPP_TARGET_DIR
mkdir -p $BUILD_GODOT_CPP_TARGET_DIR

cd $tmp_dir
cp -Rvf godot-cpp-android $BUILD_GODOT_CPP_TARGET_DIR

rm -rf $tmp_dir

#!/bin/bash

set -eux

BASE_DIR="$( cd "$(dirname "$0")" ; pwd -P )"

GODOT_DIR="$BASE_DIR/godot"
GODOT_CPP_DIR="$BASE_DIR/godot-cpp"
BUILD_DIR=$BASE_DIR/build
BUILD_GDEXTENSION_DIR=$BUILD_DIR/gdextension
CUSTOM_API_FILE=$BUILD_GDEXTENSION_DIR/godotcpp_extension_api.json
BUILD_HEADERS_DIR=$BUILD_DIR/libgodot_cpp_headers
BUILD_GODOT_CPP_DIR=$BUILD_DIR/godot-cpp
host_system="$(uname -s)"
host_arch="$(uname -m)"
target="template_debug"
target_template="template_debug"
build_type="debug"
suffix=""

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
        *)
            echo "Usage: $0 [--target <template_dev|template_debug|template_release|editor>]"
            exit 1
        ;;
    esac
    shift
done


mkdir -p $BUILD_DIR
mkdir -p $BUILD_GODOT_CPP_DIR

if [ ! -f $BUILD_GDEXTENSION_DIR/extension_api.json ]
then
    echo "Cannot find extension_api.json in $BUILD_GDEXTENSION_DIR"
    echo "Run build_libgodot.sh first"
    exit 1
fi

python3 "$BASE_DIR/tools/prepare_godotcpp_api.py" \
    "$BUILD_GDEXTENSION_DIR/extension_api.json" "$CUSTOM_API_FILE"
export SCONSFLAGS="${SCONSFLAGS:-} gdextension_dir=$BUILD_GDEXTENSION_DIR"

cd $GODOT_CPP_DIR

case $target in
template_dev)
    build_type="dev"
    suffix=".dev"
    scons custom_api_file=$CUSTOM_API_FILE arch=arm64 ios_simulator=no platform=ios dev_build=yes debug_symbols=yes target=template_debug generate_engine_classes_bindings=no generate_bindings=yes
    scons custom_api_file=$CUSTOM_API_FILE arch=universal ios_simulator=yes platform=ios dev_build=yes debug_symbols=yes target=template_debug generate_engine_classes_bindings=no generate_bindings=yes
;;
template_debug)
    build_type="debug"
    scons custom_api_file=$CUSTOM_API_FILE arch=arm64 ios_simulator=no platform=ios target=$target generate_bindings=yes
    scons custom_api_file=$CUSTOM_API_FILE arch=universal ios_simulator=yes platform=ios target=$target generate_bindings=yes
;;
template_release)
    build_type="release"
    target_template="template_release"
    scons custom_api_file=$CUSTOM_API_FILE arch=arm64 ios_simulator=no platform=ios target=$target generate_bindings=yes
    scons custom_api_file=$CUSTOM_API_FILE arch=universal ios_simulator=yes platform=ios target=$target generate_bindings=yes
;;
*)
    echo "Not supported target: $target"
    exit 1
esac

BUILD_GODOT_CPP_TARGET_DIR="$BUILD_GODOT_CPP_DIR/$build_type"
mkdir -p $BUILD_GODOT_CPP_TARGET_DIR

# Prepare headers

tmp_dir="$(mktemp -d)"
universal_dir="$tmp_dir/universal"
arm64_dir="$tmp_dir/arm64"
prep_dir="$tmp_dir/prep"
headers_dir="$prep_dir/include"
mkdir -p $universal_dir
mkdir -p $arm64_dir
mkdir -p $prep_dir
mkdir -p $headers_dir

cp -a $GODOT_CPP_DIR/include/* $headers_dir/
cp -a $GODOT_CPP_DIR/gen/include/* $headers_dir/
cp $BUILD_GDEXTENSION_DIR/gdextension_interface.h $headers_dir/

cp -a $GODOT_CPP_DIR/bin/libgodot-cpp.ios.$target_template$suffix.arm64.a $arm64_dir/libgodot-cpp.a
cp -a $GODOT_CPP_DIR/bin/libgodot-cpp.ios.$target_template$suffix.universal.simulator.a $universal_dir/libgodot-cpp.a

# cd $headers_dir

# cat > $headers_dir/module.modulemap << EOF
# module libgodot-cpp {
#     header *
#     export *
# }
# EOF

rm -rf $BUILD_DIR/libgodot-cpp.xcframework

xcodebuild -create-xcframework \
    -library $arm64_dir/libgodot-cpp.a  \
    -headers $headers_dir \
    -library $universal_dir/libgodot-cpp.a  \
    -headers $headers_dir \
    -output $prep_dir/libgodot-cpp.xcframework

cd $prep_dir
cp -Rvf libgodot-cpp.xcframework $BUILD_GODOT_CPP_TARGET_DIR

cd $BASE_DIR
rm -rf $tmp_dir

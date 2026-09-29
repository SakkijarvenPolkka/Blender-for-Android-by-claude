#!/usr/bin/env bash
# Build everything: SDK/NDK setup, Blender source, dependencies, Blender and the APK.
#
# Requirements (Ubuntu 24.04): see README.md, in short
#   sudo apt install build-essential cmake ninja-build git curl unzip zip patch \
#     python3 openjdk-17-jdk qemu-user-static autoconf automake libtool pkg-config
set -euo pipefail
SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPTS_DIR}/setup_sdk.sh"
"${SCRIPTS_DIR}/fetch_blender.sh"
"${SCRIPTS_DIR}/build_deps.sh"
"${SCRIPTS_DIR}/build_blender.sh"
"${SCRIPTS_DIR}/package_apk.sh"

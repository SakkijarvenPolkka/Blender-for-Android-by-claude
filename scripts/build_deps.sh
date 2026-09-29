#!/usr/bin/env bash
# Cross-compile Blender's dependencies for Android arm64 into ${LIBDIR}.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

[ -d "${BLENDER_SRC_DIR}" ] || die "Blender source not found, run scripts/fetch_blender.sh first"
[ -d "${ANDROID_NDK_HOME}" ] || die "Android NDK not found, run scripts/setup_sdk.sh first"

# The dependencies only need to be rebuilt when their configuration changes.
deps_hash="$(cat "${REPO_DIR}/BLENDER_VERSION" <(echo "${ANDROID_NDK_VERSION} ${ANDROID_API} ${ANDROID_ARCH_FLAGS}") \
  $(find "${REPO_DIR}/deps" -type f | sort) | sha256sum | cut -d' ' -f1)"
if [ -f "${LIBDIR}/.deps_hash" ] && [ "$(cat "${LIBDIR}/.deps_hash")" = "${deps_hash}" ] \
    && [ -x "${HOST_PYTHON_PREFIX}/bin/python3" ]; then
  log "Dependencies are up to date (${LIBDIR})"
  exit 0
fi

mkdir -p "${DEPS_BUILD_DIR}" "${DOWNLOAD_DIR}" "${LIBDIR}"

log "Configuring dependencies (build: ${DEPS_BUILD_DIR}, install: ${LIBDIR})"
cmake -G Ninja -S "${REPO_DIR}/deps" -B "${DEPS_BUILD_DIR}" \
  -DBLENDER_SOURCE_DIR="${BLENDER_SRC_DIR}" \
  -DANDROID_NDK="${ANDROID_NDK_HOME}" \
  -DANDROID_ABI="${ANDROID_ABI}" \
  -DANDROID_API="${ANDROID_API}" \
  "-DANDROID_ARCH_FLAGS=${ANDROID_ARCH_FLAGS}" \
  -DLIBDIR="${LIBDIR}" \
  -DDOWNLOAD_DIR="${DOWNLOAD_DIR}" \
  -DHOST_PYTHON_PREFIX="${HOST_PYTHON_PREFIX}" \
  -DDEPS_JOBS="${JOBS}"

log "Building dependencies"
# Each dependency builds in parallel internally, build them one at a time.
cmake --build "${DEPS_BUILD_DIR}" -j 1 -- "$@"

# Exported CMake configurations can contain absolute paths to NDK system libraries
# (e.g. `.../sysroot/usr/lib/aarch64-linux-android/31/libm.so`). Replace them by the library
# name: this keeps LIBDIR relocatable and allows linking the build tools statically.
log "Sanitizing exported CMake configurations"
find "${LIBDIR}" -name "*.cmake" -print0 | xargs -0 sed -i -E \
  's#[^;" ]*/sysroot/usr/lib/aarch64-linux-android/[0-9]+/lib([A-Za-z0-9_]+)\.(so|a)#\1#g'

echo "${deps_hash}" > "${LIBDIR}/.deps_hash"
log "Dependencies installed to ${LIBDIR}"

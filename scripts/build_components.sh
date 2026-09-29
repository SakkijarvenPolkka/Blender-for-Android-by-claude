#!/usr/bin/env bash
# Build the optional components (native code installed after the application from Blender,
# `Edit > Android Components`), see `components/CMakeLists.txt`.
#
# Needs the build of Blender they are made for (scripts/build_blender.sh). The result
# (`${COMPONENTS_OUT_DIR}`: archives & `components.json`) is published in the release of the
# application, where the application downloads it from, or installed from a file.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

build_info="${BLENDER_INSTALL_DIR}/${BLENDER_VERSION_SHORT}/datafiles/android/build_info.json"
[ -f "${BLENDER_BUILD_DIR}/lib/libblender.so" ] || die "libblender.so not found, run scripts/build_blender.sh first"
[ -f "${build_info}" ] || die "${build_info} not found, run scripts/build_blender.sh first"

HOST_PYTHON="${HOST_PYTHON:-$(ls "${HOST_PYTHON_PREFIX}"/bin/python3.[0-9]* 2>/dev/null | grep -v config | head -n 1 || true)}"
[ -x "${HOST_PYTHON}" ] || die "Host Python not found (built together with the dependencies)"

export LC_ALL=C.UTF-8
staging="${COMPONENTS_BUILD_DIR}/staging"

log "Configuring components (build: ${COMPONENTS_BUILD_DIR})"
cmake -G Ninja -S "${REPO_DIR}/components" -B "${COMPONENTS_BUILD_DIR}" \
  -DBLENDER_SOURCE_DIR="${BLENDER_SRC_DIR}" \
  -DANDROID_NDK="${ANDROID_NDK_HOME}" \
  -DANDROID_ABI="${ANDROID_ABI}" \
  -DANDROID_API="${ANDROID_API}" \
  "-DANDROID_ARCH_FLAGS=${ANDROID_ARCH_FLAGS}" \
  -DLIBDIR="${LIBDIR}" \
  -DHOST_PYTHON_PREFIX="${HOST_PYTHON_PREFIX}" \
  -DBLENDER_LIBRARY="${BLENDER_BUILD_DIR}/lib/libblender.so" \
  -DSTAGING_DIR="${staging}" \
  -DDOWNLOAD_DIR="${DOWNLOAD_DIR}" \
  -DDEPS_JOBS="${JOBS}"

log "Building components"
cmake --build "${COMPONENTS_BUILD_DIR}" -j 1

log "Packaging components to ${COMPONENTS_OUT_DIR}"
rm -rf "${COMPONENTS_OUT_DIR}"
"${HOST_PYTHON}" "${REPO_DIR}/components/package.py" \
  --staging "${staging}" --build-info "${build_info}" --output "${COMPONENTS_OUT_DIR}"

log "Done: ${COMPONENTS_OUT_DIR}"

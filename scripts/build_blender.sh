#!/usr/bin/env bash
# Cross-compile Blender for Android arm64 (`libblender.so` + data files).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

[ -f "${BLENDER_SRC_DIR}/.android_port_applied" ] || [ -n "${BLENDER_SRC_DIR_IS_DEV:-}" ] \
  || die "Blender source not prepared, run scripts/fetch_blender.sh first"
[ -d "${LIBDIR}/include" ] || die "Dependencies not found in ${LIBDIR}, run scripts/build_deps.sh first"
[ -n "${QEMU_AARCH64}" ] || die "qemu-aarch64(-static) is required to run build tools (apt install qemu-user-static)"

if [ -z "${HOST_PYTHON}" ]; then
  HOST_PYTHON="$(ls "${HOST_PYTHON_PREFIX}"/bin/python3.[0-9]* 2>/dev/null | grep -v config | head -n 1 || true)"
fi
[ -x "${HOST_PYTHON}" ] || die "Host Python not found (built together with the dependencies)"

extra_args=()
if command -v ccache >/dev/null 2>&1; then
  extra_args+=(-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache)
fi

log "Configuring Blender (build: ${BLENDER_BUILD_DIR})"
cmake -G Ninja -S "${BLENDER_SRC_DIR}" -B "${BLENDER_BUILD_DIR}" \
  -C "${REPO_DIR}/blender/android_config.cmake" \
  -DCMAKE_TOOLCHAIN_FILE="${ANDROID_NDK_HOME}/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI="${ANDROID_ABI}" \
  -DANDROID_PLATFORM="android-${ANDROID_API}" \
  -DANDROID_STL=c++_static \
  "-DCMAKE_C_FLAGS=${ANDROID_ARCH_FLAGS} -g0" \
  "-DCMAKE_CXX_FLAGS=${ANDROID_ARCH_FLAGS} -g0" \
  -DCMAKE_CROSSCOMPILING_EMULATOR="${QEMU_AARCH64}" \
  -DLIBDIR="${LIBDIR}" \
  -DPYTHON_EXECUTABLE="${HOST_PYTHON}" \
  -DCMAKE_INSTALL_PREFIX="${BLENDER_INSTALL_DIR}" \
  "${extra_args[@]}"

log "Building Blender"
cmake --build "${BLENDER_BUILD_DIR}" -j "${JOBS}" "$@"

log "Installing to ${BLENDER_INSTALL_DIR}"
rm -rf "${BLENDER_INSTALL_DIR}"
cmake --install "${BLENDER_BUILD_DIR}"

log "Done: ${BLENDER_INSTALL_DIR}/lib/libblender.so"

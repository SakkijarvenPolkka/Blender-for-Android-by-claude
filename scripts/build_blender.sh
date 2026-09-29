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
# BLENDER_TIME_LIMIT (e.g. `4h`, see `timeout`) stops the build in time to keep the compiler
# cache (CI), the next build continues from there.
if [ -n "${BLENDER_TIME_LIMIT:-}" ]; then
  status=0
  timeout --signal=INT --kill-after=5m "${BLENDER_TIME_LIMIT}" \
    cmake --build "${BLENDER_BUILD_DIR}" -j "${JOBS}" "$@" || status=$?
  if [ "${status}" -eq 124 ]; then
    log "Time limit (${BLENDER_TIME_LIMIT}) reached, build again to continue (with ccache)"
    exit 124
  fi
  [ "${status}" -eq 0 ] || die "Building Blender failed"
else
  cmake --build "${BLENDER_BUILD_DIR}" -j "${JOBS}" "$@"
fi

log "Installing to ${BLENDER_INSTALL_DIR}"
rm -rf "${BLENDER_INSTALL_DIR}"
cmake --install "${BLENDER_BUILD_DIR}"

# Identifies this build for optional components with native code (`android_components` add-on),
# which are linked against `libblender.so`: the dependencies, Blender's sources & patches.
abi="$( (cat "${LIBDIR}/.deps_hash" 2>/dev/null; echo "${BLENDER_VERSION}"; \
  cat "${REPO_DIR}/blender/patches/"*.patch "${REPO_DIR}/blender/android_config.cmake"; \
  find "${REPO_DIR}/blender/overlay" -type f -print0 | sort -z | xargs -0 cat) | sha256sum | cut -c1-16)"
mkdir -p "${BLENDER_INSTALL_DIR}/${BLENDER_VERSION_SHORT}/datafiles/android"
cat > "${BLENDER_INSTALL_DIR}/${BLENDER_VERSION_SHORT}/datafiles/android/build_info.json" <<EOF
{
  "blender_version": "${BLENDER_VERSION}",
  "port_revision": ${PORT_REVISION},
  "repository": "${BLENDER_ANDROID_REPOSITORY}",
  "release_tag": "${RELEASE_TAG}",
  "abi": "${abi}"
}
EOF

log "Done: ${BLENDER_INSTALL_DIR}/lib/libblender.so"

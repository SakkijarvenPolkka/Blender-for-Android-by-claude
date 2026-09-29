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

# The host Python is installed outside of LIBDIR, build it again when it's missing.
if [ ! -x "${HOST_PYTHON_PREFIX}/bin/python3" ]; then
  rm -f "${LIBDIR}"/.deps/external_python_host*
fi

# Some archives (e.g. FLAC) contain non-ASCII file names, which can't be extracted without a
# UTF-8 locale.
export LC_ALL=C.UTF-8

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

# Marks the dependencies that are installed (that ninja wouldn't build again), see
# `deps/cmake/options.cmake`. The next build only builds the others, also from a new build
# directory with a cached LIBDIR.
mark_installed() {
  local pending name hash_file installed=0 left=0
  pending="$(ninja -C "${DEPS_BUILD_DIR}" -n 2>/dev/null | { grep -oE "'external_[A-Za-z0-9_]+'" || true; } | tr -d "'" | sort -u)"
  mkdir -p "${LIBDIR}/.deps"
  for hash_file in "${DEPS_BUILD_DIR}"/deps_hashes/*; do
    [ -f "${hash_file}" ] || continue
    name="$(basename "${hash_file}")"
    if grep -qx "${name}" <<<"${pending}"; then
      left=$((left + 1))
    else
      cp "${hash_file}" "${LIBDIR}/.deps/${name}"
      installed=$((installed + 1))
    fi
  done
  log "Dependencies built: ${installed}, left: ${left}"
}

log "Building dependencies"
# Each dependency builds in parallel internally, build them one at a time.
# DEPS_TIME_LIMIT (e.g. `5h`, see `timeout`) stops the build in time to keep what was built (CI).
status=0
if [ -n "${DEPS_TIME_LIMIT:-}" ]; then
  timeout --signal=INT --kill-after=5m "${DEPS_TIME_LIMIT}" \
    cmake --build "${DEPS_BUILD_DIR}" -j 1 -- "$@" || status=$?
else
  cmake --build "${DEPS_BUILD_DIR}" -j 1 -- "$@" || status=$?
fi
mark_installed

# Exported CMake configurations can contain absolute paths to NDK system libraries
# (e.g. `.../sysroot/usr/lib/aarch64-linux-android/31/libm.so`). Replace them by the library
# name: this keeps LIBDIR relocatable and allows linking the build tools statically.
log "Sanitizing exported CMake configurations"
find "${LIBDIR}" -name "*.cmake" -print0 | xargs -0 sed -i -E \
  's#[^;" ]*/sysroot/usr/lib/aarch64-linux-android/[0-9]+/lib([A-Za-z0-9_]+)\.(so|a)#\1#g'

if [ "${status}" -eq 124 ]; then
  log "Time limit (${DEPS_TIME_LIMIT}) reached, run again to build the remaining dependencies"
  exit 124
elif [ "${status}" -ne 0 ]; then
  die "Building the dependencies failed"
fi

echo "${deps_hash}" > "${LIBDIR}/.deps_hash"
log "Dependencies installed to ${LIBDIR}"

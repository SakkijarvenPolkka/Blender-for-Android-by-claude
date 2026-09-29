#!/usr/bin/env bash
# Runs the Android build of Blender in background mode on the build machine:
# QEMU user-mode emulation + Android's bionic runtime (extracted from an emulator image).
#
#   tests/qemu/run_blender.sh                 # smoke test (Python, modeling, I/O, Cycles)
#   tests/qemu/run_blender.sh -- --version    # any Blender arguments
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/scripts/env.sh"

ANDROID_ROOT="${ANDROID_ROOT:-${WORK_DIR}/android_root}"
TEST_DIR="${WORK_DIR}/test"
LIB="${BLENDER_INSTALL_DIR}/lib/libblender.so"

[ -f "${LIB}" ] || die "${LIB} not found, run scripts/build_blender.sh first"
[ -n "${QEMU_AARCH64}" ] || die "qemu-aarch64(-static) is required"

python3 "${REPO_DIR}/tests/qemu/prepare_android_root.py" \
  --ndk "${ANDROID_NDK_HOME}" --download-dir "${DOWNLOAD_DIR}" "${ANDROID_ROOT}"

mkdir -p "${TEST_DIR}/home" "${TEST_DIR}/user" "${TEST_DIR}/tmp" "${TEST_DIR}/output"
RUNNER="${TEST_DIR}/blender_runner"
if [ ! -x "${RUNNER}" ] || [ "${REPO_DIR}/tests/qemu/blender_runner.c" -nt "${RUNNER}" ]; then
  "${ANDROID_TOOLCHAIN_DIR}/bin/${ANDROID_TRIPLE}${ANDROID_API}-clang" -O2 \
    -o "${RUNNER}" "${REPO_DIR}/tests/qemu/blender_runner.c" -ldl
fi

export HOME="${TEST_DIR}/home"
export TMPDIR="${TEST_DIR}/tmp"
export BLENDER_SYSTEM_RESOURCES="${BLENDER_INSTALL_DIR}/${BLENDER_VERSION_SHORT}"
export BLENDER_USER_RESOURCES="${TEST_DIR}/user"
export BLENDER_ANDROID_KEEP_STDOUT=1
export LANG=C.UTF-8

run_blender() {
  "${QEMU_AARCH64}" -L "${ANDROID_ROOT}" "${RUNNER}" "${LIB}" "$@"
}

if [ "${1:-}" = "--" ]; then
  shift
  run_blender "$@"
  exit $?
fi

log "Blender --version"
run_blender --version

log "Smoke test (background mode)"
run_blender --background --factory-startup -noaudio \
  --python "${REPO_DIR}/tests/qemu/smoke_test.py" -- "${TEST_DIR}/output" 2>&1 | tee "${TEST_DIR}/smoke_test.log"
grep -q "ALL TESTS PASSED" "${TEST_DIR}/smoke_test.log" || die "Smoke test failed"
log "Smoke test passed, output in ${TEST_DIR}/output"

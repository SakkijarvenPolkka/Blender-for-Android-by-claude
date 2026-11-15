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

# Optional components made for this build (scripts/build_components.sh) are tested too.
if python3 - "${COMPONENTS_OUT_DIR}/components.json" \
    "${BLENDER_INSTALL_DIR}/${BLENDER_VERSION_SHORT}/datafiles/android/build_info.json" <<'EOF' 2>/dev/null
import json, sys
components, build_info = (json.load(open(path)) for path in sys.argv[1:3])
sys.exit(components["abi"] != build_info["abi"])
EOF
then
  export BLENDER_ANDROID_COMPONENTS="${COMPONENTS_OUT_DIR}"
  log "Testing the optional components in ${COMPONENTS_OUT_DIR}"
fi

log "Smoke test (background mode)"
run_blender --background --factory-startup -noaudio \
  --python "${REPO_DIR}/tests/qemu/smoke_test.py" -- "${TEST_DIR}/output" 2>&1 | tee "${TEST_DIR}/smoke_test.log"
grep -q "ALL TESTS PASSED" "${TEST_DIR}/smoke_test.log" || die "Smoke test failed"
log "Smoke test passed, output in ${TEST_DIR}/output"

# GPU back-end preference: Vulkan, the only back-end of the build. Otherwise Blender tries the
# preferred back-end first and reports "Failed to load using Vulkan, using OpenGL instead" at every
# start (OpenGL: the default of desktop Blender, stored in the preferences by builds up to 24).
log "GPU back-end preference"
PREFS_DIR="${TEST_DIR}/prefs"
rm -rf "${PREFS_DIR}"
mkdir -p "${PREFS_DIR}"
GPU_BACKEND_CHECK="import bpy, sys
value = bpy.context.preferences.system.gpu_backend
print('gpu_backend preference:', repr(value), flush=True)
if value == 'VULKAN' and '--save' in sys.argv:
    bpy.ops.wm.save_userpref()
print('GPU BACKEND ' + ('OK' if value == 'VULKAN' else 'WRONG'), flush=True)"
# Factory settings (saved, to be loaded below).
( export BLENDER_USER_RESOURCES="${PREFS_DIR}"
  run_blender --background --factory-startup -noaudio --python-expr "${GPU_BACKEND_CHECK}" -- --save ) \
  > "${TEST_DIR}/gpu_backend_factory.log" 2>&1 || true
grep -q "GPU BACKEND OK" "${TEST_DIR}/gpu_backend_factory.log" \
  || { cat "${TEST_DIR}/gpu_backend_factory.log"; die "Factory settings: the GPU back-end isn't Vulkan"; }
# Saved preferences selecting OpenGL are loaded with Vulkan.
"${PYTHON:-python3}" -I "${REPO_DIR}/tests/qemu/userpref_gpu_backend.py" "${PREFS_DIR}/config/userpref.blend" 1 \
  || die "Unable to change the GPU back-end of the saved preferences"
( export BLENDER_USER_RESOURCES="${PREFS_DIR}"
  run_blender --background -noaudio --python-expr "${GPU_BACKEND_CHECK}" ) \
  > "${TEST_DIR}/gpu_backend_saved.log" 2>&1 || true
grep -q "GPU BACKEND OK" "${TEST_DIR}/gpu_backend_saved.log" && ! grep -q "matches no enum" "${TEST_DIR}/gpu_backend_saved.log" \
  || { cat "${TEST_DIR}/gpu_backend_saved.log"; die "Preferences saved with OpenGL: the GPU back-end isn't Vulkan"; }
log "GPU back-end preference: Vulkan (factory settings, preferences saved with OpenGL)"

# Python interpreter executable (`sys.executable`), packaged like in the APK.
log "Python executable (isolated mode, as used by the extensions platform)"
PYTHON_EXE="${TEST_DIR}/libblender_python.so"
"${ANDROID_TOOLCHAIN_DIR}/bin/${ANDROID_TRIPLE}${ANDROID_API}-clang" -O2 -pie -o "${PYTHON_EXE}" \
  "${REPO_DIR}/android/native/blender_python.c" -I"${LIBDIR}/include/python3.13" \
  -L"$(dirname "${LIB}")" -lblender '-Wl,-rpath,$ORIGIN'
LD_LIBRARY_PATH="$(dirname "${LIB}")" "${QEMU_AARCH64}" -L "${ANDROID_ROOT}" "${PYTHON_EXE}" -I -c \
  "import sys, ssl, numpy, requests; assert sys.executable.endswith('libblender_python.so'); \
print('python', sys.version.split()[0], ssl.OPENSSL_VERSION, 'numpy', numpy.__version__)" \
  || die "Python executable test failed"

# Cloudflare Tunnel client packaged in the APK (`scripts/build_cloudflared.sh`): it runs on bionic.
# (Only its version: a tunnel would make the build machine reachable from the internet.)
CLOUDFLARED="${CLOUDFLARED_OUT_DIR:-${WORK_DIR}/out/cloudflared}/libcloudflared.so"
if [ -f "${CLOUDFLARED}" ]; then
  log "cloudflared"
  "${QEMU_AARCH64}" -L "${ANDROID_ROOT}" "${CLOUDFLARED}" --version | tee "${TEST_DIR}/cloudflared.log"
  grep -q "cloudflared version" "${TEST_DIR}/cloudflared.log" || die "cloudflared test failed"
fi

# MCP server (`mcp_server` add-on): Blender serves in the background, the test acts as client.
log "MCP server"
MCP_PORT="${MCP_PORT:-18765}"
export BLENDER_MCP_TOKEN="test-$$-${RANDOM}"
"${QEMU_AARCH64}" -L "${ANDROID_ROOT}" "${RUNNER}" "${LIB}" --background --factory-startup -noaudio \
  --python-expr "import addon_utils; addon_utils.enable('mcp_server'); import mcp_server; \
mcp_server.serve_forever(port=${MCP_PORT})" > "${TEST_DIR}/mcp_server.log" 2>&1 &
MCP_PID=$!
trap 'kill ${MCP_PID} 2>/dev/null || true' EXIT
for _ in $(seq 1 120); do
  grep -q "MCP end-point" "${TEST_DIR}/mcp_server.log" 2>/dev/null && break
  kill -0 "${MCP_PID}" 2>/dev/null || { cat "${TEST_DIR}/mcp_server.log"; die "MCP server exited"; }
  sleep 1
done
"${PYTHON:-python3}" "${REPO_DIR}/tests/qemu/mcp_test.py" \
  "http://127.0.0.1:${MCP_PORT}/mcp" "${BLENDER_MCP_TOKEN}" "${TEST_DIR}/output" \
  || { tail -30 "${TEST_DIR}/mcp_server.log"; die "MCP test failed"; }
kill "${MCP_PID}" 2>/dev/null || true
log "All tests passed"

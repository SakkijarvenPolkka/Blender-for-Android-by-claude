# Shared build configuration for Blender for Android.
#
# Source this file from the other scripts. Every value can be overridden from
# the environment before sourcing, e.g. `WORK_DIR=/mnt/big ./scripts/build_all.sh`.

# Repository root (directory that contains this `scripts/` folder).
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Blender release that is ported. Must exist on download.blender.org/source/.
BLENDER_VERSION="${BLENDER_VERSION:-$(cat "${REPO_DIR}/BLENDER_VERSION")}"
BLENDER_VERSION_SHORT="${BLENDER_VERSION%.*}"

# Everything that is downloaded or built goes below WORK_DIR (outside the repo).
WORK_DIR="${WORK_DIR:-${REPO_DIR}/_work}"
DOWNLOAD_DIR="${DOWNLOAD_DIR:-${WORK_DIR}/downloads}"
BLENDER_SRC_DIR="${BLENDER_SRC_DIR:-${WORK_DIR}/src/blender-${BLENDER_VERSION}}"
DEPS_BUILD_DIR="${DEPS_BUILD_DIR:-${WORK_DIR}/build/deps}"
# Install prefix of the cross-compiled dependencies (Blender's LIBDIR).
LIBDIR="${LIBDIR:-${WORK_DIR}/android_arm64_libs}"
BLENDER_BUILD_DIR="${BLENDER_BUILD_DIR:-${WORK_DIR}/build/blender}"
BLENDER_INSTALL_DIR="${BLENDER_INSTALL_DIR:-${WORK_DIR}/install/blender}"

# Android toolchain.
#
# Minimum target is the Galaxy S22 series:
#   - Snapdragon 8 Gen 1 (Adreno 730) / Exynos 2200 (Xclipse 920)
#   - Cortex-X2 / A710 / A510 cores: ARMv9.0-A, so ARMv8.2-A + FP16 + DotProd is safe.
#   - Shipped with Android 12 (API 31), Vulkan 1.1+ (1.3 with current drivers).
ANDROID_ABI="${ANDROID_ABI:-arm64-v8a}"
ANDROID_API="${ANDROID_API:-31}"
ANDROID_TARGET_SDK="${ANDROID_TARGET_SDK:-35}"
ANDROID_NDK_VERSION="${ANDROID_NDK_VERSION:-r29}"
ANDROID_ARCH_FLAGS="${ANDROID_ARCH_FLAGS:--march=armv8.2-a+fp16+dotprod}"

if [ -z "${ANDROID_HOME:-}" ]; then
  ANDROID_HOME="${WORK_DIR}/android-sdk"
fi
if [ -z "${ANDROID_NDK_HOME:-}" ]; then
  ANDROID_NDK_HOME="${WORK_DIR}/android-ndk-${ANDROID_NDK_VERSION}"
fi
export ANDROID_HOME ANDROID_NDK_HOME

ANDROID_TOOLCHAIN_DIR="${ANDROID_NDK_HOME}/toolchains/llvm/prebuilt/linux-x86_64"
ANDROID_TRIPLE="aarch64-linux-android"

# Host Python used during the build (must match Blender's Python minor version),
# built together with the dependencies.
HOST_PYTHON_PREFIX="${HOST_PYTHON_PREFIX:-${WORK_DIR}/host_python}"
HOST_PYTHON="${HOST_PYTHON:-}"

# QEMU user-mode emulator used to run Blender's build-time tools
# (makesdna, makesrna, datatoc, shader_tool, msgfmt), which are cross-compiled
# as static Android executables.
QEMU_AARCH64="${QEMU_AARCH64:-$(command -v qemu-aarch64-static || command -v qemu-aarch64 || true)}"

JOBS="${JOBS:-$(nproc)}"

log() {
  printf '\033[1;34m[blender-android]\033[0m %s\n' "$*"
}

die() {
  printf '\033[1;31m[blender-android] error:\033[0m %s\n' "$*" >&2
  exit 1
}

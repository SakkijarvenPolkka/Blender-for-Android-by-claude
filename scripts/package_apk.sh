#!/usr/bin/env bash
# Package the Blender build (libblender.so + data files) into an APK.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

APK_WORK_DIR="${WORK_DIR}/apk"
OUT_DIR="${OUT_DIR:-${WORK_DIR}/out}"
LIB="${BLENDER_INSTALL_DIR}/lib/libblender.so"
DATA_DIR="${BLENDER_INSTALL_DIR}/${BLENDER_VERSION_SHORT}"

[ -f "${LIB}" ] || die "${LIB} not found, run scripts/build_blender.sh first"
[ -d "${DATA_DIR}" ] || die "${DATA_DIR} not found, run scripts/build_blender.sh first"

rm -rf "${APK_WORK_DIR}"
mkdir -p "${APK_WORK_DIR}/jniLibs/${ANDROID_ABI}" "${APK_WORK_DIR}/assets" "${OUT_DIR}"

log "Stripping libblender.so"
"${ANDROID_TOOLCHAIN_DIR}/bin/llvm-strip" --strip-unneeded \
  -o "${APK_WORK_DIR}/jniLibs/${ANDROID_ABI}/libblender.so" "${LIB}"

# Python interpreter executable (`sys.executable`), see `android/native/blender_python.c`.
log "Building the Python interpreter executable"
"${ANDROID_TOOLCHAIN_DIR}/bin/${ANDROID_TRIPLE}${ANDROID_API}-clang" -O2 -s -pie \
  -o "${APK_WORK_DIR}/jniLibs/${ANDROID_ABI}/libblender_python.so" \
  "${REPO_DIR}/android/native/blender_python.c" -I"${LIBDIR}/include/python3.13" \
  -L"${APK_WORK_DIR}/jniLibs/${ANDROID_ABI}" -lblender '-Wl,-rpath,$ORIGIN'

log "Creating data archive"
"${PYTHON:-python3}" - "${BLENDER_INSTALL_DIR}" "${BLENDER_VERSION_SHORT}" \
  "${APK_WORK_DIR}/assets/blender_data.zip" <<'EOF'
import os
import sys
import zipfile

install_dir, version_dir, archive = sys.argv[1:4]
root = os.path.join(install_dir, version_dir)
total = 0
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        # Byte-code is created on the device when needed.
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in sorted(filenames):
            path = os.path.join(dirpath, filename)
            if os.path.islink(path):
                continue
            arcname = os.path.relpath(path, install_dir)
            zf.write(path, arcname)
            total += os.path.getsize(path)
with open(archive + ".size", "w") as fh:
    fh.write(str(total))
print("{:s}: {:.1f} MiB uncompressed".format(archive, total / (1024 * 1024)))
EOF
echo "${BLENDER_VERSION}" > "${APK_WORK_DIR}/assets/blender_data.version"

log "Building APK"
GRADLE="${REPO_DIR}/android/gradlew"
[ -x "${GRADLE}" ] || GRADLE="gradle"
(
  cd "${REPO_DIR}/android"
  "${GRADLE}" --no-daemon assembleRelease \
    "-Pblender.nativeLibsDir=${APK_WORK_DIR}/jniLibs" \
    "-Pblender.assetsDir=${APK_WORK_DIR}/assets" \
    "-Pblender.sdlJavaDir=${LIBDIR}/share/sdl3-java" \
    "-Pblender.version=${BLENDER_VERSION}" \
    "-Pblender.portRevision=${PORT_REVISION:-1}"
)

apk_out="${OUT_DIR}/Blender-${BLENDER_VERSION}-android-${ANDROID_ABI}.apk"
cp "${REPO_DIR}/android/app/build/outputs/apk/release/app-release.apk" "${apk_out}"
log "APK: ${apk_out} ($(du -h "${apk_out}" | cut -f1))"

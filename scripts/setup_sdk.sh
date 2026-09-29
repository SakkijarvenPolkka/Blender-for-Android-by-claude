#!/usr/bin/env bash
# Install the Android NDK and SDK components needed by the build (when missing).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

CMDLINE_TOOLS_ZIP="commandlinetools-linux-9862592_latest.zip"

mkdir -p "${DOWNLOAD_DIR}"

if [ ! -f "${ANDROID_NDK_HOME}/build/cmake/android.toolchain.cmake" ]; then
  log "Installing Android NDK ${ANDROID_NDK_VERSION} to ${ANDROID_NDK_HOME}"
  zip="android-ndk-${ANDROID_NDK_VERSION}-linux.zip"
  curl -fL --retry 5 -o "${DOWNLOAD_DIR}/${zip}" "https://dl.google.com/android/repository/${zip}"
  mkdir -p "$(dirname "${ANDROID_NDK_HOME}")"
  unzip -q -o "${DOWNLOAD_DIR}/${zip}" -d "$(dirname "${ANDROID_NDK_HOME}")"
  if [ ! -d "${ANDROID_NDK_HOME}" ]; then
    mv "$(dirname "${ANDROID_NDK_HOME}")/android-ndk-${ANDROID_NDK_VERSION}" "${ANDROID_NDK_HOME}"
  fi
fi

SDKMANAGER="${ANDROID_HOME}/cmdline-tools/latest/bin/sdkmanager"
if [ ! -x "${SDKMANAGER}" ]; then
  log "Installing Android SDK command line tools to ${ANDROID_HOME}"
  curl -fL --retry 5 -o "${DOWNLOAD_DIR}/${CMDLINE_TOOLS_ZIP}" \
    "https://dl.google.com/android/repository/${CMDLINE_TOOLS_ZIP}"
  mkdir -p "${ANDROID_HOME}/cmdline-tools"
  rm -rf "${ANDROID_HOME}/cmdline-tools/latest" "${ANDROID_HOME}/cmdline-tools/cmdline-tools"
  unzip -q -o "${DOWNLOAD_DIR}/${CMDLINE_TOOLS_ZIP}" -d "${ANDROID_HOME}/cmdline-tools"
  mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest"
fi

log "Installing SDK platform & build tools"
yes | "${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" --licenses >/dev/null 2>&1 || true
"${SDKMANAGER}" --sdk_root="${ANDROID_HOME}" \
  "platforms;android-${ANDROID_TARGET_SDK}" "build-tools;35.0.0" "platform-tools" >/dev/null

log "Android SDK: ${ANDROID_HOME}"
log "Android NDK: ${ANDROID_NDK_HOME}"

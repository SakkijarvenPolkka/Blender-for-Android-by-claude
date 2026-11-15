#!/usr/bin/env bash
# Build cloudflared (Cloudflare Tunnel client, Apache-2.0) for Android, packaged in the APK as
# `libcloudflared.so` (applications can only execute files from their native library directory).
# The MCP server add-on runs it to give Blender a public HTTPS address, which custom connectors of
# the Claude apps require (they call the server from the internet).
#
# Needs Go (any version: the version cloudflared requires is downloaded, `GOTOOLCHAIN=auto`). The
# sources come from the Go module proxy, verified against the Go checksum database.
#
# Output: ${CLOUDFLARED_OUT_DIR}/libcloudflared.so and LICENSE (skipped when up to date).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

# Release 2026.11.0 (cloudflared tags aren't semantic versions, hence the pseudo-version).
CLOUDFLARED_VERSION="${CLOUDFLARED_VERSION:-2026.11.0}"
CLOUDFLARED_MODULE_VERSION="${CLOUDFLARED_MODULE_VERSION:-v0.0.0-20261112112111-b0297f0b24c6}"
CLOUDFLARED_OUT_DIR="${CLOUDFLARED_OUT_DIR:-${WORK_DIR}/out/cloudflared}"
CLOUDFLARED_BUILD_DIR="${WORK_DIR}/build/cloudflared"

OUT="${CLOUDFLARED_OUT_DIR}/libcloudflared.so"
STAMP="${CLOUDFLARED_OUT_DIR}/version"
if [ -f "${OUT}" ] && [ "$(cat "${STAMP}" 2>/dev/null)" = "${CLOUDFLARED_VERSION}" ]; then
  log "cloudflared ${CLOUDFLARED_VERSION}: up to date (${OUT})"
  exit 0
fi

command -v go >/dev/null || die "Go is required to build cloudflared (https://go.dev/dl/)"
CC="${ANDROID_TOOLCHAIN_DIR}/bin/${ANDROID_TRIPLE}${ANDROID_API}-clang"
[ -x "${CC}" ] || die "Android NDK not found (${ANDROID_NDK_HOME}), run scripts/setup_sdk.sh"

export GOPATH="${GOPATH:-${WORK_DIR}/go}"
export GOMODCACHE="${GOMODCACHE:-${GOPATH}/pkg/mod}"
export GOCACHE="${GOCACHE:-${WORK_DIR}/build/go-cache}"
export GOTOOLCHAIN="${GOTOOLCHAIN:-auto}"
export GOFLAGS="-mod=mod"

log "Downloading cloudflared ${CLOUDFLARED_VERSION} (${CLOUDFLARED_MODULE_VERSION})"
module_dir="$(go mod download -json "github.com/cloudflare/cloudflared@${CLOUDFLARED_MODULE_VERSION}" \
  | "${PYTHON:-python3}" -c 'import json, sys; info = json.load(sys.stdin); print(info.get("Dir") or sys.exit(info.get("Error", "download failed")))')"

rm -rf "${CLOUDFLARED_BUILD_DIR}"
mkdir -p "$(dirname "${CLOUDFLARED_BUILD_DIR}")" "${CLOUDFLARED_OUT_DIR}"
cp -R "${module_dir}" "${CLOUDFLARED_BUILD_DIR}"
chmod -R u+w "${CLOUDFLARED_BUILD_DIR}"

log "Building cloudflared for Android ${ANDROID_ABI} (API ${ANDROID_API})"
(
  cd "${CLOUDFLARED_BUILD_DIR}"
  # GOOS=android: host names are resolved by bionic (Android's DNS), there is no /etc/resolv.conf
  # for Go's own resolver. Segments aligned to 16 KB pages (Android 15+ devices).
  GOOS=android GOARCH=arm64 CGO_ENABLED=1 CC="${CC}" CXX="${CC}++" \
    go build -trimpath -buildmode=pie -o "${OUT}.tmp" \
      -ldflags "-s -w -X main.Version=${CLOUDFLARED_VERSION} -X main.BuildTime=${CLOUDFLARED_MODULE_VERSION} \
-extldflags=-Wl,-z,max-page-size=16384" \
      ./cmd/cloudflared
)
cp "${CLOUDFLARED_BUILD_DIR}/LICENSE" "${CLOUDFLARED_OUT_DIR}/LICENSE"
mv "${OUT}.tmp" "${OUT}"
echo "${CLOUDFLARED_VERSION}" > "${STAMP}"
rm -rf "${CLOUDFLARED_BUILD_DIR}"
log "cloudflared: ${OUT} ($(du -h "${OUT}" | cut -f1))"

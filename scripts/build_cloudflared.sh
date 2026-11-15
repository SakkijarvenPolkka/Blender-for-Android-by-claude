#!/usr/bin/env bash
# Build cloudflared (Cloudflare Tunnel client, Apache-2.0) for Android, packaged in the APK as
# `libcloudflared.so` (applications can only execute files from their native library directory).
# The MCP server add-on runs it to give Blender a public HTTPS address, which custom connectors of
# the Claude apps require (they call the server from the internet).
#
# Needs Go 1.21 or newer (the version cloudflared requires is downloaded, `GOTOOLCHAIN=auto`). The
# sources come from the Go module proxy, verified against the Go checksum database.
#
# Output: ${CLOUDFLARED_OUT_DIR}/libcloudflared.so, LICENSE and THIRD_PARTY_NOTICES.txt (the licenses
# of the Go modules in the executable), skipped when up to date.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

# Release 2026.11.0 (cloudflared tags aren't semantic versions, hence the pseudo-version).
CLOUDFLARED_VERSION="${CLOUDFLARED_VERSION:-2026.11.0}"
CLOUDFLARED_MODULE_VERSION="${CLOUDFLARED_MODULE_VERSION:-v0.0.0-20261112112111-b0297f0b24c6}"
CLOUDFLARED_OUT_DIR="${CLOUDFLARED_OUT_DIR:-${WORK_DIR}/out/cloudflared}"
CLOUDFLARED_BUILD_DIR="${WORK_DIR}/build/cloudflared"

OUT="${CLOUDFLARED_OUT_DIR}/libcloudflared.so"
STAMP="${CLOUDFLARED_OUT_DIR}/version"
# Built again when the version or these scripts change.
STAMP_VALUE="${CLOUDFLARED_VERSION} $(cat "${BASH_SOURCE[0]}" "${REPO_DIR}/scripts/go_module_notices.py" | sha256sum | cut -c1-16)"
if [ -f "${OUT}" ] && [ "$(cat "${STAMP}" 2>/dev/null)" = "${STAMP_VALUE}" ]; then
  log "cloudflared ${CLOUDFLARED_VERSION}: up to date (${OUT})"
  exit 0
fi

command -v go >/dev/null || die "Go 1.21 or newer is required to build cloudflared (https://go.dev/dl/)"
# Go 1.21 can download the version cloudflared requires.
go_minor="$(go env GOVERSION | sed -n 's/^go1\.\([0-9]*\).*/\1/p')"
[ "${go_minor:-0}" -ge 21 ] || die "Go 1.21 or newer is required to build cloudflared (found $(go env GOVERSION))"
CC="${ANDROID_TOOLCHAIN_DIR}/bin/${ANDROID_TRIPLE}${ANDROID_API}-clang"
[ -x "${CC}" ] || die "Android NDK not found (${ANDROID_NDK_HOME}), run scripts/setup_sdk.sh"

export GOPATH="${GOPATH:-${WORK_DIR}/go}"
export GOMODCACHE="${GOMODCACHE:-${GOPATH}/pkg/mod}"
export GOCACHE="${GOCACHE:-${WORK_DIR}/build/go-cache}"
export GOTOOLCHAIN="${GOTOOLCHAIN:-auto}"
# Not in a workspace of the user's; a writable module cache (WORK_DIR can be deleted).
export GOWORK=off
export GOFLAGS="${GOFLAGS:+${GOFLAGS} }-mod=mod -modcacherw"

log "Downloading cloudflared ${CLOUDFLARED_VERSION} (${CLOUDFLARED_MODULE_VERSION})"
module_dir="$(go mod download -json "github.com/cloudflare/cloudflared@${CLOUDFLARED_MODULE_VERSION}" \
  | "${PYTHON:-python3}" -c 'import json, sys; info = json.load(sys.stdin); print(info.get("Dir") or sys.exit(info.get("Error", "download failed")))')"

rm -rf "${CLOUDFLARED_BUILD_DIR}"
mkdir -p "$(dirname "${CLOUDFLARED_BUILD_DIR}")" "${CLOUDFLARED_OUT_DIR}"
cp -R "${module_dir}" "${CLOUDFLARED_BUILD_DIR}"
chmod -R u+w "${CLOUDFLARED_BUILD_DIR}"

# Go's own DNS client (SRV & TXT lookups: Cloudflare's edge servers, feature flags) reads the name
# servers from /etc/resolv.conf, which Android doesn't have: it would ask 127.0.0.1:53 and fail,
# leaving only cloudflared's DNS-over-TLS fallback (TCP 853, blocked by some networks). Host names
# are resolved by Android (cgo).
cat > "${CLOUDFLARED_BUILD_DIR}/cmd/cloudflared/android_dns.go" <<'GO'
// Added by Blender for Android (scripts/build_cloudflared.sh).

//go:build android

package main

import (
	_ "unsafe" // go:linkname
)

// Name servers of Go's DNS client when there is no /etc/resolv.conf (see Go's net/dnsconfig.go,
// accessible by go:linkname).
//
//go:linkname defaultNS net.defaultNS
var defaultNS []string

func init() {
	defaultNS = []string{"1.1.1.1:53", "8.8.8.8:53"}
}
GO

log "Building cloudflared for Android ${ANDROID_ABI} (API ${ANDROID_API})"
(
  cd "${CLOUDFLARED_BUILD_DIR}"
  # GOOS=android: host names are resolved by bionic (Android's DNS), there is no /etc/resolv.conf
  # for Go's own resolver. Segments aligned to 16 KB pages (Android 15+ devices).
  # `BuiltForPackageManager`: no automatic updates (the executable is updated with the APK).
  GOOS=android GOARCH=arm64 CGO_ENABLED=1 CC="${CC}" CXX="${CC}++" \
    go build -trimpath -buildmode=pie -o "${OUT}.tmp" \
      -ldflags "-s -w -X main.Version=${CLOUDFLARED_VERSION} -X main.BuildTime=${CLOUDFLARED_MODULE_VERSION} \
-X github.com/cloudflare/cloudflared/cmd/cloudflared/updater.BuiltForPackageManager=blender-android \
-extldflags=-Wl,-z,max-page-size=16384" \
      ./cmd/cloudflared

  # An executable Android can run: its dynamic linker, Android's libraries only, no text
  # relocations, segments aligned to 16 KB pages (otherwise it fails on such devices).
  log "Checking the executable"
  "${ANDROID_TOOLCHAIN_DIR}/bin/llvm-readelf" -lWd "${OUT}.tmp" | "${PYTHON:-python3}" -c '
import re, sys
text = sys.stdin.read()
errors = []
if "[Requesting program interpreter: /system/bin/linker64]" not in text:
    errors.append("the interpreter is not /system/bin/linker64")
aligns = [int(m, 16) for m in re.findall(r"^\s*LOAD\s.*\s(0x[0-9a-f]+)\s*$", text, re.M)]
if not aligns or min(aligns) < 0x4000:
    errors.append("LOAD segments not aligned to 16 KB: " + ", ".join(hex(a) for a in aligns))
needed = set(re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", text))
if not needed <= {"libc.so", "libdl.so", "libm.so", "liblog.so"}:
    errors.append("unexpected libraries: " + ", ".join(sorted(needed)))
if re.search(r"\(TEXTREL\)|\bTEXTREL\b", text):
    errors.append("text relocations")
if errors:
    sys.exit("libcloudflared.so: " + "; ".join(errors))
print("libcloudflared.so: 16 KB aligned, needs " + ", ".join(sorted(needed)))
'

  # Licenses of the modules (and of Go's standard library) built into the executable.
  log "Collecting the licenses of the Go modules"
  go version -m "${OUT}.tmp" | "${PYTHON:-python3}" "${REPO_DIR}/scripts/go_module_notices.py" \
    --module-cache "${GOMODCACHE}" --goroot "$(go env GOROOT)" \
    --title "cloudflared ${CLOUDFLARED_VERSION} (Cloudflare Tunnel client)" \
    > "${CLOUDFLARED_OUT_DIR}/THIRD_PARTY_NOTICES.txt"
)
cp "${CLOUDFLARED_BUILD_DIR}/LICENSE" "${CLOUDFLARED_OUT_DIR}/LICENSE"
mv "${OUT}.tmp" "${OUT}"
echo "${STAMP_VALUE}" > "${STAMP}"
rm -rf "${CLOUDFLARED_BUILD_DIR}"
log "cloudflared: ${OUT} ($(du -h "${OUT}" | cut -f1))"

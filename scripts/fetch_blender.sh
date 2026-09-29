#!/usr/bin/env bash
# Download the Blender source release, verify it and apply the Android port on top.
#
#   - blender/overlay/  : new files, copied into the source tree.
#   - blender/patches/  : changes to existing files, applied in order.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

# SHA-256 of the source archives supported by the patches.
declare -A BLENDER_SHA256=(
  ["5.2.2"]="56a3b1ec97479ff24dce65d2f09f8a1895005cece279b701fe4fcf74bce3f77e"
)

archive="blender-${BLENDER_VERSION}.tar.xz"
url="https://download.blender.org/source/${archive}"
expected_sha256="${BLENDER_SHA256[${BLENDER_VERSION}]:-}"
[ -n "${expected_sha256}" ] || die "No checksum known for Blender ${BLENDER_VERSION}"

mkdir -p "${DOWNLOAD_DIR}" "$(dirname "${BLENDER_SRC_DIR}")"

if [ ! -f "${DOWNLOAD_DIR}/${archive}" ]; then
  log "Downloading ${url}"
  curl -fL --retry 5 --retry-all-errors -o "${DOWNLOAD_DIR}/${archive}.part" "${url}"
  mv "${DOWNLOAD_DIR}/${archive}.part" "${DOWNLOAD_DIR}/${archive}"
fi

log "Verifying ${archive}"
echo "${expected_sha256}  ${DOWNLOAD_DIR}/${archive}" | sha256sum -c - >/dev/null \
  || die "Checksum mismatch for ${archive}"

if [ -f "${BLENDER_SRC_DIR}/.android_port_applied" ]; then
  log "Blender source already prepared: ${BLENDER_SRC_DIR}"
  exit 0
fi

rm -rf "${BLENDER_SRC_DIR}"
log "Extracting to ${BLENDER_SRC_DIR}"
mkdir -p "${BLENDER_SRC_DIR}"
tar -xf "${DOWNLOAD_DIR}/${archive}" -C "${BLENDER_SRC_DIR}" --strip-components=1

if [ -n "${BLENDER_SRC_GIT:-}" ]; then
  # For development: track the pristine release so `scripts/update_patches.sh` can export changes.
  log "Creating git repository of the pristine source"
  git -C "${BLENDER_SRC_DIR}" init -q
  git -C "${BLENDER_SRC_DIR}" add -A
  git -C "${BLENDER_SRC_DIR}" -c user.name=blender-android -c user.email=blender-android@localhost \
    commit -q -m "Blender ${BLENDER_VERSION}"
fi

log "Copying new files"
cp -a "${REPO_DIR}/blender/overlay/." "${BLENDER_SRC_DIR}/"

for patch_file in "${REPO_DIR}"/blender/patches/*.patch; do
  [ -e "${patch_file}" ] || continue
  log "Applying $(basename "${patch_file}")"
  patch -d "${BLENDER_SRC_DIR}" -p1 --forward --no-backup-if-mismatch < "${patch_file}"
done

touch "${BLENDER_SRC_DIR}/.android_port_applied"
log "Blender ${BLENDER_VERSION} source ready: ${BLENDER_SRC_DIR}"

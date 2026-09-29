#!/usr/bin/env bash
# Developer helper: store the changes made in the Blender source tree in this repository.
#
# The source tree must be a git repository whose HEAD is the pristine release
# (`BLENDER_SRC_GIT=1 scripts/fetch_blender.sh` creates it this way):
#   - modified files -> blender/patches/0001-android-port.patch
#   - new files      -> blender/overlay/
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

git -C "${BLENDER_SRC_DIR}" rev-parse --git-dir >/dev/null 2>&1 \
  || die "${BLENDER_SRC_DIR} is not a git repository"

patch_file="${REPO_DIR}/blender/patches/0001-android-port.patch"
mkdir -p "$(dirname "${patch_file}")"
git -C "${BLENDER_SRC_DIR}" diff --no-color --diff-filter=M HEAD > "${patch_file}"
log "Wrote ${patch_file} ($(grep -c '^diff --git' "${patch_file}") files)"

rm -rf "${REPO_DIR}/blender/overlay"
mkdir -p "${REPO_DIR}/blender/overlay"
git -C "${BLENDER_SRC_DIR}" ls-files --others --exclude-standard \
    -x '__pycache__' -x '*.pyc' | while read -r file; do
  case "${file}" in
    .android_port_applied) continue ;;
  esac
  mkdir -p "${REPO_DIR}/blender/overlay/$(dirname "${file}")"
  cp -a "${BLENDER_SRC_DIR}/${file}" "${REPO_DIR}/blender/overlay/${file}"
  log "New file: ${file}"
done

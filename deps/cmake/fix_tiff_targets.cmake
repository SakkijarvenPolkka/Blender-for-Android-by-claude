# SPDX-License-Identifier: GPL-2.0-or-later
#
# libtiff's exported targets link to `Deflate::Deflate` & `CMath::CMath` but its config file
# doesn't import these dependencies ("TODO: import dependencies"), consumers (OpenImageIO,
# Blender) fail to generate when the targets are not defined. Replace them by the libraries.
#
#   cmake -DTARGETS_FILE=<prefix>/lib/cmake/tiff/TiffTargets.cmake -P fix_tiff_targets.cmake

file(READ "${TARGETS_FILE}" _content)
string(REPLACE "Deflate::Deflate" "\${_IMPORT_PREFIX}/lib/libdeflate.a" _content "${_content}")
string(REPLACE "CMath::CMath" "m" _content "${_content}")
file(WRITE "${TARGETS_FILE}" "${_content}")

# SPDX-License-Identifier: GPL-2.0-or-later
#
# Build USD's Python modules only (`python_modules`), with the headers of all libraries (copied to
# the build directory by the `<library>_headerfiles` targets, which the modules don't depend on).
#
#   cmake -DBINARY_DIR=<usd build> -DJOBS=<n> -P build_python_modules.cmake

file(STRINGS ${BINARY_DIR}/CMakeCache.txt _make_program REGEX "^CMAKE_MAKE_PROGRAM:")
string(REGEX REPLACE "^[^=]*=" "" _make_program "${_make_program}")

execute_process(
  COMMAND ${_make_program} -C ${BINARY_DIR} -t targets all
  OUTPUT_VARIABLE _targets
  COMMAND_ERROR_IS_FATAL ANY
)
string(REGEX MATCHALL "(^|\n)[A-Za-z0-9_]+_headerfiles:" _headers "${_targets}")
string(REGEX REPLACE "[\n:]" "" _headers "${_headers}")

execute_process(
  COMMAND ${CMAKE_COMMAND} --build ${BINARY_DIR} -j ${JOBS} --target ${_headers} python_modules
  COMMAND_ERROR_IS_FATAL ANY
)

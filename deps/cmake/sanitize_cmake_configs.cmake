# SPDX-License-Identifier: GPL-2.0-or-later
#
# Exported CMake configurations of the installed dependencies can contain absolute paths to NDK
# system libraries (e.g. `.../sysroot/usr/lib/aarch64-linux-android/31/libm.so`): replace them by
# the library name. This keeps LIBDIR relocatable and allows linking executables statically (the
# build tools run with QEMU), which can't link `libm.so`.
#
#   cmake -DDIR=<LIBDIR> -P sanitize_cmake_configs.cmake
#
# Also done by `scripts/build_deps.sh` once all dependencies are built.

if(NOT DIR OR NOT IS_DIRECTORY "${DIR}")
  message(FATAL_ERROR "DIR must be the install directory of the dependencies")
endif()

file(GLOB_RECURSE _files LIST_DIRECTORIES false "${DIR}/*.cmake")
set(_count 0)
foreach(_file IN LISTS _files)
  file(READ "${_file}" _content)
  # The path only (e.g. inside `$<LINK_ONLY:...>`).
  string(REGEX REPLACE
    "/[^;\" <>]*/sysroot/usr/lib/aarch64-linux-android/[0-9]+/lib([A-Za-z0-9_]+)\\.(so|a)" "\\1"
    _sanitized "${_content}")
  # Repair what an earlier version of this replacement did to generator expressions:
  # `$<LINK_ONLY:.../libm.so>` became `m>` (never valid as a list element). Repeated: neighbours
  # share their `;`.
  set(_previous "")
  while(NOT _previous STREQUAL _sanitized)
    set(_previous "${_sanitized}")
    string(REGEX REPLACE "([;\"])([A-Za-z0-9_]+)>([;\"])" "\\1$<LINK_ONLY:\\2>\\3" _sanitized "${_sanitized}")
  endwhile()
  if(NOT _sanitized STREQUAL _content)
    file(WRITE "${_file}" "${_sanitized}")
    math(EXPR _count "${_count} + 1")
  endif()
endforeach()
message(STATUS "Sanitized ${_count} exported CMake configuration(s) in ${DIR}")

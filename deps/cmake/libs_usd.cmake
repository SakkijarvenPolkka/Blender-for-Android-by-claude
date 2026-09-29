# SPDX-License-Identifier: GPL-2.0-or-later
#
# Universal Scene Description, as a static monolithic library (`usd_m`) linked into
# `libblender.so` with all its members (USD registers types & plug-ins from static initializers).
#
# Blender uses USD's Python support (hooks, `pxr` wrappers) through the Python it embeds: the
# libraries are built with Python support but without Python modules (each would contain a
# copy of the static library), see `deps/patches/usd_android.diff`. The Python modules (`pxr`)
# are an optional component installed after the application (`components/CMakeLists.txt`).

include(${CMAKE_CURRENT_LIST_DIR}/usd_options.cmake)

add_cmake_dep(usd USD
  DEPENDS
    external_tbb external_opensubdiv external_materialx external_imath external_python
    external_python_host
  PATCHES ${USD_PATCHES}
  CMAKE_ARGS ${USD_CMAKE_ARGS}
)

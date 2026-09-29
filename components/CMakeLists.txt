# SPDX-License-Identifier: GPL-2.0-or-later
#
# Optional components of Blender for Android: native code that isn't part of the application
# (APK), built after it and installed from Blender (`android_components` add-on), see
# `scripts/build_components.sh`.
#
# - usd-python: USD's Python modules (`from pxr import Usd`). Built from the same sources and
#   settings as USD in `libblender.so` (`deps/cmake/usd_options.cmake`) and linked against it:
#   the modules use the USD, TBB, Python and C++ runtime in `libblender.so`
#   (`source/creator/symbols_android.map`), which is why they only work with the build of the
#   application they were made for.
#
# Usage:
#   cmake -G Ninja -S components -B <build> -DBLENDER_SOURCE_DIR=<blender> -DANDROID_NDK=<ndk> \
#     -DLIBDIR=<deps> -DBLENDER_LIBRARY=<build>/lib/libblender.so -DSTAGING_DIR=<dir>
#   cmake --build <build>

cmake_minimum_required(VERSION 3.21)
project(blender_android_components NONE)

include(ExternalProject)

set(BLENDER_SOURCE_DIR "" CACHE PATH "Blender source tree")
set(ANDROID_NDK "" CACHE PATH "Android NDK")
set(ANDROID_ABI "arm64-v8a" CACHE STRING "Android ABI")
set(ANDROID_API "31" CACHE STRING "Minimum Android API level")
set(ANDROID_ARCH_FLAGS "-march=armv8.2-a+fp16+dotprod" CACHE STRING "CPU flags")
set(LIBDIR "" CACHE PATH "Install prefix of the dependencies (scripts/build_deps.sh)")
set(HOST_PYTHON_PREFIX "" CACHE PATH "Host Python of the dependencies build")
set(BLENDER_LIBRARY "" CACHE FILEPATH "libblender.so the components are made for")
set(STAGING_DIR "${CMAKE_BINARY_DIR}/staging" CACHE PATH "Files of each component (<dir>/<id>)")
set(DOWNLOAD_DIR "${CMAKE_BINARY_DIR}/downloads" CACHE PATH "Source archive cache")
cmake_host_system_information(RESULT _nproc QUERY NUMBER_OF_LOGICAL_CORES)
set(DEPS_JOBS ${_nproc} CACHE STRING "Parallel jobs")

if(NOT EXISTS "${BLENDER_LIBRARY}")
  message(FATAL_ERROR "BLENDER_LIBRARY must point to libblender.so (got \"${BLENDER_LIBRARY}\")")
endif()

include(${BLENDER_SOURCE_DIR}/build_files/build_environment/cmake/versions.cmake)
set(HOST_PYTHON_EXECUTABLE ${HOST_PYTHON_PREFIX}/bin/python${PYTHON_SHORT_VERSION})
include(${CMAKE_CURRENT_SOURCE_DIR}/../deps/cmake/options.cmake)
include(${CMAKE_CURRENT_SOURCE_DIR}/../deps/cmake/usd_options.cmake)

# ---------------------------------------------------------------------------
# usd-python

# `usd_m`, the monolithic USD library the modules link against, is `libblender.so` (see
# `PXR_MONOLITHIC_IMPORT` in USD's `cmake/macros/Public.cmake`). The headers are the ones of
# the USD build in LIBDIR (same sources & settings) and the private ones of the sources.
set(USD_PYTHON_PREFIX ${CMAKE_BINARY_DIR}/usd_python)
set(USD_MONOLITHIC_IMPORT ${CMAKE_BINARY_DIR}/usd_monolithic_import.cmake)
file(WRITE ${USD_MONOLITHIC_IMPORT}
  "add_library(usd_m SHARED IMPORTED)\n"
  "set_target_properties(usd_m PROPERTIES\n"
  "  IMPORTED_LOCATION \"${BLENDER_LIBRARY}\"\n"
  "  IMPORTED_SONAME libblender.so\n"
  "  INTERFACE_INCLUDE_DIRECTORIES \"${LIBDIR}/include;${LIBDIR}/include/python${PYTHON_SHORT_VERSION};"
  "${USD_PYTHON_PREFIX}/src/external_usd_python\"\n"
  "  INTERFACE_COMPILE_DEFINITIONS PXR_BOOST_PYTHON_NO_PY_SIGNATURES\n"
  ")\n"
)

dep_download_args(USD _dl)
set(_patch_command)
foreach(_patch ${USD_PATCHES})
  list(APPEND _patch_command COMMAND patch -p1 -N -i ${_patch})
endforeach()
list(REMOVE_AT _patch_command 0)

set(USD_PYTHON_STAGING ${STAGING_DIR}/usd-python)
# Description of the component (`component.json`, the build's ABI is added when packaging).
file(WRITE ${CMAKE_BINARY_DIR}/usd-python.json
  "{\n"
  "  \"id\": \"usd-python\",\n"
  "  \"name\": \"USD Python Modules\",\n"
  "  \"description\": \"Python API of Universal Scene Description (from pxr import Usd, UsdGeom, Sdf...)\",\n"
  "  \"version\": \"${USD_VERSION}\"\n"
  "}\n"
)

ExternalProject_Add(external_usd_python
  ${_dl}
  PREFIX ${USD_PYTHON_PREFIX}
  PATCH_COMMAND ${_patch_command}
  CMAKE_GENERATOR Ninja
  CMAKE_ARGS
    ${DEFAULT_CMAKE_FLAGS}
    ${USD_CMAKE_ARGS}
    -DBUILD_SHARED_LIBS=ON
    -DPXR_BUILD_PYTHON_MODULES=ON
    -DPXR_MONOLITHIC_IMPORT=${USD_MONOLITHIC_IMPORT}
    # The C++ runtime is the one in `libblender.so`: a single copy of the RTTI & exception
    # support (types are compared by address on Android) shared with USD.
    "-DCMAKE_SHARED_LINKER_FLAGS=-nostdlib++ -Wl,--no-undefined -Wl,--build-id=sha1"
  # Only the Python modules, the libraries are in `libblender.so`.
  BUILD_COMMAND
    ${CMAKE_COMMAND} -DBINARY_DIR=<BINARY_DIR> -DJOBS=${DEPS_JOBS}
      -P ${CMAKE_CURRENT_SOURCE_DIR}/build_python_modules.cmake
  # Linked again when libblender.so changed.
  BUILD_ALWAYS ON
  # The files USD would install below `lib/python/pxr`.
  INSTALL_COMMAND
    ${CMAKE_COMMAND} -E rm -rf ${USD_PYTHON_STAGING}
    COMMAND ${HOST_PYTHON_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/install_python_files.py
      --build-dir <BINARY_DIR> --prefix lib/python/pxr --exclude testenv
      --output ${USD_PYTHON_STAGING}/site-packages/pxr
      --strip ${ANDROID_TOOLCHAIN_DIR}/bin/llvm-strip
      --append ${CMAKE_CURRENT_SOURCE_DIR}/usd_python_init.py=__init__.py
    COMMAND ${CMAKE_COMMAND} -E copy ${CMAKE_BINARY_DIR}/usd-python.json
      ${USD_PYTHON_STAGING}/component.json
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

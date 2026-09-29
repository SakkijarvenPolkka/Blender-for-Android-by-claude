# SPDX-License-Identifier: GPL-2.0-or-later
#
# Cross-compiles Blender's library dependencies for Android (arm64-v8a).
#
# Library versions, download URLs and checksums are taken from the Blender
# source tree (`build_files/build_environment/cmake/versions.cmake`) so that the
# Android build uses exactly the same libraries as official Blender releases.
#
# Usage (see `scripts/build_deps.sh`):
#   cmake -G Ninja -S deps -B <build> \
#     -DBLENDER_SOURCE_DIR=<blender> -DANDROID_NDK=<ndk> -DLIBDIR=<install>
#   cmake --build <build>

cmake_minimum_required(VERSION 3.21)
project(blender_android_deps NONE)

include(ExternalProject)

set(BLENDER_SOURCE_DIR "" CACHE PATH "Blender source tree")
set(ANDROID_NDK "" CACHE PATH "Android NDK")
set(ANDROID_ABI "arm64-v8a" CACHE STRING "Android ABI")
set(ANDROID_API "31" CACHE STRING "Minimum Android API level")
set(ANDROID_ARCH_FLAGS "-march=armv8.2-a+fp16+dotprod" CACHE STRING "CPU flags")
set(LIBDIR "${CMAKE_BINARY_DIR}/install" CACHE PATH "Install prefix of the libraries")
set(DOWNLOAD_DIR "${CMAKE_BINARY_DIR}/downloads" CACHE PATH "Source archive cache")
cmake_host_system_information(RESULT _nproc QUERY NUMBER_OF_LOGICAL_CORES)
set(DEPS_JOBS ${_nproc} CACHE STRING "Parallel jobs per dependency")

if(NOT ANDROID_ABI STREQUAL "arm64-v8a")
  message(FATAL_ERROR "Only arm64-v8a is supported")
endif()

include(${BLENDER_SOURCE_DIR}/build_files/build_environment/cmake/versions.cmake)
include(cmake/options.cmake)
# Python first: provides HOST_PYTHON_EXECUTABLE used by other projects.
include(cmake/libs_python.cmake)
include(cmake/libs_core.cmake)
include(cmake/libs_gpu.cmake)
include(cmake/libs_python_packages.cmake)

add_dependencies(external_shaderc external_python_host)

# Write a summary for the Blender build.
file(WRITE ${CMAKE_BINARY_DIR}/deps_info.cmake
  "set(BLENDER_ANDROID_LIBDIR \"${LIBDIR}\")\n"
  "set(BLENDER_ANDROID_HOST_PYTHON \"${HOST_PYTHON_EXECUTABLE}\")\n"
)

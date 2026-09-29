# SPDX-License-Identifier: GPL-2.0-or-later
#
# Common settings for cross-compiling Blender's dependencies for Android.

if(NOT ANDROID_NDK OR NOT EXISTS "${ANDROID_NDK}/build/cmake/android.toolchain.cmake")
  message(FATAL_ERROR "ANDROID_NDK must point to an Android NDK (got \"${ANDROID_NDK}\")")
endif()
if(NOT BLENDER_SOURCE_DIR OR NOT EXISTS "${BLENDER_SOURCE_DIR}/build_files/build_environment/cmake/versions.cmake")
  message(FATAL_ERROR "BLENDER_SOURCE_DIR must point to the Blender source tree")
endif()

set(ANDROID_TOOLCHAIN_FILE "${ANDROID_NDK}/build/cmake/android.toolchain.cmake")
set(ANDROID_TOOLCHAIN_DIR "${ANDROID_NDK}/toolchains/llvm/prebuilt/linux-x86_64")
set(ANDROID_TRIPLE "aarch64-linux-android")

# `-g0` overrides the `-g` that the NDK toolchain always adds, debug info of all
# dependencies would otherwise take many gigabytes.
set(DEPS_OPT_FLAGS "-O2 -g0 ${ANDROID_ARCH_FLAGS}")
set(DEPS_C_FLAGS "${DEPS_OPT_FLAGS} -fPIC")
set(DEPS_CXX_FLAGS "${DEPS_OPT_FLAGS} -fPIC")
separate_arguments(DEPS_C_FLAGS_LIST UNIX_COMMAND "${DEPS_C_FLAGS}")

set(DEFAULT_CMAKE_FLAGS
  -DCMAKE_TOOLCHAIN_FILE=${ANDROID_TOOLCHAIN_FILE}
  -DANDROID_ABI=${ANDROID_ABI}
  -DANDROID_PLATFORM=android-${ANDROID_API}
  -DANDROID_STL=c++_static
  -DCMAKE_BUILD_TYPE=Release
  -DCMAKE_INSTALL_PREFIX=${LIBDIR}
  -DCMAKE_INSTALL_LIBDIR=lib
  -DCMAKE_PREFIX_PATH=${LIBDIR}
  -DCMAKE_FIND_ROOT_PATH=${LIBDIR}
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON
  -DBUILD_SHARED_LIBS=OFF
  -DBUILD_TESTING=OFF
  "-DCMAKE_C_FLAGS=${DEPS_C_FLAGS}"
  "-DCMAKE_CXX_FLAGS=${DEPS_CXX_FLAGS}"
  -DCMAKE_CXX_STANDARD=17
  -DCMAKE_POLICY_DEFAULT_CMP0074=NEW
  -DCMAKE_POLICY_DEFAULT_CMP0077=NEW
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
  -DCMAKE_FIND_PACKAGE_NO_PACKAGE_REGISTRY=ON
  -Wno-dev
)

# Environment for autotools / Makefile based projects.
set(ANDROID_CC "${ANDROID_TOOLCHAIN_DIR}/bin/${ANDROID_TRIPLE}${ANDROID_API}-clang")
set(ANDROID_CXX "${ANDROID_TOOLCHAIN_DIR}/bin/${ANDROID_TRIPLE}${ANDROID_API}-clang++")
set(AUTOTOOLS_CFLAGS "${DEPS_C_FLAGS} -I${LIBDIR}/include")
set(AUTOTOOLS_LDFLAGS "-L${LIBDIR}/lib -Wl,--build-id=sha1 -Wl,-z,max-page-size=16384")
set(AUTOTOOLS_ENV
  ${CMAKE_COMMAND} -E env
    CC=${ANDROID_CC}
    CXX=${ANDROID_CXX}
    AR=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ar
    AS=${ANDROID_CC}
    LD=${ANDROID_TOOLCHAIN_DIR}/bin/ld.lld
    NM=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-nm
    RANLIB=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ranlib
    STRIP=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-strip
    READELF=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-readelf
    OBJDUMP=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-objdump
    "CFLAGS=${AUTOTOOLS_CFLAGS}"
    "CXXFLAGS=${AUTOTOOLS_CFLAGS}"
    "CPPFLAGS=-I${LIBDIR}/include"
    "LDFLAGS=${AUTOTOOLS_LDFLAGS}"
    PKG_CONFIG_LIBDIR=${LIBDIR}/lib/pkgconfig:${LIBDIR}/share/pkgconfig
    PKG_CONFIG_PATH=
)
set(AUTOTOOLS_HOST_ARGS
  --host=${ANDROID_TRIPLE}
  --build=x86_64-pc-linux-gnu
  --prefix=${LIBDIR}
  --libdir=${LIBDIR}/lib
  --enable-static
  --disable-shared
  --with-pic
)

set(MAKE_CMD make -j${DEPS_JOBS})

# All dependencies use the version, URL and checksum that Blender itself uses
# (`build_files/build_environment/cmake/versions.cmake`).
#
# Archives listed in `<DOWNLOAD_DIR>/unverified.txt` were created from a git
# checkout by `scripts/prefetch_github_archives.py` (for networks that block
# GitHub archive downloads), their checksum can't match and is not checked.
set(DEPS_UNVERIFIED_FILES)
if(EXISTS ${DOWNLOAD_DIR}/unverified.txt)
  file(STRINGS ${DOWNLOAD_DIR}/unverified.txt DEPS_UNVERIFIED_FILES)
endif()

# Blender's mirror of the dependency sources (same files and checksums), tried when the
# upstream server can't be reached (e.g. gmplib.org from GitHub Actions runners).
file(STRINGS ${CMAKE_CURRENT_LIST_DIR}/../../BLENDER_VERSION _blender_version LIMIT_COUNT 1)
string(REGEX MATCH "^[0-9]+\\.[0-9]+" _blender_version "${_blender_version}")
set(DEPS_SOURCE_MIRROR
  "https://projects.blender.org/blender/lib-source/media/branch/blender-v${_blender_version}-release")

# Sets `out` to the ExternalProject download arguments of dependency `prefix`.
function(dep_download_args prefix out)
  set(_file ${${prefix}_FILE})
  if((_file IN_LIST DEPS_UNVERIFIED_FILES) AND (EXISTS ${DOWNLOAD_DIR}/${_file}))
    set(_args URL file://${DOWNLOAD_DIR}/${_file})
  else()
    set(_args
      URL ${${prefix}_URI} ${DEPS_SOURCE_MIRROR}/${_file}
      URL_HASH ${${prefix}_HASH_TYPE}=${${prefix}_HASH}
      DOWNLOAD_NAME ${_file}
      DOWNLOAD_DIR ${DOWNLOAD_DIR}
    )
  endif()
  list(APPEND _args DOWNLOAD_EXTRACT_TIMESTAMP ON)
  set(${out} ${_args} PARENT_SCOPE)
endfunction()

# Helper for CMake based dependencies:
#
#   add_cmake_dep(<target-name> <VERSIONS_PREFIX>
#     [SOURCE_SUBDIR <dir>] [DEPENDS <targets...>] [PATCHES <files...>]
#     [CMAKE_ARGS <args...>])
function(add_cmake_dep name prefix)
  cmake_parse_arguments(ARG "" "SOURCE_SUBDIR" "DEPENDS;PATCHES;CMAKE_ARGS;POST_INSTALL" ${ARGN})
  set(_patch_command)
  foreach(_patch ${ARG_PATCHES})
    list(APPEND _patch_command COMMAND patch -p1 -N -i ${_patch})
  endforeach()
  if(_patch_command)
    list(REMOVE_AT _patch_command 0)
    set(_patch_command PATCH_COMMAND ${_patch_command})
  endif()
  set(_source_subdir)
  if(ARG_SOURCE_SUBDIR)
    set(_source_subdir SOURCE_SUBDIR ${ARG_SOURCE_SUBDIR})
  endif()
  dep_download_args(${prefix} _dl)
  ExternalProject_Add(external_${name}
    ${_dl}
    PREFIX ${CMAKE_BINARY_DIR}/${name}
    ${_source_subdir}
    ${_patch_command}
    CMAKE_GENERATOR Ninja
    CMAKE_ARGS ${DEFAULT_CMAKE_FLAGS} ${ARG_CMAKE_ARGS}
    BUILD_COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> -j ${DEPS_JOBS}
    INSTALL_COMMAND ${CMAKE_COMMAND} --install <BINARY_DIR>
    INSTALL_DIR ${LIBDIR}
    LOG_CONFIGURE ON
    LOG_BUILD ON
    LOG_INSTALL ON
    LOG_OUTPUT_ON_FAILURE ON
  )
  if(ARG_POST_INSTALL)
    ExternalProject_Add_Step(external_${name} post_install
      ${ARG_POST_INSTALL}
      DEPENDEES install
    )
  endif()
  if(ARG_DEPENDS)
    add_dependencies(external_${name} ${ARG_DEPENDS})
  endif()
endfunction()

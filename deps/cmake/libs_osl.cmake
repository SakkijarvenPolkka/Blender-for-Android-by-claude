# SPDX-License-Identifier: GPL-2.0-or-later
#
# Open Shading Language for Cycles: LLVM & Clang (JIT compilation of shaders, preprocessing of
# OSL sources) and OSL, all static.
#
# OSL's build runs LLVM tools (`llvm-config`, `clang++` to make bitcode, `llvm-as`,
# `llvm-link`) and its shader compiler (`oslc`). They are built as static Android executables
# and run on the build machine with QEMU user-mode emulation (like Blender's build tools), through
# wrapper scripts in `${LLVM_HOST_TOOLS}`.

if(NOT QEMU_AARCH64)
  message(FATAL_ERROR "QEMU_AARCH64 (qemu-aarch64-static) is required to build OSL")
endif()

set(LLVM_PREFIX ${LIBDIR}/llvm)
string(REGEX MATCH "^[0-9]+" LLVM_VERSION_MAJOR ${LLVM_VERSION})
set(LLVM_HOST_TOOLS ${LLVM_PREFIX}/host-bin)
set(ANDROID_SYSROOT ${ANDROID_TOOLCHAIN_DIR}/sysroot)

# Wrappers running the LLVM tools of the Android build with QEMU.
foreach(_tool llvm-config llvm-as llvm-link clang clang++)
  set(_extra_args "")
  if(_tool MATCHES "^clang")
    # Compile for Android with the headers of the NDK.
    set(_extra_args "--target=${ANDROID_TRIPLE}${ANDROID_API} --sysroot=${ANDROID_SYSROOT} ")
  endif()
  file(WRITE ${LLVM_HOST_TOOLS}/${_tool}
    "#!/bin/sh\n"
    "exec \"${QEMU_AARCH64}\" \"${LLVM_PREFIX}/bin/${_tool}\" ${_extra_args}\"$@\"\n"
  )
  file(CHMOD ${LLVM_HOST_TOOLS}/${_tool}
    PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE
  )
endforeach()
unset(_tool)
unset(_extra_args)

# ---------------------------------------------------------------------------
# LLVM & Clang
#
# The build machine's tools needed to build LLVM (`*-tblgen`) are built automatically with the
# host compiler (LLVM's "NATIVE" sub-build).

add_cmake_dep(llvm LLVM
  SOURCE_SUBDIR llvm
  CMAKE_ARGS
    -DCMAKE_INSTALL_PREFIX=${LLVM_PREFIX}
    -DLLVM_TARGETS_TO_BUILD=AArch64
    -DLLVM_ENABLE_PROJECTS=clang
    -DLLVM_HOST_TRIPLE=${ANDROID_TRIPLE}
    -DLLVM_DEFAULT_TARGET_TRIPLE=${ANDROID_TRIPLE}${ANDROID_API}
    -DLLVM_INCLUDE_TESTS=OFF
    -DLLVM_INCLUDE_EXAMPLES=OFF
    -DLLVM_INCLUDE_BENCHMARKS=OFF
    -DLLVM_INCLUDE_DOCS=OFF
    -DLLVM_INCLUDE_UTILS=OFF
    -DLLVM_BUILD_TOOLS=OFF
    -DLLVM_ENABLE_BINDINGS=OFF
    -DLLVM_ENABLE_TERMINFO=OFF
    -DLLVM_ENABLE_ZLIB=OFF
    -DLLVM_ENABLE_ZSTD=OFF
    -DLLVM_ENABLE_LIBXML2=OFF
    -DLLVM_ENABLE_LIBEDIT=OFF
    -DLLVM_ENABLE_LIBPFM=OFF
    -DLLVM_ENABLE_UNWIND_TABLES=OFF
    -DLLVM_BUILD_LLVM_DYLIB=OFF
    -DCLANG_BUILD_TOOLS=OFF
    -DCLANG_INCLUDE_TESTS=OFF
    -DCLANG_INCLUDE_DOCS=OFF
    -DCLANG_ENABLE_ARCMT=OFF
    -DCLANG_ENABLE_STATIC_ANALYZER=OFF
    -DCLANG_PLUGIN_SUPPORT=OFF
    # libclang (C API, a shared library) and its test tool, OSL uses Clang's C++ libraries.
    -DCLANG_TOOL_LIBCLANG_BUILD=OFF
    -DCLANG_TOOL_C_INDEX_TEST_BUILD=OFF
    # Tools run with QEMU (see above).
    -DCMAKE_EXE_LINKER_FLAGS=-static
    -DPython3_EXECUTABLE=${HOST_PYTHON_EXECUTABLE}
  # Tools aren't built by default (LLVM_BUILD_TOOLS), only the ones OSL's build uses.
  POST_INSTALL
    COMMAND ${CMAKE_COMMAND} --build <BINARY_DIR> -j ${DEPS_JOBS}
      --target llvm-config llvm-as llvm-link clang
    COMMAND ${CMAKE_COMMAND} -E make_directory ${LLVM_PREFIX}/bin
    COMMAND ${CMAKE_COMMAND} -E copy
      <BINARY_DIR>/bin/llvm-config <BINARY_DIR>/bin/llvm-as <BINARY_DIR>/bin/llvm-link
      ${LLVM_PREFIX}/bin/
    COMMAND ${CMAKE_COMMAND} -E copy <BINARY_DIR>/bin/clang-${LLVM_VERSION_MAJOR} ${LLVM_PREFIX}/bin/clang
    COMMAND ${CMAKE_COMMAND} -E create_symlink clang ${LLVM_PREFIX}/bin/clang++
)
add_dependencies(external_llvm external_python_host)

# ---------------------------------------------------------------------------
# Open Shading Language

add_cmake_dep(osl OSL
  DEPENDS
    external_llvm external_openimageio external_pugixml external_imath external_zlib
    external_robinmap external_pybind11 external_cross_python
  PATCHES
    ${BLENDER_PATCH_DIR}/osl_relative_inc_cmake.diff
    ${ANDROID_PATCH_DIR}/osl_android.diff
  CMAKE_ARGS
    -DLLVM_ROOT=${LLVM_PREFIX}
    -DLLVM_DIRECTORY=${LLVM_PREFIX}
    -DLLVM_CONFIG=${LLVM_HOST_TOOLS}/llvm-config
    -DLLVM_BC_GENERATOR=${LLVM_HOST_TOOLS}/clang++
    -DLLVM_AS_TOOL=${LLVM_HOST_TOOLS}/llvm-as
    -DLLVM_LINK_TOOL=${LLVM_HOST_TOOLS}/llvm-link
    -DLLVM_STATIC=ON
    -DUSE_LLVM_BITCODE=ON
    -DOSL_BUILD_TESTS=OFF
    -DOSL_BUILD_PLUGINS=OFF
    -DOSL_BUILD_SHADERS=ON
    # The Python module (`oslquery`, used by Cycles for OSL scripts), see `libs_python.cmake`.
    ${PYBIND11_MODULE_CMAKE_ARGS}
    -DUSE_QT=OFF
    -DUSE_PARTIO=OFF
    -DUSE_CCACHE=OFF
    -DINSTALL_DOCS=OFF
    -DBUILD_SHARED_LIBS=OFF
    -DLINKSTATIC=ON
    -DSTOP_ON_WARNING=OFF
    -DOpenImageIO_ROOT=${LIBDIR}
    -DCMAKE_PROJECT_INCLUDE=${CMAKE_CURRENT_LIST_DIR}/osl_project_include.cmake
    -DZLIB_LIBRARY=${LIBDIR}/lib/libz.a
    -DZLIB_INCLUDE_DIR=${LIBDIR}/include
    # Dependency of OpenColorIO (used by OpenImageIO), not found by its find module otherwise.
    -Dminizip-ng_INCLUDE_DIR=${LIBDIR}/include/minizip-ng/minizip
    -Dminizip-ng_LIBRARY=${LIBDIR}/lib/libminizip.a
    -Dpugixml_ROOT=${LIBDIR}
    -DImath_ROOT=${LIBDIR}
    -DRobinmap_ROOT=${LIBDIR}
    -DBUILD_MISSING_ROBINMAP=OFF
    # `oslc` compiles OSL's shaders during the build.
    -DCMAKE_EXE_LINKER_FLAGS=-static
    -DCMAKE_CROSSCOMPILING_EMULATOR=${QEMU_AARCH64}
)

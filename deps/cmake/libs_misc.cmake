# SPDX-License-Identifier: GPL-2.0-or-later
#
# Text shaping (HarfBuzz, FriBidi), PDF export (libharu), glTF mesh compression (Draco,
# meshoptimizer) and the solver used for motion tracking (Ceres with Abseil).

# Meson cross file for C/C++ libraries (dependencies found with pkg-config).
set(MESON_LIBS_CROSS_FILE ${CMAKE_BINARY_DIR}/meson-android-libs.ini)
file(WRITE ${MESON_LIBS_CROSS_FILE}
  "[binaries]\n"
  "c = '${ANDROID_CC}'\n"
  "cpp = '${ANDROID_CXX}'\n"
  "ar = '${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ar'\n"
  "strip = '${ANDROID_TOOLCHAIN_DIR}/bin/llvm-strip'\n"
  "pkg-config = 'pkg-config'\n"
  "\n"
  "[built-in options]\n"
  "c_args = [${_meson_c_args}, '-I${LIBDIR}/include']\n"
  "cpp_args = [${_meson_c_args}, '-I${LIBDIR}/include']\n"
  "c_link_args = ['-L${LIBDIR}/lib']\n"
  "cpp_link_args = ['-L${LIBDIR}/lib', '-static-libstdc++']\n"
  "\n"
  "[properties]\n"
  "needs_exe_wrapper = true\n"
  "\n"
  "[host_machine]\n"
  "system = 'android'\n"
  "kernel = 'linux'\n"
  "cpu_family = 'aarch64'\n"
  "cpu = 'aarch64'\n"
  "endian = 'little'\n"
)
set(MESON_ENV ${CMAKE_COMMAND} -E env
  PKG_CONFIG_LIBDIR=${LIBDIR}/lib/pkgconfig:${LIBDIR}/share/pkgconfig
  PKG_CONFIG_PATH=
)
set(MESON ${HOST_PYTHON_PREFIX}/bin/meson)

# ---------------------------------------------------------------------------
# Text

dep_download_args(HARFBUZZ _dl)
ExternalProject_Add(external_harfbuzz
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/harfbuzz
  CONFIGURE_COMMAND ${MESON_ENV} ${MESON} setup
    --cross-file ${MESON_LIBS_CROSS_FILE}
    --prefix ${LIBDIR}
    --libdir lib
    --buildtype release
    --default-library static
    -Dtests=disabled
    -Ddocs=disabled
    -Dutilities=disabled
    -Dintrospection=disabled
    -Dfreetype=enabled
    -Dglib=disabled
    -Dgobject=disabled
    -Dcairo=disabled
    -Dicu=disabled
    -Dchafa=disabled
    <BINARY_DIR> <SOURCE_DIR>
  BUILD_COMMAND ninja -C <BINARY_DIR> -j${DEPS_JOBS}
  INSTALL_COMMAND ninja -C <BINARY_DIR> install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_harfbuzz external_freetype external_python_host_tools)

dep_download_args(FRIBIDI _dl)
ExternalProject_Add(external_fribidi
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/fribidi
  CONFIGURE_COMMAND ${MESON_ENV} ${MESON} setup
    --cross-file ${MESON_LIBS_CROSS_FILE}
    --prefix ${LIBDIR}
    --libdir lib
    --buildtype release
    --default-library static
    -Ddocs=false
    -Dbin=false
    -Dtests=false
    <BINARY_DIR> <SOURCE_DIR>
  BUILD_COMMAND ninja -C <BINARY_DIR> -j${DEPS_JOBS}
  INSTALL_COMMAND ninja -C <BINARY_DIR> install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_fribidi external_python_host_tools)

# ---------------------------------------------------------------------------
# PDF (Grease Pencil export)

add_cmake_dep(haru HARU
  DEPENDS external_zlib external_png
  CMAKE_ARGS
    -DLIBHPDF_EXAMPLES=OFF
    -DLIBHPDF_ENABLE_EXCEPTIONS=ON
)

# ---------------------------------------------------------------------------
# glTF mesh compression, used through Blender's bridge libraries (`intern/*_bridge`).

add_cmake_dep(draco DRACO
  CMAKE_ARGS
    -DDRACO_JS_GLUE=OFF
    -DDRACO_TESTS=OFF
)

add_cmake_dep(meshoptimizer MESHOPTIMIZER
  CMAKE_ARGS
    -DMESHOPT_BUILD_SHARED_LIBS=OFF
)

# ---------------------------------------------------------------------------
# Motion tracking (libmv): Ceres solver

add_cmake_dep(abseil ABSEIL
  CMAKE_ARGS
    -DABSL_PROPAGATE_CXX_STD=ON
    -DABSL_BUILD_TESTING=OFF
)

add_cmake_dep(ceres CERES
  DEPENDS external_abseil external_eigen external_tbb
  CMAKE_ARGS
    -Dabsl_DIR=${LIBDIR}/lib/cmake/absl
    -DBUILD_TESTING=OFF
    -DBUILD_BENCHMARKS=OFF
    -DBUILD_EXAMPLES=OFF
    -DUSE_CUDA=OFF
    -DMINIGLOG=ON
    -DGFLAGS=OFF
    -DSUITESPARSE=OFF
    -DLAPACK=OFF
    -DPROVIDE_UNINSTALL_TARGET=OFF
)

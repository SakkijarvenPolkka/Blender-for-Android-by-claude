# SPDX-License-Identifier: GPL-2.0-or-later
#
# Compression, image, color-management and general purpose libraries.

# NOTE: some projects always build shared libraries as well, those are removed
# after installing so that everything links statically into `libblender.so`.

# ---------------------------------------------------------------------------
# Compression

add_cmake_dep(zlib ZLIB
  PATCHES ${BLENDER_PATCH_DIR}/zlib.diff
  CMAKE_ARGS -DZLIB_BUILD_EXAMPLES=OFF
  POST_INSTALL COMMAND sh -c "rm -f ${LIBDIR}/lib/libz.so*"
)

add_cmake_dep(zstd ZSTD
  SOURCE_SUBDIR build/cmake
  CMAKE_ARGS
    -DZSTD_BUILD_PROGRAMS=OFF
    -DZSTD_BUILD_SHARED=OFF
    -DZSTD_BUILD_STATIC=ON
    -DZSTD_BUILD_TESTS=OFF
    -DZSTD_LEGACY_SUPPORT=OFF
    -DZSTD_MULTITHREAD_SUPPORT=ON
)

add_cmake_dep(brotli BROTLI
  CMAKE_ARGS -DBROTLI_DISABLE_TESTS=ON
  POST_INSTALL COMMAND sh -c "rm -f ${LIBDIR}/lib/libbrotli*.so*"
)

add_cmake_dep(deflate DEFLATE
  CMAKE_ARGS
    -DLIBDEFLATE_BUILD_STATIC_LIB=ON
    -DLIBDEFLATE_BUILD_SHARED_LIB=OFF
    -DLIBDEFLATE_BUILD_GZIP=OFF
)

# ---------------------------------------------------------------------------
# Image formats

add_cmake_dep(png PNG
  DEPENDS external_zlib
  CMAKE_ARGS
    -DPNG_SHARED=OFF
    -DPNG_STATIC=ON
    -DPNG_TESTS=OFF
    -DPNG_TOOLS=OFF
    -DPNG_FRAMEWORK=OFF
    -DPNG_ARM_NEON=on
    -DZLIB_ROOT=${LIBDIR}
)

add_cmake_dep(jpeg JPEG
  CMAKE_ARGS
    # Relative paths are resolved against the build directory by this project.
    -DCMAKE_INSTALL_LIBDIR=${LIBDIR}/lib
    -DWITH_JPEG8=ON
    -DENABLE_STATIC=ON
    -DENABLE_SHARED=OFF
    -DWITH_SIMD=ON
    -DWITH_TURBOJPEG=OFF
)

add_cmake_dep(tiff TIFF
  DEPENDS external_zlib external_jpeg external_deflate
  CMAKE_ARGS
    -DZLIB_ROOT=${LIBDIR}
    -DJPEG_ROOT=${LIBDIR}
    -Dlzma=OFF
    -Djbig=OFF
    -Dzstd=OFF
    -Dwebp=OFF
    -Dlerc=OFF
    -Dlibdeflate=ON
    -Dtiff-tests=OFF
    -Dtiff-tools=OFF
    -Dtiff-docs=OFF
    -Dtiff-contrib=OFF
    -Dsphinx=OFF
  POST_INSTALL COMMAND ${CMAKE_COMMAND}
    -DTARGETS_FILE=${LIBDIR}/lib/cmake/tiff/TiffTargets.cmake
    -P ${CMAKE_CURRENT_LIST_DIR}/fix_tiff_targets.cmake
)

add_cmake_dep(webp WEBP
  CMAKE_ARGS
    -DWEBP_BUILD_ANIM_UTILS=OFF
    -DWEBP_BUILD_CWEBP=OFF
    -DWEBP_BUILD_DWEBP=OFF
    -DWEBP_BUILD_GIF2WEBP=OFF
    -DWEBP_BUILD_IMG2WEBP=OFF
    -DWEBP_BUILD_VWEBP=OFF
    -DWEBP_BUILD_WEBPINFO=OFF
    -DWEBP_BUILD_WEBPMUX=OFF
    -DWEBP_BUILD_EXTRAS=OFF
)

add_cmake_dep(openjpeg OPENJPEG
  CMAKE_ARGS
    -DBUILD_CODEC=OFF
    -DBUILD_STATIC_LIBS=ON
    -DBUILD_THIRDPARTY=OFF
)

add_cmake_dep(openjph OPENJPH
  PATCHES ${BLENDER_PATCH_DIR}/openjph_table_init_243.diff
  CMAKE_ARGS
    -DOJPH_BUILD_TESTS=OFF
    -DOJPH_ENABLE_TIFF_SUPPORT=OFF
    -DOJPH_BUILD_EXECUTABLES=OFF
)

add_cmake_dep(imath IMATH
  CMAKE_ARGS -DPYTHON=OFF
)

# NOTE: Blender's `openexr_deflate_cmake.diff` is not applied, it is for shared OpenEXR
# libraries. The static libraries need `libdeflate` to be found by users of OpenEXR.
add_cmake_dep(openexr OPENEXR
  DEPENDS external_imath external_deflate external_openjph external_zlib
  CMAKE_ARGS
    -DOPENEXR_BUILD_BOTH_STATIC_SHARED=OFF
    -DOPENEXR_INSTALL_TOOLS=OFF
    -DOPENEXR_BUILD_TOOLS=OFF
    -DOPENEXR_BUILD_EXAMPLES=OFF
    -DOPENEXR_INSTALL_EXAMPLES=OFF
    -DOPENEXR_BUILD_PYTHON=OFF
    -DOPENEXR_FORCE_INTERNAL_DEFLATE=OFF
    -DOPENEXR_FORCE_INTERNAL_OPENJPH=OFF
)

# ---------------------------------------------------------------------------
# Utility libraries

add_cmake_dep(fmt FMT
  CMAKE_ARGS -DFMT_DOC=OFF -DFMT_TEST=OFF
)

add_cmake_dep(robinmap ROBINMAP)

add_cmake_dep(pugixml PUGIXML
  CMAKE_ARGS -DPUGIXML_BUILD_TESTS=OFF
)

add_cmake_dep(tbb TBB
  CMAKE_ARGS
    -DTBB_TEST=OFF
    -DTBB_STRICT=OFF
    -DTBB_EXAMPLES=OFF
    -DTBBMALLOC_BUILD=ON
    -DTBBMALLOC_PROXY_BUILD=OFF
    -DTBB_DISABLE_HWLOC_AUTOMATIC_SEARCH=ON
)

add_cmake_dep(eigen EIGEN
  DEPENDS external_tbb
  PATCHES ${BLENDER_PATCH_DIR}/eigen_tbb_support.diff
  CMAKE_ARGS
    -DEIGEN_BUILD_DOC=OFF
    -DEIGEN_BUILD_TESTING=OFF
    -DEIGEN_BUILD_PKGCONFIG=OFF
    -DEIGEN_BUILD_BLAS=OFF
    -DEIGEN_BUILD_LAPACK=OFF
)

add_cmake_dep(freetype FREETYPE
  DEPENDS external_brotli external_zlib
  CMAKE_ARGS
    -DFT_DISABLE_BZIP2=ON
    -DFT_DISABLE_HARFBUZZ=ON
    -DFT_DISABLE_PNG=ON
    -DFT_REQUIRE_BROTLI=ON
    -DFT_REQUIRE_ZLIB=ON
    -DBROTLIDEC_INCLUDE_DIRS=${LIBDIR}/include
    "-DBROTLIDEC_LIBRARIES=${LIBDIR}/lib/libbrotlidec-static.a$<SEMICOLON>${LIBDIR}/lib/libbrotlicommon-static.a"
    -DZLIB_ROOT=${LIBDIR}
)

# sse2neon: header only (used by Cycles and others on ARM).
dep_download_args(SSE2NEON _dl)
ExternalProject_Add(external_sse2neon
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/sse2neon
  CONFIGURE_COMMAND ""
  BUILD_COMMAND ""
  INSTALL_COMMAND ${CMAKE_COMMAND} -E copy <SOURCE_DIR>/sse2neon.h ${LIBDIR}/include/sse2neon.h
)

# ---------------------------------------------------------------------------
# OpenColorIO and its dependencies

add_cmake_dep(expat EXPAT
  SOURCE_SUBDIR expat
  CMAKE_ARGS
    -DEXPAT_BUILD_DOCS=OFF
    -DEXPAT_BUILD_EXAMPLES=OFF
    -DEXPAT_BUILD_TESTS=OFF
    -DEXPAT_BUILD_TOOLS=OFF
    -DEXPAT_BUILD_FUZZERS=OFF
    -DEXPAT_SHARED_LIBS=OFF
)

add_cmake_dep(yamlcpp YAMLCPP
  CMAKE_ARGS
    -DYAML_CPP_BUILD_TESTS=OFF
    -DYAML_CPP_BUILD_TOOLS=OFF
    -DYAML_CPP_BUILD_CONTRIB=OFF
    -DYAML_BUILD_SHARED_LIBS=OFF
)

dep_download_args(PYSTRING _dl)
ExternalProject_Add(external_pystring
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/pystring
  PATCH_COMMAND ${CMAKE_COMMAND} -E copy ${BLENDER_PATCH_DIR}/cmakelists_pystring.txt <SOURCE_DIR>/CMakeLists.txt
  CMAKE_GENERATOR Ninja
  CMAKE_ARGS ${DEFAULT_CMAKE_FLAGS}
  INSTALL_DIR ${LIBDIR}
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_OUTPUT_ON_FAILURE ON
)

add_cmake_dep(minizipng MINIZIPNG
  DEPENDS external_zlib
  CMAKE_ARGS
    -DMZ_FETCH_LIBS=OFF
    -DMZ_LIBCOMP=OFF
    -DMZ_PKCRYPT=OFF
    -DMZ_WZAES=OFF
    -DMZ_OPENSSL=OFF
    -DMZ_SIGNING=OFF
    -DMZ_LZMA=OFF
    -DMZ_ZSTD=OFF
    -DMZ_BZIP2=OFF
    -DMZ_ICONV=OFF
    -DMZ_ZLIB=ON
    -DZLIB_ROOT=${LIBDIR}
    # OpenColorIO expects this non-standard include path.
    -DCMAKE_INSTALL_INCLUDEDIR=include/minizip-ng
)

add_cmake_dep(opencolorio OPENCOLORIO
  DEPENDS external_yamlcpp external_expat external_imath external_pystring external_zlib external_minizipng
  CMAKE_ARGS
    -DOCIO_BUILD_APPS=OFF
    -DOCIO_BUILD_PYTHON=OFF
    -DOCIO_BUILD_NUKE=OFF
    -DOCIO_BUILD_JAVA=OFF
    -DOCIO_BUILD_DOCS=OFF
    -DOCIO_BUILD_TESTS=OFF
    -DOCIO_BUILD_GPU_TESTS=OFF
    -DOCIO_BUILD_OPENFX=OFF
    -DOCIO_USE_SIMD=OFF
    -DOCIO_INSTALL_EXT_PACKAGES=NONE
    -Dexpat_ROOT=${LIBDIR}
    -Dyaml-cpp_ROOT=${LIBDIR}
    -Dpystring_ROOT=${LIBDIR}
    -DImath_ROOT=${LIBDIR}
    -Dminizip-ng_ROOT=${LIBDIR}
    -Dminizip-ng_INCLUDE_DIR=${LIBDIR}/include/minizip-ng/minizip
    -Dminizip-ng_LIBRARY=${LIBDIR}/lib/libminizip.a
    -DZLIB_ROOT=${LIBDIR}
)

# ---------------------------------------------------------------------------
# OpenImageIO

add_cmake_dep(openimageio OPENIMAGEIO
  DEPENDS
    external_png external_jpeg external_tiff external_webp external_openjpeg
    external_openexr external_fmt external_robinmap external_pugixml external_tbb
    external_opencolorio external_zlib external_pybind11 external_cross_python
  PATCHES
    ${BLENDER_PATCH_DIR}/openimageio.diff
    ${BLENDER_PATCH_DIR}/openimageio_dds_3d_5133.diff
  CMAKE_ARGS
    -DLINKSTATIC=ON
    -DOpenImageIO_BUILD_MISSING_DEPS=
    -DUSE_NUKE=OFF
    -DUSE_OPENVDB=OFF
    -DUSE_FREETYPE=OFF
    -DUSE_DCMTK=OFF
    -DUSE_TBB=ON
    -DUSE_QT=OFF
    # The Python module (`import OpenImageIO`, as in Blender releases), see `libs_python.cmake`.
    ${PYBIND11_MODULE_CMAKE_ARGS}
    -DUSE_GIF=OFF
    -DUSE_OPENCV=OFF
    -DUSE_OPENJPEG=ON
    -DUSE_FFMPEG=OFF
    -DUSE_PTEX=OFF
    -DUSE_LIBHEIF=OFF
    -DUSE_LIBRAW=OFF
    -DUSE_JXL=OFF
    -DUSE_OPENCOLORIO=ON
    -DUSE_WEBP=ON
    -DUSE_EXTERNAL_PUGIXML=ON
    -DOIIO_BUILD_TOOLS=OFF
    -DOIIO_BUILD_TESTS=OFF
    -DOIIO_BUILD_DOCS=OFF
    -DINSTALL_DOCS=OFF
    -DINSTALL_FONTS=OFF
    -DSTOP_ON_WARNING=OFF
    -DUSE_SIMD=0
    -DZLIB_ROOT=${LIBDIR}
    -DPNG_ROOT=${LIBDIR}
    -DTIFF_ROOT=${LIBDIR}
    -DJPEG_ROOT=${LIBDIR}
    -Dlibjpeg-turbo_ROOT=${LIBDIR}
    -DOpenJPEG_ROOT=${LIBDIR}
    -DRobinmap_ROOT=${LIBDIR}
    -DWebP_ROOT=${LIBDIR}
    -DOpenEXR_ROOT=${LIBDIR}
    -DImath_ROOT=${LIBDIR}
    -DTBB_ROOT=${LIBDIR}
    -Dfmt_ROOT=${LIBDIR}
    -Dpugixml_ROOT=${LIBDIR}
    -Dlibdeflate_ROOT=${LIBDIR}
    -DOpenColorIO_ROOT=${LIBDIR}
    -Dopenjph_ROOT=${LIBDIR}
    # Static OpenColorIO needs its dependencies.
    -Dminizip-ng_INCLUDE_DIR=${LIBDIR}/include/minizip-ng/minizip
    -Dminizip-ng_LIBRARY=${LIBDIR}/lib/libminizip.a
)

# ---------------------------------------------------------------------------
# Geometry

add_cmake_dep(opensubdiv OPENSUBDIV
  DEPENDS external_tbb
  CMAKE_ARGS
    -DNO_LIB=OFF
    -DNO_EXAMPLES=ON
    -DNO_TUTORIALS=ON
    -DNO_REGRESSION=ON
    -DNO_PTEX=ON
    -DNO_DOC=ON
    -DNO_OMP=ON
    -DNO_TBB=OFF
    -DNO_CUDA=ON
    -DNO_OPENCL=ON
    -DNO_CLEW=ON
    -DNO_OPENGL=ON
    -DNO_METAL=ON
    -DNO_DX=ON
    -DNO_TESTS=ON
    -DNO_GLTESTS=ON
    -DNO_GLEW=ON
    -DNO_GLFW=ON
    -DNO_GLFW_X11=ON
    -DNO_MACOS_FRAMEWORK=ON
    # Blender uses the GLSL patch shader source (plain strings, no OpenGL needed).
    -DOSD_PATCH_SHADER_SOURCE_GLSL=ON
    -DTBB_ROOT=${LIBDIR}
    # On Android this overrides the install prefix (and is the destination of `Android.mk`).
    -DLIBRARY_OUTPUT_PATH_ROOT=${LIBDIR}
  POST_INSTALL COMMAND ${CMAKE_COMMAND} -E remove -f ${LIBDIR}/Android.mk
)

add_cmake_dep(manifold MANIFOLD
  DEPENDS external_tbb
  CMAKE_ARGS
    -DMANIFOLD_JSBIND=OFF
    -DMANIFOLD_CBIND=OFF
    -DMANIFOLD_PYBIND=OFF
    -DMANIFOLD_PAR=ON
    -DMANIFOLD_CROSS_SECTION=OFF
    -DMANIFOLD_EXPORT=OFF
    -DMANIFOLD_DEBUG=OFF
    -DMANIFOLD_TEST=OFF
    -DMANIFOLD_DOWNLOADS=OFF
    -DTBB_ROOT=${LIBDIR}
    -DTRACY_ENABLE=OFF
)

dep_download_args(POTRACE _dl)
ExternalProject_Add(external_potrace
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/potrace
  PATCH_COMMAND ${CMAKE_COMMAND} -E copy ${BLENDER_PATCH_DIR}/cmakelists_potrace.txt <SOURCE_DIR>/CMakeLists.txt
  CMAKE_GENERATOR Ninja
  CMAKE_ARGS ${DEFAULT_CMAKE_FLAGS}
  INSTALL_DIR ${LIBDIR}
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_OUTPUT_ON_FAILURE ON
)

dep_download_args(GMP _dl)
ExternalProject_Add(external_gmp
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/gmp
  BUILD_IN_SOURCE ON
  PATCH_COMMAND patch -p1 -N -i ${BLENDER_PATCH_DIR}/gmp.diff
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure ${AUTOTOOLS_HOST_ARGS} --enable-cxx
  BUILD_COMMAND ${MAKE_CMD}
  INSTALL_COMMAND make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

# FFTW: double and single precision (NEON is only available for single).
foreach(_fftw_variant double float)
  if(_fftw_variant STREQUAL "float")
    set(_fftw_args --enable-float --enable-neon)
  else()
    set(_fftw_args)
  endif()
  dep_download_args(FFTW _dl)
  ExternalProject_Add(external_fftw3_${_fftw_variant}
    ${_dl}
    PREFIX ${CMAKE_BINARY_DIR}/fftw3_${_fftw_variant}
    CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure ${AUTOTOOLS_HOST_ARGS}
      --enable-threads --disable-fortran --disable-doc ${_fftw_args}
    BUILD_COMMAND ${MAKE_CMD}
    INSTALL_COMMAND make install
    LOG_CONFIGURE ON
    LOG_BUILD ON
    LOG_INSTALL ON
    LOG_OUTPUT_ON_FAILURE ON
  )
endforeach()
add_dependencies(external_fftw3_float external_fftw3_double)

# SPDX-License-Identifier: GPL-2.0-or-later
#
# Audio & video: FFmpeg with the same codec libraries as official Blender releases
# (x264, x265, libvpx, aom, Opus, Vorbis, Theora, LAME), FLAC and libsndfile.

# Old autotools projects don't know Android (`aarch64-linux-android`): use current copies of
# `config.sub` & `config.guess` from automake.
file(GLOB _config_sub /usr/share/automake*/config.sub /usr/share/misc/config.sub)
list(GET _config_sub 0 AUTOTOOLS_CONFIG_SUB)
get_filename_component(_config_dir ${AUTOTOOLS_CONFIG_SUB} DIRECTORY)
set(AUTOTOOLS_CONFIG_GUESS ${_config_dir}/config.guess)
if(NOT EXISTS ${AUTOTOOLS_CONFIG_SUB} OR NOT EXISTS ${AUTOTOOLS_CONFIG_GUESS})
  message(FATAL_ERROR "config.sub/config.guess not found, install automake")
endif()
set(AUTOTOOLS_UPDATE_CONFIG_SUB
  ${CMAKE_COMMAND} -E copy ${AUTOTOOLS_CONFIG_SUB} ${AUTOTOOLS_CONFIG_GUESS} <SOURCE_DIR>/
)

# ---------------------------------------------------------------------------
# Xiph codecs

add_cmake_dep(ogg OGG
  CMAKE_ARGS
    -DINSTALL_DOCS=OFF
)

add_cmake_dep(vorbis VORBIS
  DEPENDS external_ogg
  CMAKE_ARGS
    -DOGG_ROOT=${LIBDIR}
  # The CMake build doesn't list the math library for static linking in `vorbis.pc`.
  POST_INSTALL COMMAND sed -i "s/^Libs.private: *$/Libs.private: -lm/" ${LIBDIR}/lib/pkgconfig/vorbis.pc
)

add_cmake_dep(flac FLAC
  DEPENDS external_ogg
  CMAKE_ARGS
    -DBUILD_PROGRAMS=OFF
    -DBUILD_EXAMPLES=OFF
    -DBUILD_DOCS=OFF
    -DBUILD_TESTING=OFF
    -DINSTALL_MANPAGES=OFF
    -DWITH_FORTIFY_SOURCE=OFF
    -DOgg_ROOT=${LIBDIR}
)

# The CMake build of the Opus release archive is incomplete, use autotools (like Blender).
dep_download_args(OPUS _dl)
ExternalProject_Add(external_opus
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/opus
  BUILD_IN_SOURCE ON
  PATCH_COMMAND ${AUTOTOOLS_UPDATE_CONFIG_SUB}
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure ${AUTOTOOLS_HOST_ARGS}
    --disable-maintainer-mode
    --disable-doc
    --disable-extra-programs
  BUILD_COMMAND ${MAKE_CMD}
  INSTALL_COMMAND make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

dep_download_args(THEORA _dl)
ExternalProject_Add(external_theora
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/theora
  BUILD_IN_SOURCE ON
  PATCH_COMMAND ${AUTOTOOLS_UPDATE_CONFIG_SUB}
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} HAVE_PDFLATEX=no <SOURCE_DIR>/configure ${AUTOTOOLS_HOST_ARGS}
    --with-ogg=${LIBDIR}
    --with-vorbis=${LIBDIR}
    --disable-examples
    --disable-oggtest
    --disable-vorbistest
    --disable-sdltest
    --disable-spec
    --disable-asm
  BUILD_COMMAND ${MAKE_CMD}
  INSTALL_COMMAND make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_theora external_ogg external_vorbis)

# ---------------------------------------------------------------------------
# MP3 (encoder)

dep_download_args(LAME _dl)
ExternalProject_Add(external_lame
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/lame
  BUILD_IN_SOURCE ON
  PATCH_COMMAND ${AUTOTOOLS_UPDATE_CONFIG_SUB}
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure ${AUTOTOOLS_HOST_ARGS}
    --enable-export=full
    --without-vorbis
    --disable-mp3x
    --disable-mp3rtp
    --disable-gtktest
    --disable-frontend
    --disable-decoder
  BUILD_COMMAND ${MAKE_CMD}
  INSTALL_COMMAND make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

# ---------------------------------------------------------------------------
# Video codecs

dep_download_args(VPX _dl)
ExternalProject_Add(external_vpx
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/vpx
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure
    --target=arm64-android-gcc
    --prefix=${LIBDIR}
    --libdir=${LIBDIR}/lib
    --enable-static
    --disable-shared
    --enable-pic
    --enable-vp8
    --enable-vp9
    --enable-runtime-cpu-detect
    --disable-examples
    --disable-tools
    --disable-docs
    --disable-unit-tests
    --disable-install-bins
    --disable-install-srcs
    --disable-install-docs
  BUILD_COMMAND ${AUTOTOOLS_ENV} ${MAKE_CMD}
  INSTALL_COMMAND ${AUTOTOOLS_ENV} make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

dep_download_args(X264 _dl)
ExternalProject_Add(external_x264
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/x264
  BUILD_IN_SOURCE ON
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure
    --host=${ANDROID_TRIPLE}
    --cross-prefix=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-
    --prefix=${LIBDIR}
    --libdir=${LIBDIR}/lib
    --enable-static
    --enable-pic
    --disable-cli
    --disable-opencl
    --disable-lavf
    --disable-swscale
    --disable-ffms
    --disable-gpac
    --disable-lsmash
  BUILD_COMMAND ${AUTOTOOLS_ENV} ${MAKE_CMD}
  INSTALL_COMMAND ${AUTOTOOLS_ENV} make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

add_cmake_dep(x265 X265
  SOURCE_SUBDIR source
  CMAKE_ARGS
    -DENABLE_SHARED=OFF
    -DENABLE_PIC=ON
    -DENABLE_CLI=OFF
    -DENABLE_LIBNUMA=OFF
    # NEON assembly isn't set up for cross-compiling, the intrinsics are still used.
    -DENABLE_ASSEMBLY=OFF
    -DCMAKE_POLICY_DEFAULT_CMP0025=NEW
  # The libraries of the C++ runtime found by x265's build are invalid linker flags
  # (`-l-l:libunwind.a`), use the static C++ runtime of the NDK (like Blender).
  POST_INSTALL COMMAND sed -i "s/^Libs.private:.*$/Libs.private: -lc++_static -lc++abi -lm -ldl/"
    ${LIBDIR}/lib/pkgconfig/x265.pc
)

add_cmake_dep(aom AOM
  PATCHES
    ${BLENDER_PATCH_DIR}/aom_6d2b7f71b98bfa28e372b1f2d85f137280bdb3de.diff
  CMAKE_ARGS
    -DAOM_TARGET_CPU=arm64
    -DCONFIG_RUNTIME_CPU_DETECT=1
    -DENABLE_TESTDATA=OFF
    -DENABLE_TESTS=OFF
    -DENABLE_TOOLS=OFF
    -DENABLE_EXAMPLES=OFF
    -DENABLE_DOCS=OFF
)

# ---------------------------------------------------------------------------
# libsndfile (audio files)

add_cmake_dep(sndfile SNDFILE
  DEPENDS external_ogg external_vorbis external_opus external_flac external_lame
  PATCHES
    ${BLENDER_PATCH_DIR}/sndfile_1045.diff
  CMAKE_ARGS
    -DOgg_ROOT=${LIBDIR}
    -DVorbis_ROOT=${LIBDIR}
    -DOpus_ROOT=${LIBDIR}
    -DFLAC_ROOT=${LIBDIR}
    -DLAME_ROOT=${LIBDIR}
    -DMP3LAME_ROOT=${LIBDIR}
    -DCMAKE_DISABLE_FIND_PACKAGE_ALSA=ON
    -DCMAKE_DISABLE_FIND_PACKAGE_mpg123=ON
    -DCMAKE_DISABLE_FIND_PACKAGE_Speex=ON
    -DCMAKE_DISABLE_FIND_PACKAGE_SQLite3=ON
    -DBUILD_PROGRAMS=OFF
    -DBUILD_EXAMPLES=OFF
    -DBUILD_TESTING=OFF
    -DENABLE_CPACK=OFF
    -DENABLE_PACKAGE_CONFIG=ON
    -DPYTHON_EXECUTABLE=${HOST_PYTHON_EXECUTABLE}
)

# ---------------------------------------------------------------------------
# FFmpeg

dep_download_args(FFMPEG _dl)
ExternalProject_Add(external_ffmpeg
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/ffmpeg
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure
    --prefix=${LIBDIR}
    --libdir=${LIBDIR}/lib
    --enable-cross-compile
    --target-os=android
    --arch=aarch64
    --cc=${ANDROID_CC}
    --cxx=${ANDROID_CXX}
    --ar=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ar
    --nm=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-nm
    --ranlib=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ranlib
    --strip=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-strip
    --pkg-config=pkg-config
    --pkg-config-flags=--static
    "--extra-cflags=${DEPS_C_FLAGS} -I${LIBDIR}/include"
    "--extra-ldflags=-L${LIBDIR}/lib"
    --enable-static
    --disable-shared
    --enable-pic
    --disable-programs
    --disable-doc
    --disable-debug
    --enable-optimizations
    --enable-runtime-cpudetect
    --enable-gpl
    --disable-nonfree
    --disable-version3
    --enable-zlib
    --enable-libx264
    --enable-libx265
    --enable-libvpx
    --enable-libaom
    --enable-libopus
    --enable-libvorbis
    --enable-libtheora
    --enable-libmp3lame
    --enable-libopenjpeg
    --disable-lzma
    --disable-bzlib
    --disable-iconv
    --disable-network
    --disable-indevs
    --disable-outdevs
    --disable-vulkan
    --disable-jni
    --disable-mediacodec
    --disable-sdl2
    --disable-openssl
  BUILD_COMMAND ${AUTOTOOLS_ENV} ${MAKE_CMD}
  INSTALL_COMMAND ${AUTOTOOLS_ENV} make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_ffmpeg
  external_zlib
  external_openjpeg
  external_x264
  external_x265
  external_vpx
  external_aom
  external_opus
  external_vorbis
  external_theora
  external_lame
)

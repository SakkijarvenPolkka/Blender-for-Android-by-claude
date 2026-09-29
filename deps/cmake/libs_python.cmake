# SPDX-License-Identifier: GPL-2.0-or-later
#
# CPython for Android (officially supported since Python 3.13, PEP 738).
#
# The standard library extension modules are linked statically into `libpython3.x.a`
# (`MODULE_BUILDTYPE=static`), which in turn is linked into `libblender.so`: no separate
# libraries to package & load. Extension modules of bundled packages (NumPy) are shared
# libraries, see `libs_python_packages.cmake`.

# ---------------------------------------------------------------------------
# Python's own dependencies

dep_download_args(BZIP2 _dl)
ExternalProject_Add(external_bzip2
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/bzip2
  BUILD_IN_SOURCE ON
  CONFIGURE_COMMAND ""
  BUILD_COMMAND make -j${DEPS_JOBS} libbz2.a
    CC=${ANDROID_CC}
    AR=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ar
    RANLIB=${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ranlib
    "CFLAGS=${DEPS_C_FLAGS} -D_FILE_OFFSET_BITS=64"
  INSTALL_COMMAND ${CMAKE_COMMAND} -E copy <SOURCE_DIR>/libbz2.a ${LIBDIR}/lib/libbz2.a
    COMMAND ${CMAKE_COMMAND} -E copy <SOURCE_DIR>/bzlib.h ${LIBDIR}/include/bzlib.h
  LOG_BUILD ON
  LOG_OUTPUT_ON_FAILURE ON
)

dep_download_args(LZMA _dl)
ExternalProject_Add(external_lzma
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/lzma
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure ${AUTOTOOLS_HOST_ARGS}
    --disable-xz --disable-xzdec --disable-lzmadec --disable-lzmainfo
    --disable-scripts --disable-doc --disable-nls
  BUILD_COMMAND ${MAKE_CMD}
  INSTALL_COMMAND make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

dep_download_args(FFI _dl)
ExternalProject_Add(external_ffi
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/ffi
  CONFIGURE_COMMAND ${AUTOTOOLS_ENV} <SOURCE_DIR>/configure ${AUTOTOOLS_HOST_ARGS}
    --disable-docs --disable-multi-os-directory --disable-exec-static-tramp
  BUILD_COMMAND ${MAKE_CMD}
  INSTALL_COMMAND make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

# SQLite: build the amalgamation directly, simpler than cross-configuring.
dep_download_args(SQLITE _dl)
ExternalProject_Add(external_sqlite
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/sqlite
  BUILD_IN_SOURCE ON
  CONFIGURE_COMMAND ""
  BUILD_COMMAND ${ANDROID_CC} ${DEPS_C_FLAGS_LIST}
    -DSQLITE_ENABLE_FTS5 -DSQLITE_ENABLE_RTREE -DSQLITE_ENABLE_MATH_FUNCTIONS
    -DSQLITE_ENABLE_JSON1 -DSQLITE_THREADSAFE=1 -DSQLITE_OMIT_LOAD_EXTENSION=0
    -c sqlite3.c -o sqlite3.o
    COMMAND ${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ar rcs libsqlite3.a sqlite3.o
  INSTALL_COMMAND ${CMAKE_COMMAND} -E copy libsqlite3.a ${LIBDIR}/lib/libsqlite3.a
    COMMAND ${CMAKE_COMMAND} -E copy sqlite3.h sqlite3ext.h ${LIBDIR}/include/
  LOG_BUILD ON
  LOG_OUTPUT_ON_FAILURE ON
)

# OpenSSL (needed for `ssl`/`hashlib`, used by Blender's online extensions).
set(SSL_CONFIGURE_ENV
  ${CMAKE_COMMAND} -E env
    ANDROID_NDK_ROOT=${ANDROID_NDK}
    PATH=${ANDROID_TOOLCHAIN_DIR}/bin:$ENV{PATH}
    "CFLAGS=${DEPS_C_FLAGS}"
)
dep_download_args(SSL _dl)
ExternalProject_Add(external_ssl
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/ssl
  BUILD_IN_SOURCE ON
  CONFIGURE_COMMAND ${SSL_CONFIGURE_ENV} perl ./Configure android-arm64
    -D__ANDROID_API__=${ANDROID_API}
    no-shared no-tests no-docs no-apps no-module
    --prefix=${LIBDIR} --libdir=lib --openssldir=/system/etc/security
  BUILD_COMMAND ${SSL_CONFIGURE_ENV} make -j${DEPS_JOBS} build_libs
  INSTALL_COMMAND ${SSL_CONFIGURE_ENV} make install_dev
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

# ---------------------------------------------------------------------------
# Host ("build") Python of the same version, required for cross-compiling
# CPython and used by Blender's build system.

set(HOST_PYTHON_PREFIX "${CMAKE_BINARY_DIR}/host_python/install" CACHE PATH
  "Install prefix of the host Python (used by the Blender build as well)")
set(HOST_PYTHON_EXECUTABLE ${HOST_PYTHON_PREFIX}/bin/python${PYTHON_SHORT_VERSION})

dep_download_args(PYTHON _dl)
ExternalProject_Add(external_python_host
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/host_python
  CONFIGURE_COMMAND <SOURCE_DIR>/configure --prefix=${HOST_PYTHON_PREFIX}
    --without-ensurepip --disable-test-modules
  BUILD_COMMAND make -j${DEPS_JOBS}
  INSTALL_COMMAND make install
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)

# ---------------------------------------------------------------------------
# Target Python

set(PYTHON_ANDROID_ENV
  ${AUTOTOOLS_ENV}
    MODULE_BUILDTYPE=static
    "LIBSQLITE3_CFLAGS=-I${LIBDIR}/include"
    "LIBSQLITE3_LIBS=-L${LIBDIR}/lib -lsqlite3 -lm"
    "LIBFFI_CFLAGS=-I${LIBDIR}/include"
    "LIBFFI_LIBS=-L${LIBDIR}/lib -lffi"
    "LIBLZMA_CFLAGS=-I${LIBDIR}/include"
    "LIBLZMA_LIBS=-L${LIBDIR}/lib -llzma"
    "BZIP2_CFLAGS=-I${LIBDIR}/include"
    "BZIP2_LIBS=-L${LIBDIR}/lib -lbz2"
    "ZLIB_CFLAGS=-I${LIBDIR}/include"
    "ZLIB_LIBS=-L${LIBDIR}/lib -lz"
    "LIBMPDEC_CFLAGS="
    "LIBUUID_CFLAGS="
    ac_cv_file__dev_ptmx=no
    ac_cv_file__dev_ptc=no
)

dep_download_args(PYTHON _dl)
ExternalProject_Add(external_python
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/python
  CONFIGURE_COMMAND ${PYTHON_ANDROID_ENV} <SOURCE_DIR>/configure
    --host=${ANDROID_TRIPLE}
    --build=x86_64-pc-linux-gnu
    --prefix=${LIBDIR}
    --with-build-python=${HOST_PYTHON_EXECUTABLE}
    --without-ensurepip
    --disable-shared
    --disable-test-modules
    --with-openssl=${LIBDIR}
    --with-system-expat
    --without-readline
  BUILD_COMMAND ${PYTHON_ANDROID_ENV} make -j${DEPS_JOBS}
  INSTALL_COMMAND ${PYTHON_ANDROID_ENV} make install
    # Internal libraries of the statically linked `_decimal` & `_sha2` modules, they are
    # not part of `libpython3.x.a`.
    COMMAND ${CMAKE_COMMAND} -E copy
      <BINARY_DIR>/Modules/_decimal/libmpdec/libmpdec.a
      <BINARY_DIR>/Modules/_hacl/libHacl_Hash_SHA2.a
      ${LIBDIR}/lib/
    COMMAND ${CMAKE_COMMAND} -DPYTHON_LIBDIR=${LIBDIR}/lib/python${PYTHON_SHORT_VERSION}
      -P ${CMAKE_CURRENT_LIST_DIR}/fix_python_sysconfig.cmake
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_python
  external_python_host
  external_zlib
  external_bzip2
  external_lzma
  external_ffi
  external_sqlite
  external_ssl
  external_expat
)

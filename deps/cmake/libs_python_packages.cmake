# SPDX-License-Identifier: GPL-2.0-or-later
#
# Python packages bundled with Blender (`site-packages`), the same as in official releases:
# pure Python packages (requests, cattrs ...) and extension modules cross-compiled for Android
# (NumPy, zstandard).
#
# Extension modules are shared libraries loaded from the extracted data (like CPython's own
# Android builds), they depend on `libblender.so` which provides the Python API
# (see `cross_python.cmake`).

set(PYTHON_TARGET_SITE_PACKAGES ${LIBDIR}/lib/python${PYTHON_SHORT_VERSION}/site-packages)
set(CROSS_PYTHON ${CROSS_PYTHON_DIR}/bin/python3)

# ---------------------------------------------------------------------------
# Tools on the build machine (pip, Cython)

ExternalProject_Add(external_python_host_tools
  DOWNLOAD_COMMAND ""
  CONFIGURE_COMMAND ""
  BUILD_COMMAND ""
  PREFIX ${CMAKE_BINARY_DIR}/python_host_tools
  INSTALL_COMMAND ${HOST_PYTHON_EXECUTABLE} -m ensurepip --upgrade
    COMMAND ${HOST_PYTHON_EXECUTABLE} -m pip install --no-cache-dir
    cython==${CYTHON_VERSION}
    meson==${MESON_VERSION}
    setuptools==${SETUPTOOLS_VERSION}
    wheel
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_python_host_tools external_python_host)

# ---------------------------------------------------------------------------
# Pure Python packages

ExternalProject_Add(external_python_site_packages
  DOWNLOAD_COMMAND ""
  CONFIGURE_COMMAND ""
  BUILD_COMMAND ""
  PREFIX ${CMAKE_BINARY_DIR}/site_packages
  # Platform independent wheels only (`--platform any`): never binaries for the build machine.
  INSTALL_COMMAND ${HOST_PYTHON_EXECUTABLE} -m pip install --no-cache-dir --no-deps --no-compile
    --upgrade --target ${PYTHON_TARGET_SITE_PACKAGES}
    --platform any --implementation py --python-version ${PYTHON_SHORT_VERSION}
    --only-binary :all:
    idna==${IDNA_VERSION}
    charset-normalizer==${CHARSET_NORMALIZER_VERSION}
    urllib3==${URLLIB3_VERSION}
    certifi==${CERTIFI_VERSION}
    requests==${REQUESTS_VERSION}
    autopep8==${AUTOPEP8_VERSION}
    pycodestyle==${PYCODESTYLE_VERSION}
    docutils==${DOCUTILS_VERSION}
    attrs==${ATTRS_VERSION}
    cattrs==${CATTRS_VERSION}
    fastjsonschema==${FASTJSONSCHEMA_VERSION}
    typing-extensions==${TYPING_EXTENSIONS_VERSION}
    tomli-w==${TOMLI_W_VERSION}
    # Python packages installed after the application (`android_components` add-on).
    pip==${PYTHON_PIP_VERSION}
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_python_site_packages external_python external_python_host_tools)

# ---------------------------------------------------------------------------
# Cross Python

ExternalProject_Add(external_cross_python
  DOWNLOAD_COMMAND ""
  CONFIGURE_COMMAND ""
  BUILD_COMMAND ""
  PREFIX ${CMAKE_BINARY_DIR}/cross_python_build
  INSTALL_COMMAND ${CMAKE_COMMAND}
    -DCROSS_PYTHON_DIR=${CROSS_PYTHON_DIR}
    -DLIBDIR=${LIBDIR}
    -DHOST_PYTHON=${HOST_PYTHON_EXECUTABLE}
    -DPYTHON_SHORT_VERSION=${PYTHON_SHORT_VERSION}
    -DCC=${ANDROID_CC}
    -DANDROID_API=${ANDROID_API}
    -P ${CMAKE_CURRENT_LIST_DIR}/cross_python.cmake
)
add_dependencies(external_cross_python external_python external_python_host)

# Meson cross file for extension modules.
set(_meson_c_args "${DEPS_C_FLAGS_LIST}")
list(TRANSFORM _meson_c_args PREPEND "'")
list(TRANSFORM _meson_c_args APPEND "'")
list(JOIN _meson_c_args ", " _meson_c_args)
set(MESON_CROSS_FILE ${CROSS_PYTHON_DIR}/meson-android.ini)
file(WRITE ${MESON_CROSS_FILE}
  "[binaries]\n"
  "c = '${ANDROID_CC}'\n"
  "cpp = '${ANDROID_CXX}'\n"
  "ar = '${ANDROID_TOOLCHAIN_DIR}/bin/llvm-ar'\n"
  "strip = '${ANDROID_TOOLCHAIN_DIR}/bin/llvm-strip'\n"
  "python = '${CROSS_PYTHON}'\n"
  "pkg-config = 'false'\n"
  "\n"
  "[built-in options]\n"
  "c_args = [${_meson_c_args}]\n"
  "cpp_args = [${_meson_c_args}]\n"
  # Each module has its own copy of the C++ runtime (like `libblender.so`).
  "c_link_args = ['-L${CROSS_PYTHON_DIR}/lib', '-Wl,--no-undefined', '-lm']\n"
  "cpp_link_args = ['-L${CROSS_PYTHON_DIR}/lib', '-Wl,--no-undefined', '-lm', '-static-libstdc++']\n"
  "\n"
  "[properties]\n"
  "needs_exe_wrapper = true\n"
  # 128-bit IEEE quad precision (AArch64), can't be detected when cross-compiling.
  "longdouble_format = 'IEEE_QUAD_LE'\n"
  "\n"
  "[host_machine]\n"
  "system = 'android'\n"
  "kernel = 'linux'\n"
  "cpu_family = 'aarch64'\n"
  "cpu = 'aarch64'\n"
  "endian = 'little'\n"
)

# ---------------------------------------------------------------------------
# NumPy

# Cython is looked up as a tool of the build machine.
set(HOST_TOOLS_ENV ${CMAKE_COMMAND} -E env PATH=${HOST_PYTHON_PREFIX}/bin:$ENV{PATH})

dep_download_args(NUMPY _dl)
ExternalProject_Add(external_numpy
  ${_dl}
  PREFIX ${CMAKE_BINARY_DIR}/numpy
  # NumPy's fork of Meson (SIMD support).
  CONFIGURE_COMMAND ${HOST_TOOLS_ENV}
    ${HOST_PYTHON_EXECUTABLE} <SOURCE_DIR>/vendored-meson/meson/meson.py setup
    --cross-file ${MESON_CROSS_FILE}
    --buildtype release
    --prefix <INSTALL_DIR>
    -Dpython.platlibdir=<INSTALL_DIR>/site-packages
    -Dpython.purelibdir=<INSTALL_DIR>/site-packages
    # No BLAS/LAPACK library: NumPy's bundled `lapack_lite` is used.
    -Dblas=none
    -Dlapack=none
    -Dallow-noblas=true
    <BINARY_DIR> <SOURCE_DIR>
  BUILD_COMMAND ${HOST_TOOLS_ENV} ninja -C <BINARY_DIR> -j${DEPS_JOBS}
  # Without the test-suite.
  INSTALL_COMMAND ${HOST_PYTHON_EXECUTABLE} <SOURCE_DIR>/vendored-meson/meson/meson.py install
      -C <BINARY_DIR> --no-rebuild --tags runtime,python-runtime,devel
    COMMAND ${CMAKE_COMMAND} -E rm -rf ${PYTHON_TARGET_SITE_PACKAGES}/numpy
    COMMAND ${CMAKE_COMMAND} -E copy_directory
      <INSTALL_DIR>/site-packages/numpy ${PYTHON_TARGET_SITE_PACKAGES}/numpy
  LOG_CONFIGURE ON
  LOG_BUILD ON
  LOG_INSTALL ON
  LOG_OUTPUT_ON_FAILURE ON
)
add_dependencies(external_numpy external_cross_python external_python_host_tools)

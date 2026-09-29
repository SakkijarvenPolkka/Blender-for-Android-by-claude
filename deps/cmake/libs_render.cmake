# SPDX-License-Identifier: GPL-2.0-or-later
#
# Cycles on the CPU: ray tracing (Embree), path guiding (OpenPGL) and denoising (Open Image
# Denoise). All of them support ARM64 with NEON.

add_cmake_dep(embree EMBREE
  DEPENDS external_tbb
  PATCHES
    ${BLENDER_PATCH_DIR}/embree.diff
  CMAKE_ARGS
    -DEMBREE_ISPC_SUPPORT=OFF
    -DEMBREE_TUTORIALS=OFF
    -DEMBREE_STATIC_LIB=ON
    -DEMBREE_RAY_MASK=ON
    -DEMBREE_FILTER_FUNCTION=ON
    -DEMBREE_BACKFACE_CULLING=OFF
    -DEMBREE_BACKFACE_CULLING_CURVES=ON
    -DEMBREE_BACKFACE_CULLING_SPHERES=ON
    -DEMBREE_TASKING_SYSTEM=TBB
    -DEMBREE_TBB_ROOT=${LIBDIR}
    -DTBB_ROOT=${LIBDIR}
    -DEMBREE_MAX_ISA=NEON
)

add_cmake_dep(openpgl OPENPGL
  DEPENDS external_tbb
  CMAKE_ARGS
    -DOPENPGL_BUILD_STATIC=ON
    -DOPENPGL_TBB_ROOT=${LIBDIR}
    -DTBB_ROOT=${LIBDIR}
)

# ---------------------------------------------------------------------------
# Open Image Denoise
#
# Its CPU kernels are compiled with ISPC, a compiler for the build machine: the release binary
# of the version Blender builds from source (it targets Android on ARM64).

set(ISPC_HOST_VERSION ${ISPC_VERSION})
set(ISPC_HOST_FILE ispc-${ISPC_HOST_VERSION}-linux.tar.gz)
set(ISPC_HOST_DIR ${CMAKE_BINARY_DIR}/ispc)
# In the build directory (not kept), extracted from the downloaded archive when needed.
list(APPEND DEPS_ALWAYS_BUILD external_ispc)
ExternalProject_Add(external_ispc
  URL https://github.com/ispc/ispc/releases/download/${ISPC_HOST_VERSION}/${ISPC_HOST_FILE}
  URL_HASH SHA256=63e7d61037849fa1ed644f0398d21740ee9f880b9bf81f017c65eebe1d42c02b
  DOWNLOAD_NAME ${ISPC_HOST_FILE}
  DOWNLOAD_DIR ${DOWNLOAD_DIR}
  DOWNLOAD_NO_EXTRACT ON
  PREFIX ${ISPC_HOST_DIR}
  CONFIGURE_COMMAND ""
  BUILD_COMMAND ""
  INSTALL_COMMAND ${CMAKE_COMMAND} -E chdir ${ISPC_HOST_DIR}
    tar xzf ${DOWNLOAD_DIR}/${ISPC_HOST_FILE} --strip-components=1 --wildcards "*/bin/ispc"
)

add_cmake_dep(openimagedenoise OIDN
  DEPENDS external_tbb external_ispc external_python_host
  PATCHES
    ${ANDROID_PATCH_DIR}/oidn_android.diff
  CMAKE_ARGS
    -DOIDN_APPS=OFF
    -DOIDN_STATIC_LIB=ON
    -DOIDN_DEVICE_CPU=ON
    -DOIDN_FILTER_RTLIGHTMAP=OFF
    -DTBB_ROOT=${LIBDIR}
    -DISPC_EXECUTABLE=${ISPC_HOST_DIR}/bin/ispc
    -DISPC_TARGET_OS=--target-os=android
    -DPython_EXECUTABLE=${HOST_PYTHON_EXECUTABLE}
)

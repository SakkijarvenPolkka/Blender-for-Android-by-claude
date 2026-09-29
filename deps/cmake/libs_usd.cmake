# SPDX-License-Identifier: GPL-2.0-or-later
#
# Universal Scene Description, as a static monolithic library (`usd_m`) linked into
# `libblender.so` with all its members (USD registers types & plug-ins from static initializers).
#
# Blender uses USD's Python support (hooks, `pxr` wrappers) through the Python it embeds: the
# libraries are built with Python support but without Python modules (each would contain a
# copy of the static library), see `deps/patches/usd_android.diff`.

string(REPLACE "." "_" USD_NAMESPACE "pxrBlender_v${USD_VERSION}")

add_cmake_dep(usd USD
  DEPENDS
    external_tbb external_opensubdiv external_materialx external_imath external_python
    external_python_host
  PATCHES
    ${BLENDER_PATCH_DIR}/usd.diff
    ${BLENDER_PATCH_DIR}/usd_noboost.diff
    ${BLENDER_PATCH_DIR}/usd_a609a89a750f1c70f5bfd61bb418d5a09eaa6585.diff
    ${BLENDER_PATCH_DIR}/usd_5744a98789c934e8810058b0f21d22f344df28b0.diff
    ${ANDROID_PATCH_DIR}/usd_android.diff
  CMAKE_ARGS
    -DPXR_SET_INTERNAL_NAMESPACE=${USD_NAMESPACE}
    -DPXR_BUILD_MONOLITHIC=ON
    -DPXR_ENABLE_PYTHON_SUPPORT=ON
    -DPXR_BUILD_PYTHON_MODULES=OFF
    # Python symbols come from `libblender.so`.
    -DPXR_PY_UNDEFINED_DYNAMIC_LOOKUP=ON
    -DPython3_EXECUTABLE=${HOST_PYTHON_EXECUTABLE}
    -DPython3_INCLUDE_DIR=${LIBDIR}/include/python${PYTHON_SHORT_VERSION}
    -DPython3_LIBRARY=${LIBDIR}/lib/libpython${PYTHON_SHORT_VERSION}.a
    -DPXR_BUILD_IMAGING=ON
    -DPXR_BUILD_USD_IMAGING=ON
    -DPXR_ENABLE_GL_SUPPORT=OFF
    -DPXR_ENABLE_VULKAN_SUPPORT=OFF
    -DPXR_ENABLE_METAL_SUPPORT=OFF
    -DPXR_ENABLE_MATERIALX_SUPPORT=ON
    -DPXR_ENABLE_OPENVDB_SUPPORT=OFF
    -DPXR_ENABLE_OSL_SUPPORT=OFF
    -DPXR_ENABLE_PTEX_SUPPORT=OFF
    -DPXR_ENABLE_HDF5_SUPPORT=OFF
    -DPXR_BUILD_OPENIMAGEIO_PLUGIN=OFF
    -DPXR_BUILD_OPENCOLORIO_PLUGIN=OFF
    -DPXR_BUILD_EMBREE_PLUGIN=OFF
    -DPXR_BUILD_ALEMBIC_PLUGIN=OFF
    -DPXR_BUILD_DRACO_PLUGIN=OFF
    -DPXR_BUILD_PRMAN_PLUGIN=OFF
    -DPXR_BUILD_USDVIEW=OFF
    -DPXR_BUILD_USD_TOOLS=OFF
    -DPXR_BUILD_TESTS=OFF
    -DPXR_BUILD_EXAMPLES=OFF
    -DPXR_BUILD_TUTORIALS=OFF
    -DPXR_BUILD_DOCUMENTATION=OFF
    -DPXR_ENABLE_PRECOMPILED_HEADERS=OFF
    -DOPENSUBDIV_ROOT_DIR=${LIBDIR}
    -DMaterialX_ROOT=${LIBDIR}
    -DImath_ROOT=${LIBDIR}
    -DTBB_ROOT=${LIBDIR}
)

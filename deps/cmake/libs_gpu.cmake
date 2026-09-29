# SPDX-License-Identifier: GPL-2.0-or-later
#
# Vulkan headers, shader compiler (shaderc) and SDL3 (windowing, input, audio).
#
# The Vulkan loader itself is provided by Android (`libvulkan.so` in the NDK
# sysroot), only the newer headers Blender expects are installed here.

add_cmake_dep(vulkan_headers VULKAN_HEADERS
  CMAKE_ARGS
    -DVULKAN_HEADERS_ENABLE_MODULE=OFF
    -DVULKAN_HEADERS_ENABLE_TESTS=OFF
)

# shaderc builds SPIRV-Tools, SPIRV-Headers and glslang from their source
# directories as part of its own build, only download & extract those here.
foreach(_src SPIRV_HEADERS SPIRV_TOOLS SHADERC_GLSLANG)
  string(TOLOWER ${_src} _name)
  dep_download_args(${_src} _dl)
  ExternalProject_Add(external_${_name}
    ${_dl}
    PREFIX ${CMAKE_BINARY_DIR}/${_name}
    CONFIGURE_COMMAND ""
    BUILD_COMMAND ""
    INSTALL_COMMAND ""
  )
endforeach()

add_cmake_dep(shaderc SHADERC
  DEPENDS external_spirv_headers external_spirv_tools external_shaderc_glslang
  CMAKE_ARGS
    -DSHADERC_SKIP_TESTS=ON
    -DSHADERC_SKIP_EXAMPLES=ON
    -DSHADERC_SKIP_COPYRIGHT_CHECK=ON
    -DSHADERC_ENABLE_SHARED_CRT=ON
    -DSHADERC_SPIRV_TOOLS_DIR=${CMAKE_BINARY_DIR}/spirv_tools/src/external_spirv_tools
    -DSHADERC_SPIRV_HEADERS_DIR=${CMAKE_BINARY_DIR}/spirv_headers/src/external_spirv_headers
    -DSHADERC_GLSLANG_DIR=${CMAKE_BINARY_DIR}/shaderc_glslang/src/external_shaderc_glslang
    -DSPIRV_SKIP_EXECUTABLES=ON
    -DSPIRV_SKIP_TESTS=ON
    -DSPIRV_WERROR=OFF
    -DSPIRV_TOOLS_BUILD_STATIC=ON
    -DENABLE_GLSLANG_BINARIES=OFF
    -DENABLE_CTEST=OFF
    -DENABLE_OPT=ON
    -DGLSLANG_TESTS=OFF
    -DPython3_EXECUTABLE=${HOST_PYTHON_EXECUTABLE}
  POST_INSTALL COMMAND sh -c "rm -f ${LIBDIR}/lib/libshaderc_shared.so* ${LIBDIR}/lib/libSPIRV-Tools-shared.so"
)

# SDL3: Android platform integration (activity life-cycle, surfaces, input,
# IME, clipboard and audio). Built statically into `libblender.so`, the Java
# half (`org.libsdl.app`) is copied into the Android app project.
add_cmake_dep(sdl SDL
  CMAKE_ARGS
    -DSDL_SHARED=OFF
    -DSDL_STATIC=ON
    -DSDL_STATIC_PIC=ON
    -DSDL_TESTS=OFF
    -DSDL_TEST_LIBRARY=OFF
    -DSDL_EXAMPLES=OFF
    -DSDL_INSTALL_DOCS=OFF
    -DSDL_VULKAN=ON
    -DSDL_OPENGLES=ON
    -DSDL_OPENGL=OFF
    -DSDL_HIDAPI=ON
    -DSDL_ANDROID_JAR=OFF
  POST_INSTALL
    COMMAND ${CMAKE_COMMAND} -E remove_directory ${LIBDIR}/share/sdl3-java
    COMMAND ${CMAKE_COMMAND} -E copy_directory
      <SOURCE_DIR>/android-project/app/src/main/java
      ${LIBDIR}/share/sdl3-java
)

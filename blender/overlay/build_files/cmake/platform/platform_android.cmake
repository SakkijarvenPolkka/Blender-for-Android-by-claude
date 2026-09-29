# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later

# Libraries configuration for Android (arm64-v8a).
#
# All dependencies are cross-compiled into a single prefix (`LIBDIR`) by the
# dependency superbuild of the Android port (`deps/`), and linked statically
# into `libblender.so`, which is loaded by the Java activity.

if(NOT DEFINED LIBDIR OR NOT EXISTS "${LIBDIR}/include")
  message(FATAL_ERROR
    "Android builds need the pre-compiled dependencies, "
    "set LIBDIR to the install prefix of the dependency build (got \"${LIBDIR}\")."
  )
endif()

if(FIRST_RUN)
  message(STATUS "Using pre-compiled Android LIBDIR: ${LIBDIR}")
endif()

set(WITH_LIBS_PRECOMPILED ON)
set(WITH_STATIC_LIBS ON)
set(WITH_CPU_CHECK OFF)
set(WITH_BINRELOC OFF)

# Search our libraries first, then the NDK sysroot (for system libraries such
# as `libvulkan.so`, `liblog.so` & `libandroid.so`).
list(PREPEND CMAKE_FIND_ROOT_PATH ${LIBDIR})
set(CMAKE_PREFIX_PATH ${LIBDIR})

foreach(_root
    OPENEXR IMATH OPENJPH OPENIMAGEIO OPENCOLORIO JPEG PNG ZLIB ZSTD EPOXY FMT FREETYPE BROTLI
    PYTHON OPENJPEG SDL FFTW3 WEBP PUGIXML TBB GMP POTRACE OPENSUBDIV VULKAN SHADERC
    SSE2NEON EIGEN3 MANIFOLD FFMPEG LIBSNDFILE HARFBUZZ FRIBIDI HARU OPENVDB NANOVDB BLOSC
    ALEMBIC EMBREE OPENIMAGEDENOISE USD RUBBERBAND)
  set(${_root}_ROOT_DIR ${LIBDIR})
endforeach()
unset(_root)
foreach(_package
    OpenEXR Imath openjph OpenImageIO OpenColorIO fmt Eigen3 TBB manifold absl Ceres draco
    meshoptimizer openpgl MaterialX)
  set(${_package}_ROOT ${LIBDIR})
endforeach()
unset(_package)

macro(find_package_wrapper)
  find_package_static(${ARGV})
endmacro()

# ----------------------------------------------------------------------------
# Libraries

find_package_wrapper(JPEG REQUIRED)
find_package_wrapper(PNG REQUIRED)
find_package_wrapper(ZLIB REQUIRED)
find_package_wrapper(Zstd REQUIRED)
find_package_wrapper(fmt REQUIRED)
mark_as_advanced(fmt_DIR)

if(WITH_OPENGL_BACKEND)
  message(FATAL_ERROR "The OpenGL backend is not supported on Android, use Vulkan")
endif()
# Epoxy (OpenGL function loader) is not used without the OpenGL backend.
set(EPOXY_INCLUDE_DIRS "")
set(EPOXY_LIBRARIES "")

if(WITH_VULKAN_BACKEND)
  # Headers from LIBDIR (newer than the NDK ones), loader from the NDK sysroot.
  find_path(VULKAN_INCLUDE_DIR NAMES vulkan/vulkan.h HINTS ${LIBDIR}/include NO_DEFAULT_PATH)
  find_library(VULKAN_LIBRARY NAMES vulkan)
  if(NOT VULKAN_INCLUDE_DIR OR NOT VULKAN_LIBRARY)
    message(FATAL_ERROR "Vulkan headers or loader not found")
  endif()
  set(VULKAN_INCLUDE_DIRS ${VULKAN_INCLUDE_DIR})
  set(VULKAN_LIBRARIES ${VULKAN_LIBRARY})
  set(VULKAN_FOUND TRUE)
  find_package_wrapper(ShaderC REQUIRED)
endif()

find_package_wrapper(Freetype REQUIRED)
find_package_wrapper(Brotli REQUIRED)

if(WITH_HARFBUZZ)
  find_package(Harfbuzz)
endif()
if(WITH_FRIBIDI)
  find_package(Fribidi)
endif()

if(WITH_PYTHON)
  # The build machine can't run the Android Python, use the host Python of the
  # same version that was built together with the dependencies.
  if(NOT PYTHON_EXECUTABLE)
    message(FATAL_ERROR "PYTHON_EXECUTABLE must point to a host Python ${PYTHON_VERSION}")
  endif()
  set(PYTHON_EXECUTABLE ${PYTHON_EXECUTABLE} CACHE FILEPATH "" FORCE)
  find_package(PythonLibsUnix REQUIRED)

  # The standard library extension modules are linked into `libpython3.x.a`
  # (`MODULE_BUILDTYPE=static`), add the libraries they depend on.
  foreach(_lib mpdec Hacl_Hash_SHA2 ssl crypto ffi sqlite3 lzma bz2 expat)
    find_library_static(PYTHON_DEP_${_lib}_LIBRARY NAMES ${_lib} HINTS ${LIBDIR}/lib REQUIRED)
    mark_as_advanced(PYTHON_DEP_${_lib}_LIBRARY)
    list(APPEND PYTHON_LIBRARIES ${PYTHON_DEP_${_lib}_LIBRARY})
  endforeach()
  unset(_lib)
  list(APPEND PYTHON_LIBRARIES ${ZLIB_LIBRARIES} log)
  # `PYTHON_LINKFLAGS` is meant for executables (`-export-dynamic`).
  set(PYTHON_LINKFLAGS "")
else()
  find_program(PYTHON_EXECUTABLE "python3")
endif()

find_package_wrapper(OpenEXR REQUIRED)

if(WITH_IMAGE_OPENJPEG)
  find_package_wrapper(OpenJPEG)
  set_and_warn_library_found("OpenJPEG" OPENJPEG_FOUND WITH_IMAGE_OPENJPEG)
endif()

if(WITH_SDL)
  find_package_wrapper(SDL3 REQUIRED)
endif()

if(WITH_FFTW3)
  find_package_wrapper(Fftw3)
  set_and_warn_library_found("fftw3" FFTW3_FOUND WITH_FFTW3)
endif()

# Codecs
if(WITH_CODEC_SNDFILE)
  find_package_wrapper(SndFile)
  set_and_warn_library_found("libsndfile" SNDFILE_FOUND WITH_CODEC_SNDFILE)
  if(SNDFILE_FOUND)
    # Static library, with the codec libraries it uses.
    foreach(_lib FLAC vorbisenc vorbis ogg opus mp3lame)
      find_library_static(SNDFILE_${_lib}_LIBRARY NAMES ${_lib} HINTS ${LIBDIR}/lib REQUIRED)
      mark_as_advanced(SNDFILE_${_lib}_LIBRARY)
      list(APPEND LIBSNDFILE_LIBRARIES ${SNDFILE_${_lib}_LIBRARY})
    endforeach()
    unset(_lib)
  endif()
endif()

if(WITH_CODEC_FFMPEG)
  set(FFMPEG_ROOT_DIR ${LIBDIR})
  # Also the static codec libraries, in link order.
  set(FFMPEG_FIND_COMPONENTS
    avformat avdevice avfilter avcodec avutil swresample swscale
    x264 x265 vpx aom opus theoraenc theoradec vorbisenc vorbis ogg mp3lame
  )
  find_package(FFmpeg)
  set_and_warn_library_found("FFmpeg" FFMPEG_FOUND WITH_CODEC_FFMPEG)
endif()

test_neon_support()
if(SUPPORTS_NEON_BUILD)
  find_package_wrapper(sse2neon REQUIRED)
endif()

if(WITH_PUGIXML)
  find_package_wrapper(PugiXML)
  set_and_warn_library_found("PugiXML" PUGIXML_FOUND WITH_PUGIXML)
endif()

if(WITH_IMAGE_WEBP)
  find_package_wrapper(WebP)
  set_and_warn_library_found("WebP" WEBP_FOUND WITH_IMAGE_WEBP)
endif()

# OpenColorIO is a static library, its configuration looks for its dependencies.
set(minizip-ng_INCLUDE_DIR ${LIBDIR}/include/minizip-ng/minizip CACHE PATH "")
set(minizip-ng_LIBRARY ${LIBDIR}/lib/libminizip.a CACHE FILEPATH "")
mark_as_advanced(minizip-ng_INCLUDE_DIR minizip-ng_LIBRARY)

# OpenImageIO is a static library, its exported targets link to the targets of its
# dependencies, make sure those exist.
find_package(WebP CONFIG REQUIRED)
find_package(TIFF REQUIRED)
find_package(pugixml CONFIG REQUIRED)
find_package(openjph CONFIG REQUIRED)
# Some libraries are referenced by name only (e.g. `openjp2`).
link_directories(${LIBDIR}/lib)

find_package_wrapper(OpenImageIO REQUIRED)
find_package_wrapper(OpenColorIO 2.0.0 REQUIRED)

if(WITH_OPENSUBDIV)
  # OpenSubdiv is built without GPU back-ends, `osdGPU` only contains the GLSL
  # patch shader source (Blender evaluates on the GPU with its own shaders).
  find_package_wrapper(OpenSubdiv)
  set(OPENSUBDIV_LIBPATH "")
  set_and_warn_library_found("OpenSubdiv" OPENSUBDIV_FOUND WITH_OPENSUBDIV)
endif()

if(WITH_TBB OR WITH_TBB_MALLOC_PROXY)
  find_package_wrapper(TBB)
  if(TBB_FOUND)
    if(WITH_TBB)
      get_target_property(TBB_LIBRARIES TBB::tbb LOCATION)
      get_target_property(TBB_INCLUDE_DIRS TBB::tbb INTERFACE_INCLUDE_DIRECTORIES)
    endif()
    if(WITH_TBB_MALLOC_PROXY)
      get_target_property(TBB_MALLOC_PROXY_LIBRARIES TBB::tbbmalloc_proxy LOCATION)
      get_target_property(TBB_MALLOC_LIBRARIES TBB::tbbmalloc LOCATION)
    endif()
  endif()
  if(WITH_TBB)
    set_and_warn_library_found("TBB" TBB_FOUND WITH_TBB)
  endif()
  if(WITH_TBB_MALLOC_PROXY)
    set_and_warn_library_found("TBB" TBB_FOUND WITH_TBB_MALLOC_PROXY)
  endif()
  mark_as_advanced(TBB_DIR)
endif()

if(WITH_GMP)
  find_package_wrapper(GMP)
  set_and_warn_library_found("GMP" GMP_FOUND WITH_GMP)
endif()

if(WITH_POTRACE)
  find_package_wrapper(Potrace)
  set_and_warn_library_found("Potrace" POTRACE_FOUND WITH_POTRACE)
endif()

if(WITH_MANIFOLD)
  find_package(manifold REQUIRED)
  mark_as_advanced(manifold_DIR)
endif()

find_package_wrapper(Eigen3 REQUIRED)
mark_as_advanced(Eigen3_DIR)

if(WITH_LIBMV)
  find_package_wrapper(Ceres REQUIRED)
  mark_as_advanced(Ceres_DIR absl_DIR)
endif()

if(WITH_HARU)
  find_package_wrapper(Haru)
  set_and_warn_library_found("Haru" HARU_FOUND WITH_HARU)
endif()

# glTF mesh compression, linked into bridge libraries loaded by the glTF add-on.
if(WITH_DRACO)
  find_package_wrapper(draco)
  if(TARGET draco::draco)
    set(DRACO_FOUND TRUE)
  endif()
  set_and_warn_library_found("Draco" DRACO_FOUND WITH_DRACO)
  mark_as_advanced(draco_DIR)
endif()
if(WITH_MESHOPTIMIZER)
  find_package_wrapper(meshoptimizer)
  if(TARGET meshoptimizer::meshoptimizer)
    set(MESHOPTIMIZER_FOUND TRUE)
  endif()
  set_and_warn_library_found("meshoptimizer" MESHOPTIMIZER_FOUND WITH_MESHOPTIMIZER)
  mark_as_advanced(meshoptimizer_DIR)
endif()

if(WITH_RUBBERBAND)
  find_package_wrapper(Rubberband)
  set_and_warn_library_found("Rubberband" RUBBERBAND_FOUND WITH_RUBBERBAND)
endif()

# Volumes.
if(WITH_OPENVDB)
  find_package(OpenVDB)
  set_and_warn_library_found("OpenVDB" OPENVDB_FOUND WITH_OPENVDB)
  if(OPENVDB_FOUND)
    set(OPENVDB_DEFINITIONS "")
    # Static library, with its dependencies.
    find_package_wrapper(Blosc REQUIRED)
    list(APPEND OPENVDB_LIBRARIES ${BLOSC_LIBRARIES} ${ZLIB_LIBRARIES})
  endif()
endif()

if(WITH_NANOVDB)
  find_package_wrapper(NanoVDB)
  set_and_warn_library_found("NanoVDB" NANOVDB_FOUND WITH_NANOVDB)
endif()

if(WITH_ALEMBIC)
  find_package_wrapper(Alembic)
  set_and_warn_library_found("Alembic" ALEMBIC_FOUND WITH_ALEMBIC)
endif()

if(WITH_MATERIALX)
  find_package_wrapper(MaterialX)
  set_and_warn_library_found("MaterialX" MaterialX_FOUND WITH_MATERIALX)
  mark_as_advanced(MaterialX_DIR)
endif()

# Universal Scene Description: a static library with Python support (through the embedded
# Python), linked with all its members (see `source/creator`).
if(WITH_USD)
  find_package_wrapper(USD)
  set_and_warn_library_found("USD" USD_FOUND WITH_USD)
  if(USD_FOUND)
    if(WITH_MATERIALX AND MaterialX_FOUND)
      list(APPEND USD_LIBRARIES MaterialXGenShader MaterialXFormat MaterialXCore)
    endif()
    list(APPEND USD_LIBRARIES ${OPENSUBDIV_LIBRARIES} ${TBB_LIBRARIES})
  endif()
endif()

# Cycles on the CPU (NEON).
if(WITH_CYCLES AND WITH_CYCLES_EMBREE)
  find_package(Embree 4.0.0 REQUIRED)
endif()

if(WITH_CYCLES AND WITH_CYCLES_PATH_GUIDING)
  find_package_wrapper(openpgl)
  mark_as_advanced(openpgl_DIR)
  if(openpgl_FOUND)
    get_target_property(OPENPGL_LIBRARIES openpgl::openpgl LOCATION)
    get_target_property(OPENPGL_INCLUDE_DIR openpgl::openpgl INTERFACE_INCLUDE_DIRECTORIES)
  else()
    set(WITH_CYCLES_PATH_GUIDING OFF)
    message(STATUS "OpenPGL not found, disabling WITH_CYCLES_PATH_GUIDING")
  endif()
endif()

if(WITH_OPENIMAGEDENOISE)
  find_package_wrapper(OpenImageDenoise)
  set_and_warn_library_found("OpenImageDenoise" OPENIMAGEDENOISE_FOUND WITH_OPENIMAGEDENOISE)
  if(OPENIMAGEDENOISE_FOUND)
    # Static library with the CPU device only: the modules it's made of.
    foreach(_lib OpenImageDenoise_core OpenImageDenoise_device_cpu)
      find_library_static(OIDN_${_lib}_LIBRARY NAMES ${_lib} HINTS ${LIBDIR}/lib REQUIRED)
      mark_as_advanced(OIDN_${_lib}_LIBRARY)
      list(APPEND OPENIMAGEDENOISE_LIBRARIES ${OIDN_${_lib}_LIBRARY})
    endforeach()
    unset(_lib)
  endif()
endif()

# Open Shading Language, static with LLVM & Clang (linked through OSL's targets), see
# `deps/cmake/libs_osl.cmake` of the Android port. `oslc` is an Android executable too, it's run
# through `CMAKE_CROSSCOMPILING_EMULATOR` to compile Cycles' shaders.
if(WITH_CYCLES AND WITH_CYCLES_OSL)
  set(OSL_ROOT ${LIBDIR})
  # Static OSL links pugixml as `pugixml::pugixml` (the target of pugixml's configuration is
  # `pugixml`).
  if(NOT TARGET pugixml::pugixml)
    if(NOT TARGET pugixml)
      find_package(pugixml CONFIG REQUIRED)
    endif()
    add_library(pugixml::pugixml INTERFACE IMPORTED)
    set_target_properties(pugixml::pugixml PROPERTIES INTERFACE_LINK_LIBRARIES pugixml)
  endif()
  find_package_wrapper(OSL 1.13.4)
  set_and_warn_library_found("OSL" OSL_FOUND WITH_CYCLES_OSL)
  mark_as_advanced(OSL_DIR)
endif()

# Features that are not available (yet) on Android.
foreach(_option
    WITH_OPENAL WITH_JACK WITH_PULSEAUDIO WITH_PIPEWIRE
    WITH_INPUT_NDOF WITH_HYDRA
    WITH_XR_OPENXR WITH_TRACY
    WITH_GHOST_X11 WITH_GHOST_WAYLAND WITH_SYSTEM_AUDASPACE)
  if(${_option})
    message(STATUS "${_option} is not supported on Android, disabling")
    set(${_option} OFF)
  endif()
endforeach()
unset(_option)

# ----------------------------------------------------------------------------
# Build and Link Flags

find_package(Threads REQUIRED)
if(CMAKE_THREAD_LIBS_INIT)
  list(APPEND PLATFORM_LINKLIBS ${CMAKE_THREAD_LIBS_INIT})
  set(PTHREADS_LIBRARIES ${CMAKE_THREAD_LIBS_INIT})
endif()
# NOTE: `android` & `log` are only linked into `libblender.so`, see `source/creator`.
list(APPEND PLATFORM_LINKLIBS m dl)

# Build-time tools (`makesdna`, `makesrna`, `datatoc`, `shader_tool`, `msgfmt`) run on the
# build machine through `CMAKE_CROSSCOMPILING_EMULATOR` (QEMU user-mode), static executables
# don't need Android's dynamic linker. `libblender.so` is the only other build target.
if(NOT CMAKE_CROSSCOMPILING_EMULATOR)
  message(FATAL_ERROR
    "CMAKE_CROSSCOMPILING_EMULATOR must be set to run build tools, "
    "e.g. -DCMAKE_CROSSCOMPILING_EMULATOR=/usr/bin/qemu-aarch64-static")
endif()
string(APPEND CMAKE_EXE_LINKER_FLAGS " -static")

add_definitions(-D_LARGEFILE_SOURCE -D_FILE_OFFSET_BITS=64 -D_LARGEFILE64_SOURCE)

set(PLATFORM_CFLAGS "-pipe -fPIC -funsigned-char -fno-strict-aliasing -ffp-contract=off")

# All symbols except the JNI entry points and `SDL_main` are hidden.
set(PLATFORM_SYMBOLS_MAP ${CMAKE_SOURCE_DIR}/source/creator/symbols_android.map)
set(PLATFORM_LINKFLAGS_SYMBOL_HIDING "-Wl,--version-script='${PLATFORM_SYMBOLS_MAP}'")
# `libblender.so` is loaded by the Java side, not as a dependency of the executable like on other
# platforms. As a global library (`DF_1_GLOBAL`) its symbols take precedence over the copies in
# libraries loaded later (Python extension modules): e.g. the RTTI of a template instantiated in
# a module is the one of `libblender.so`, as types are compared by address with libc++.
string(APPEND PLATFORM_LINKFLAGS_SYMBOL_HIDING " -Wl,-z,global")
# Calls within `libblender.so` to its exported functions stay direct (not through the PLT).
string(APPEND PLATFORM_LINKFLAGS_SYMBOL_HIDING " -Wl,-Bsymbolic-functions")

set(PLATFORM_ENV_BUILD "_DUMMY_ENV_VAR_=1")
set(PLATFORM_ENV_INSTALL "_DUMMY_ENV_VAR_=1")

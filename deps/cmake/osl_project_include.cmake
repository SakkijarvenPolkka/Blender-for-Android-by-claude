# SPDX-License-Identifier: GPL-2.0-or-later
#
# Included by OSL's `project()` (CMAKE_PROJECT_INCLUDE): imported targets of libraries the CMake
# configuration of the static OpenImageIO links without finding them. OSL's tools (`oslc`) are
# static executables linking all of OpenImageIO's dependencies.

set(_prefix ${OpenImageIO_ROOT})

find_package(OpenEXR CONFIG REQUIRED)

if(NOT TARGET WebP::sharpyuv)
  add_library(WebP::sharpyuv STATIC IMPORTED)
  set_target_properties(WebP::sharpyuv PROPERTIES IMPORTED_LOCATION ${_prefix}/lib/libsharpyuv.a)
endif()
foreach(_target webp webpdemux libwebpmux)
  string(REGEX REPLACE "^lib" "" _name ${_target})
  if(NOT TARGET WebP::${_target})
    add_library(WebP::${_target} STATIC IMPORTED)
    set_target_properties(WebP::${_target} PROPERTIES
      IMPORTED_LOCATION ${_prefix}/lib/lib${_name}.a
      INTERFACE_INCLUDE_DIRECTORIES ${_prefix}/include
    )
  endif()
endforeach()
set_property(TARGET WebP::webp APPEND PROPERTY INTERFACE_LINK_LIBRARIES WebP::sharpyuv)
set_property(TARGET WebP::webpdemux WebP::libwebpmux APPEND PROPERTY INTERFACE_LINK_LIBRARIES WebP::webp)

# Libraries linked by name (e.g. `openjp2`).
link_directories(${_prefix}/lib)
unset(_prefix)
unset(_target)
unset(_name)

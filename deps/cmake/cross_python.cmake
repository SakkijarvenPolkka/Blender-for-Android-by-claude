# SPDX-License-Identifier: GPL-2.0-or-later
#
# Prepares a "cross Python" to build Python extension modules for Android with the host Python:
#
#   <CROSS_PYTHON_DIR>/lib/libpython<ver>.so
#       Link-time stand-in for the Python library. Its SONAME is `libblender.so`: extension
#       modules get a dependency on Blender's library, which contains Python (linked statically).
#       Android doesn't use libraries loaded without RTLD_GLOBAL to resolve symbols of libraries
#       loaded later, extension modules have to depend on the library providing the Python API.
#   <CROSS_PYTHON_DIR>/sysconfig/_sysconfigdata_*.py
#       The Android Python's configuration, adjusted to link extension modules against the
#       stand-in library instead of the static library.
#   <CROSS_PYTHON_DIR>/bin/python3
#       Host Python reporting the Android configuration (`sysconfig`), used by build systems
#       (Meson, setuptools) to build extension modules for Android.
#
#   cmake -DCROSS_PYTHON_DIR=... -DLIBDIR=... -DHOST_PYTHON=... -DPYTHON_SHORT_VERSION=...
#         -DCC=... -DANDROID_API=... -P cross_python.cmake

set(_lib_dir ${CROSS_PYTHON_DIR}/lib)
set(_sysconfig_dir ${CROSS_PYTHON_DIR}/sysconfig)
set(_bin_dir ${CROSS_PYTHON_DIR}/bin)
file(MAKE_DIRECTORY ${_lib_dir} ${_sysconfig_dir} ${_bin_dir})

# Stand-in library.
execute_process(
  COMMAND ${CC} -shared -o ${_lib_dir}/libpython${PYTHON_SHORT_VERSION}.so
    -Wl,-soname,libblender.so
    -Wl,--whole-archive ${LIBDIR}/lib/libpython${PYTHON_SHORT_VERSION}.a -Wl,--no-whole-archive
    # Internal (hidden) symbols of the `_decimal` & `_sha2` modules.
    ${LIBDIR}/lib/libmpdec.a ${LIBDIR}/lib/libHacl_Hash_SHA2.a
    -lm -ldl -llog
  RESULT_VARIABLE _result
)
if(NOT _result EQUAL 0)
  message(FATAL_ERROR "Failed to create the Python stand-in library")
endif()

# Configuration.
file(GLOB _sysconfigdata ${LIBDIR}/lib/python${PYTHON_SHORT_VERSION}/_sysconfigdata_*.py)
list(LENGTH _sysconfigdata _count)
if(NOT _count EQUAL 1)
  message(FATAL_ERROR "Expected one _sysconfigdata file, found: ${_sysconfigdata}")
endif()
get_filename_component(_sysconfigdata_file ${_sysconfigdata} NAME)
get_filename_component(_sysconfigdata_name ${_sysconfigdata} NAME_WE)
file(READ ${_sysconfigdata} _content)
foreach(_pair
    "LIBDIR|${_lib_dir}"
    "LIBPL|${_lib_dir}"
    # No `python-3.x.pc`: Meson would link the static library.
    "LIBPC|"
    # Link extension modules against libpython (Meson checks `LIBPYTHON`,
    # setuptools `Py_ENABLE_SHARED`).
    "LIBPYTHON|-lpython${PYTHON_SHORT_VERSION}"
    "Py_ENABLE_SHARED|1"
)
  string(REPLACE "|" ";" _pair "${_pair}")
  list(GET _pair 0 _key)
  list(LENGTH _pair _len)
  if(_len GREATER 1)
    list(GET _pair 1 _value)
  else()
    set(_value "")
  endif()
  if(_key STREQUAL "Py_ENABLE_SHARED")
    string(REGEX REPLACE "'${_key}': [0-9]+" "'${_key}': ${_value}" _content "${_content}")
  else()
    string(REGEX REPLACE "'${_key}': '[^']*'" "'${_key}': '${_value}'" _content "${_content}")
  endif()
endforeach()
# Find the stand-in before the static library (linker flags).
string(REPLACE "-L${LIBDIR}/lib " "-L${_lib_dir} -L${LIBDIR}/lib " _content "${_content}")
file(WRITE ${_sysconfig_dir}/${_sysconfigdata_file} "${_content}")

# Host Python reporting the Android configuration.
file(WRITE ${_bin_dir}/python3
  "#!/bin/sh\n"
  "export _PYTHON_SYSCONFIGDATA_NAME=${_sysconfigdata_name}\n"
  "export _PYTHON_HOST_PLATFORM=android-${ANDROID_API}-arm64_v8a\n"
  "export PYTHONPATH=${_sysconfig_dir}\${PYTHONPATH:+:\$PYTHONPATH}\n"
  "exec ${HOST_PYTHON} \"\$@\"\n"
)
file(CHMOD ${_bin_dir}/python3 PERMISSIONS
  OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE)

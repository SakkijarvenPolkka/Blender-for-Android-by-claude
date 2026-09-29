# SPDX-License-Identifier: GPL-2.0-or-later
#
# On Android `ctypes` loads the Python library by name (`ctypes.pythonapi` uses the `LDLIBRARY`
# configuration variable). Python is linked statically into Blender's `libblender.so`, which
# exports the Python API: use it instead of the static library name (`libpython3.x.a`).
#
#   cmake -DPYTHON_LIBDIR=<prefix>/lib/python3.x -P fix_python_sysconfig.cmake

file(GLOB _files "${PYTHON_LIBDIR}/_sysconfigdata_*.py")
if(NOT _files)
  message(FATAL_ERROR "No _sysconfigdata in ${PYTHON_LIBDIR}")
endif()
foreach(_file ${_files})
  file(READ "${_file}" _content)
  string(REGEX REPLACE "'LDLIBRARY': '[^']*'" "'LDLIBRARY': 'libblender.so'" _content "${_content}")
  string(REGEX REPLACE "'INSTSONAME': '[^']*'" "'INSTSONAME': 'libblender.so'" _content "${_content}")
  file(WRITE "${_file}" "${_content}")
endforeach()

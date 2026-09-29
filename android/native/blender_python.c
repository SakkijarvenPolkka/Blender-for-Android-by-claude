/* SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Python interpreter executable for Blender on Android (`sys.executable`).
 *
 * Blender runs Python in sub-processes (extensions platform, background jobs). Android
 * applications can only execute files from their native library directory, so this program is
 * packaged there as `libblender_python.so`. It runs the Python interpreter linked into
 * `libblender.so` with the standard library & packages extracted with Blender's data. */

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv)
{
  PyConfig config;
  PyConfig_InitPythonConfig(&config);

  PyStatus status = PyConfig_SetBytesArgv(&config, argc, argv);
  if (PyStatus_Exception(status)) {
    goto fail;
  }

  /* Python's home, set in the configuration: the `PYTHONHOME` environment variable is ignored in
   * isolated mode (`-I`, used by Blender). `BLENDER_SYSTEM_RESOURCES` is set by the application,
   * see `BlenderPaths.java`. */
  const char *resources = getenv("BLENDER_SYSTEM_RESOURCES");
  if (resources != NULL && getenv("PYTHONHOME") == NULL) {
    char home[4096];
    snprintf(home, sizeof(home), "%s/python", resources);
    status = PyConfig_SetBytesString(&config, &config.home, home);
    if (PyStatus_Exception(status)) {
      goto fail;
    }
  }

  status = Py_InitializeFromConfig(&config);
  if (PyStatus_Exception(status)) {
    goto fail;
  }
  PyConfig_Clear(&config);
  return Py_RunMain();

fail:
  PyConfig_Clear(&config);
  if (PyStatus_IsExit(status)) {
    return status.exitcode;
  }
  Py_ExitStatusException(status);
}

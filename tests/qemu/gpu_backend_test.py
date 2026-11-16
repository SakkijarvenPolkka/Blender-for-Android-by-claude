# SPDX-License-Identifier: GPL-2.0-or-later
"""
GPU back-end preference of the Android build, run in background mode (see `run_blender.sh`):

  blender --background --factory-startup --python gpu_backend_test.py -- factory
  blender --background --python gpu_backend_test.py -- saved

Vulkan is the only GPU back-end of the build. A preference selecting another one (OpenGL: the
default of desktop Blender, stored by builds up to 24) makes Blender try that back-end first and
report "Failed to load using Vulkan, using OpenGL instead" at every start, the preferences then
show no back-end at all.

- factory: the factory preferences select Vulkan (also the RNA default, which comes from DNA through
  makesrna), OpenGL can't be selected. The preferences are saved for the next step.
- saved: started with saved preferences selecting OpenGL (changed by the caller with
  `userpref_gpu_backend.py`), Blender uses Vulkan. Also when the preferences are reloaded with
  other values (Metal, none, OpenGL in preferences of Blender 3.4) and for "Load Factory Settings".
"""

import os
import sys

import bpy

# On Android, Python redirects `sys.stdout` & `sys.stderr` to the system log (logcat) when
# embedded in an app. Under QEMU there is no logcat, restore the original streams.
sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import userpref_gpu_backend  # noqa: E402

failures = []


def check(condition, message):
    print("[gpu-backend-test] {:s}: {:s}".format("ok" if condition else "FAILED", message), flush=True)
    if not condition:
        failures.append(message)


def check_preference(context):
    value = bpy.context.preferences.system.gpu_backend
    check(value == 'VULKAN', "{:s}: gpu_backend preference is {!r}".format(context, value))


def test_factory():
    check_preference("factory settings")
    default = bpy.types.PreferencesSystem.bl_rna.properties["gpu_backend"].default
    check(default == 'VULKAN', "RNA default is {!r}".format(default))
    system = bpy.context.preferences.system
    try:
        system.gpu_backend = 'OPENGL'
    except TypeError:
        check(True, "OpenGL can't be selected")
    else:
        check(False, "OpenGL can be selected")
    system.gpu_backend = 'VULKAN'
    check_preference("selected")
    bpy.ops.wm.save_userpref()


def test_saved():
    check_preference("started with preferences saved with OpenGL")
    filepath = os.path.join(bpy.utils.user_resource('CONFIG'), "userpref.blend")
    for value, name in ((2, "Metal"), (0, "none"), (1, "OpenGL")):
        userpref_gpu_backend.write_gpu_backend(filepath, value)
        bpy.ops.wm.read_userpref()
        check_preference("preferences reloaded with {:s}".format(name))
    # Preferences of Blender 3.4: all versioning runs, also the block for files before 3.5.
    userpref_gpu_backend.set_file_version(filepath, 304)
    bpy.ops.wm.read_userpref()
    check_preference("preferences of Blender 3.4 with OpenGL")
    bpy.ops.wm.read_factory_settings()
    check_preference("Load Factory Settings")


def main():
    mode = sys.argv[sys.argv.index("--") + 1] if "--" in sys.argv else ""
    if mode == "factory":
        test_factory()
    elif mode == "saved":
        test_saved()
    else:
        check(False, "unknown mode {!r}".format(mode))
    if failures:
        print("[gpu-backend-test] {:d} FAILED".format(len(failures)), flush=True)
        sys.exit(1)
    print("[gpu-backend-test] GPU BACKEND TEST PASSED", flush=True)


main()

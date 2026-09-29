/* SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Loads `libblender.so` and calls its `SDL_main`, like the Android activity does.
 * Used to run Blender in background mode (no window) on a Linux host with QEMU user-mode
 * emulation and Android's bionic libraries, see `tests/qemu/run_blender.sh`. */

#include <dlfcn.h>
#include <stdio.h>

typedef int (*main_fn)(int argc, char *argv[]);

int main(int argc, char *argv[])
{
  if (argc < 2) {
    fprintf(stderr, "usage: %s /path/to/libblender.so [blender arguments...]\n", argv[0]);
    return 2;
  }
  void *handle = dlopen(argv[1], RTLD_NOW | RTLD_GLOBAL);
  if (handle == NULL) {
    fprintf(stderr, "dlopen failed: %s\n", dlerror());
    return 1;
  }
  main_fn sdl_main = (main_fn)dlsym(handle, "SDL_main");
  if (sdl_main == NULL) {
    fprintf(stderr, "SDL_main not found: %s\n", dlerror());
    return 1;
  }
  /* argv[0] = "app_process" as passed by SDL on Android, followed by Blender's arguments. */
  argv[1] = "app_process";
  return sdl_main(argc - 1, argv + 1);
}

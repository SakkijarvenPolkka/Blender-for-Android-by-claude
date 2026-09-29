/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup creator
 *
 * Android entry point.
 *
 * The Java activity (`org.blender.android.BlenderActivity`, a sub-class of SDL's
 * `SDLActivity`) prepares the environment (data file locations, see the Android app project),
 * loads `libblender.so` and calls `SDL_main` on a dedicated thread.
 */

#ifndef __ANDROID__
#  error "Android only"
#endif

#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>

#include <android/log.h>
#include <jni.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <pthread.h>
#include <unistd.h>

/* Blender's `main` (see `creator.cc`). */
int blender_android_main(int argc, const char **argv);

/* -------------------------------------------------------------------- */
/** \name Redirect `stdout` & `stderr` to `logcat`
 * \{ */

static int g_log_pipe[2] = {-1, -1};

static void *log_thread_fn(void * /*user_data*/)
{
  char buf[4096];
  size_t len = 0;
  while (true) {
    const ssize_t read_len = read(g_log_pipe[0], buf + len, sizeof(buf) - 1 - len);
    if (read_len <= 0) {
      break;
    }
    len += size_t(read_len);
    buf[len] = '\0';

    /* Write complete lines, keep the remainder. */
    char *line = buf;
    char *newline;
    while ((newline = strchr(line, '\n')) != nullptr) {
      *newline = '\0';
      __android_log_write(ANDROID_LOG_INFO, "Blender", line);
      line = newline + 1;
    }
    len = strlen(line);
    if (len == sizeof(buf) - 1) {
      /* Line too long, flush. */
      __android_log_write(ANDROID_LOG_INFO, "Blender", line);
      len = 0;
    }
    else if (line != buf) {
      memmove(buf, line, len + 1);
    }
  }
  return nullptr;
}

static void log_redirect_init()
{
  setvbuf(stdout, nullptr, _IOLBF, 0);
  setvbuf(stderr, nullptr, _IONBF, 0);
  if (pipe(g_log_pipe) != 0) {
    return;
  }
  dup2(g_log_pipe[1], STDOUT_FILENO);
  dup2(g_log_pipe[1], STDERR_FILENO);

  pthread_t thread;
  if (pthread_create(&thread, nullptr, log_thread_fn, nullptr) == 0) {
    pthread_detach(thread);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Functions for Python Scripts
 *
 * Called through `ctypes` (e.g. `ctypes.pythonapi.blender_android_keep_alive`).
 * \{ */

/**
 * Keep Blender running while it's in the background (a foreground service with a notification),
 * otherwise Android can freeze or stop the application.
 * The requests are counted: every enable must be matched by a disable.
 */
extern "C" JNIEXPORT void blender_android_keep_alive(const int enable)
{
  JNIEnv *env = static_cast<JNIEnv *>(SDL_GetAndroidJNIEnv());
  jobject activity = static_cast<jobject>(SDL_GetAndroidActivity());
  if (env == nullptr || activity == nullptr) {
    return;
  }
  jclass activity_class = env->GetObjectClass(activity);
  jmethodID method = env->GetMethodID(activity_class, "setKeepAlive", "(Z)V");
  if (method != nullptr) {
    env->CallVoidMethod(activity, method, jboolean(enable != 0));
  }
  if (env->ExceptionCheck()) {
    env->ExceptionClear();
  }
  env->DeleteLocalRef(activity_class);
  env->DeleteLocalRef(activity);
}

/** \} */

int main(int argc, char *argv[])
{
  /* Keep the standard streams when running outside of the app (testing). */
  if (getenv("BLENDER_ANDROID_KEEP_STDOUT") == nullptr) {
    log_redirect_init();
  }

  /* USD is linked statically (no library directory to find its plug-ins from), its plug-in
   * resources are installed with the data files. */
  const char *resources = getenv("BLENDER_SYSTEM_RESOURCES");
  if (resources != nullptr && getenv("PXR_PLUGINPATH_NAME") == nullptr) {
    char usd_path[4096];
    snprintf(usd_path, sizeof(usd_path), "%s/datafiles/usd", resources);
    setenv("PXR_PLUGINPATH_NAME", usd_path, 0);
  }

  /* SDL passes the arguments given by `SDLActivity.getArguments()`
   * (`argv[0]` is "app_process"). */
  return blender_android_main(argc, const_cast<const char **>(argv));
}

/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Android specific GHOST API.
 */

#pragma once

#ifdef __ANDROID__

/** Application life-cycle notifications, see #GHOST_AndroidSetLifecycleCallback. */
enum GHOST_TAndroidLifecycleEvent {
  /** The application is about to be paused (it may be killed afterwards). */
  GHOST_kAndroidLifecycleEnterBackground = 0,
  /** The application was resumed. */
  GHOST_kAndroidLifecycleEnterForeground,
  /** The operating system is about to terminate the application. */
  GHOST_kAndroidLifecycleTerminating,
  /** The operating system is low on memory. */
  GHOST_kAndroidLifecycleLowMemory,
};

using GHOST_TAndroidLifecycleCallback = void (*)(GHOST_TAndroidLifecycleEvent event);

/**
 * Register a callback for application life-cycle events (called from the main thread while
 * processing events). Used by the window-manager to write a recovery file when the application
 * goes to the background, since Android may kill it at any time afterwards.
 */
void GHOST_AndroidSetLifecycleCallback(GHOST_TAndroidLifecycleCallback callback);

/**
 * Called from the Java UI thread (see `org.blender.ghost.GhostAndroid`),
 * these queue an event for the main thread.
 */
void GHOST_AndroidToggleVirtualKeyboard();
void GHOST_AndroidOpenFile(const char *filepath);

#endif /* __ANDROID__ */

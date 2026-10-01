/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 */

#include "GHOST_SystemAndroid.hh"
#include "GHOST_WindowAndroid.hh"

#include "GHOST_EventButton.hh"
#include "GHOST_EventCursor.hh"
#include "GHOST_EventDragnDrop.hh"
#include "GHOST_EventKey.hh"
#include "GHOST_EventTrackpad.hh"
#include "GHOST_EventWheel.hh"
#include "GHOST_TimerManager.hh"
#include "GHOST_WindowManager.hh"

#include "GHOST_ContextNone.hh"
#ifdef WITH_VULKAN_BACKEND
#  include "GHOST_ContextVK.hh"
#endif

#include "CLG_log.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <stdexcept>

static CLG_LogRef LOG = {"ghost.android"};

/* -------------------------------------------------------------------- */
/** \name Tuning
 *
 * Distances are in "density independent pixels".
 * \{ */

/** Movement before a single finger touch becomes a drag. */
static constexpr float TOUCH_SLOP_DP = 10.0f;
/** Duration without movement for a long press (right click). */
static constexpr uint64_t TOUCH_LONG_PRESS_MS = 550;
/** Maximum duration & movement of a two finger tap (right click). */
static constexpr uint64_t TOUCH_TWO_FINGER_TAP_MS = 300;
static constexpr float TOUCH_TWO_FINGER_TAP_SLOP_DP = 16.0f;
/** Movement before deciding between pan and zoom gestures. */
static constexpr float TOUCH_GESTURE_DECIDE_DP = 12.0f;
/** Trackpad pan units per "density independent pixel" of finger movement. */
static constexpr float TOUCH_PAN_SCALE = 1.0f;
/** Trackpad magnify units per relative change of the finger distance. */
static constexpr float TOUCH_ZOOM_SCALE = 150.0f;

/** \} */

/* -------------------------------------------------------------------- */
/** \name Life-cycle Callback
 * \{ */

static GHOST_TAndroidLifecycleCallback g_lifecycle_callback = nullptr;

void GHOST_AndroidSetLifecycleCallback(GHOST_TAndroidLifecycleCallback callback)
{
  g_lifecycle_callback = callback;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Requests from the Java UI Thread
 * \{ */

/** Custom SDL event types (zero until the system is created). */
static uint32_t g_event_toggle_keyboard = 0;
static uint32_t g_event_open_file = 0;
static uint32_t g_event_surface = 0;

void GHOST_AndroidToggleVirtualKeyboard()
{
  if (g_event_toggle_keyboard == 0) {
    return;
  }
  SDL_Event event = {};
  event.type = g_event_toggle_keyboard;
  SDL_PushEvent(&event);
}

void GHOST_AndroidOpenFile(const char *filepath)
{
  if (g_event_open_file == 0 || filepath == nullptr) {
    return;
  }
  SDL_Event event = {};
  event.type = g_event_open_file;
  /* Freed by the main thread. */
  event.user.data1 = strdup(filepath);
  if (!SDL_PushEvent(&event)) {
    free(event.user.data1);
  }
}

void GHOST_AndroidSurfaceChanged(const bool available)
{
  if (g_event_surface == 0) {
    return;
  }
  SDL_Event event = {};
  event.type = g_event_surface;
  event.user.code = available ? 1 : 0;
  SDL_PushEvent(&event);
}

#include <jni.h>

extern "C" {
JNIEXPORT void JNICALL Java_org_blender_ghost_GhostAndroid_toggleVirtualKeyboard(JNIEnv * /*env*/,
                                                                                jclass /*cls*/)
{
  GHOST_AndroidToggleVirtualKeyboard();
}

JNIEXPORT void JNICALL Java_org_blender_ghost_GhostAndroid_openFile(JNIEnv *env,
                                                                   jclass /*cls*/,
                                                                   jstring filepath)
{
  const char *filepath_utf8 = env->GetStringUTFChars(filepath, nullptr);
  GHOST_AndroidOpenFile(filepath_utf8);
  env->ReleaseStringUTFChars(filepath, filepath_utf8);
}

JNIEXPORT void JNICALL Java_org_blender_ghost_GhostAndroid_surfaceChanged(JNIEnv * /*env*/,
                                                                         jclass /*cls*/,
                                                                         jboolean available)
{
  GHOST_AndroidSurfaceChanged(available != JNI_FALSE);
}
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name System
 * \{ */

GHOST_SystemAndroid::GHOST_SystemAndroid() : GHOST_System()
{
  /* Touch, pen and mouse input are handled separately (see header). */
  SDL_SetHint(SDL_HINT_TOUCH_MOUSE_EVENTS, "0");
  SDL_SetHint(SDL_HINT_MOUSE_TOUCH_EVENTS, "0");
  SDL_SetHint(SDL_HINT_PEN_MOUSE_EVENTS, "0");
  SDL_SetHint(SDL_HINT_PEN_TOUCH_EVENTS, "0");
  /* "Back" is mapped to escape instead of closing the activity. */
  SDL_SetHint(SDL_HINT_ANDROID_TRAP_BACK_BUTTON, "1");
  /* Keep running in the background (renders, requests to the MCP server add-on): nothing is
   * presented without a surface, see #GHOST_WindowAndroid::setSurfaceAvailable. The application
   * keeps the process alive with a foreground service when needed (see `BlenderActivity`). */
  SDL_SetHint(SDL_HINT_ANDROID_BLOCK_ON_PAUSE, "0");
  /* Blender draws the IME composition string itself. */
  SDL_SetHint(SDL_HINT_IME_IMPLEMENTED_UI, "composition");
  /* Blender handles signals itself, SDL would turn SIGINT & SIGTERM into a quit request. */
  SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");
  if (std::getenv("BLENDER_ANDROID_ORIENTATIONS") == nullptr) {
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");
  }
  else {
    SDL_SetHint(SDL_HINT_ORIENTATIONS, std::getenv("BLENDER_ANDROID_ORIENTATIONS"));
  }

  if (!SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS)) {
    throw std::runtime_error(SDL_GetError());
  }

  const uint32_t user_events = SDL_RegisterEvents(3);
  if (user_events != 0) {
    g_event_open_file = user_events;
    g_event_toggle_keyboard = user_events + 1;
    g_event_surface = user_events + 2;
  }

  SDL_AddEventWatch(lifecycleEventWatch, this);
}

GHOST_SystemAndroid::~GHOST_SystemAndroid()
{
  SDL_RemoveEventWatch(lifecycleEventWatch, this);
  g_event_open_file = 0;
  g_event_toggle_keyboard = 0;
  g_event_surface = 0;
  SDL_Quit();
}

GHOST_TSuccess GHOST_SystemAndroid::init()
{
  return GHOST_System::init();
}

GHOST_IWindow *GHOST_SystemAndroid::createWindow(const char *title,
                                                 int32_t /*left*/,
                                                 int32_t /*top*/,
                                                 uint32_t width,
                                                 uint32_t height,
                                                 GHOST_TWindowState state,
                                                 GHOST_GPUSettings gpu_settings,
                                                 const bool exclusive,
                                                 const bool /*is_dialog*/,
                                                 const GHOST_IWindow * /*parent_window*/)
{
  if (window_ != nullptr) {
    /* An activity has a single surface. Blender can show preferences, file browsers & renders
     * inside the main window instead (see "Temporary Editors" in the preferences). */
    CLOG_WARN(&LOG, "Only a single window is supported on Android");
    return nullptr;
  }

  const GHOST_ContextParams context_params = GHOST_CONTEXT_PARAMS_FROM_GPU_SETTINGS(gpu_settings);
  GHOST_WindowAndroid *window = new GHOST_WindowAndroid(this,
                                                        title,
                                                        width,
                                                        height,
                                                        state,
                                                        gpu_settings.context_type,
                                                        context_params,
                                                        gpu_settings.preferred_device,
                                                        exclusive);
  if (!window->getValid()) {
    delete window;
    return nullptr;
  }

  window_ = window;
  window_manager_->addWindow(window);
  window_manager_->setActiveWindow(window);
  cursor_[0] = float(window->getWidth()) * 0.5f;
  cursor_[1] = float(window->getHeight()) * 0.5f;
  pushEvent(std::make_unique<GHOST_Event>(getMilliSeconds(), GHOST_kEventWindowSize, window));
  return window;
}

GHOST_IContext *GHOST_SystemAndroid::createOffscreenContext(GHOST_GPUSettings gpu_settings)
{
  const GHOST_ContextParams context_params_offscreen =
      GHOST_CONTEXT_PARAMS_FROM_GPU_SETTINGS_OFFSCREEN(gpu_settings);

  switch (gpu_settings.context_type) {
#ifdef WITH_VULKAN_BACKEND
    case GHOST_kDrawingContextTypeVulkan: {
      GHOST_Context *context = new GHOST_ContextVK(
          context_params_offscreen, nullptr, 1, 2, gpu_settings.preferred_device);
      if (context->initializeDrawingContext()) {
        return context;
      }
      delete context;
      return nullptr;
    }
#endif
    case GHOST_kDrawingContextTypeNone: {
      GHOST_Context *context = new GHOST_ContextNone(context_params_offscreen);
      if (context->initializeDrawingContext()) {
        return context;
      }
      delete context;
      return nullptr;
    }
    default:
      return nullptr;
  }
}

GHOST_TSuccess GHOST_SystemAndroid::disposeContext(GHOST_IContext *context)
{
  delete context;
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemAndroid::disposeWindow(GHOST_IWindow *window)
{
  if (window == window_) {
    window_ = nullptr;
  }
  dirty_windows_.erase(std::remove(dirty_windows_.begin(),
                                   dirty_windows_.end(),
                                   static_cast<GHOST_WindowAndroid *>(window)),
                       dirty_windows_.end());
  return GHOST_System::disposeWindow(window);
}

void GHOST_SystemAndroid::addDirtyWindow(GHOST_WindowAndroid *window)
{
  dirty_windows_.push_back(window);
}

void GHOST_SystemAndroid::setRelativeMouseMode(bool relative)
{
  relative_mouse_mode_ = relative;
}

float GHOST_SystemAndroid::getDensity() const
{
  float scale = window_ ? SDL_GetWindowDisplayScale(window_->getSDLWindow()) : 0.0f;
  if (scale <= 0.0f) {
    scale = 1.0f;
  }
  return scale;
}

uint64_t GHOST_SystemAndroid::getMilliSeconds() const
{
  return SDL_GetTicks();
}

uint8_t GHOST_SystemAndroid::getNumDisplays() const
{
  return 1;
}

void GHOST_SystemAndroid::getMainDisplayDimensions(uint32_t &width, uint32_t &height) const
{
  if (window_) {
    width = uint32_t(window_->getWidth());
    height = uint32_t(window_->getHeight());
    return;
  }
  const SDL_DisplayMode *mode = SDL_GetCurrentDisplayMode(SDL_GetPrimaryDisplay());
  if (mode) {
    width = uint32_t(mode->w * mode->pixel_density);
    height = uint32_t(mode->h * mode->pixel_density);
  }
}

void GHOST_SystemAndroid::getAllDisplayDimensions(uint32_t &width, uint32_t &height) const
{
  getMainDisplayDimensions(width, height);
}

GHOST_TSuccess GHOST_SystemAndroid::getCursorPosition(int32_t &x, int32_t &y) const
{
  x = int32_t(cursor_[0]);
  y = int32_t(cursor_[1]);
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemAndroid::setCursorPosition(int32_t x, int32_t y)
{
  /* The pointer can't be warped on Android, only update the position reported to Blender. */
  cursor_[0] = float(x);
  cursor_[1] = float(y);
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemAndroid::getModifierKeys(GHOST_ModifierKeys &keys) const
{
  const SDL_Keymod mod = SDL_GetModState();
  keys.set(GHOST_kModifierKeyLeftShift, (mod & SDL_KMOD_LSHIFT) != 0 || gesture_shift_held_);
  keys.set(GHOST_kModifierKeyRightShift, (mod & SDL_KMOD_RSHIFT) != 0);
  keys.set(GHOST_kModifierKeyLeftControl, (mod & SDL_KMOD_LCTRL) != 0);
  keys.set(GHOST_kModifierKeyRightControl, (mod & SDL_KMOD_RCTRL) != 0);
  keys.set(GHOST_kModifierKeyLeftAlt, (mod & SDL_KMOD_LALT) != 0);
  keys.set(GHOST_kModifierKeyRightAlt, (mod & SDL_KMOD_RALT) != 0);
  keys.set(GHOST_kModifierKeyLeftOS, (mod & SDL_KMOD_LGUI) != 0);
  keys.set(GHOST_kModifierKeyRightOS, (mod & SDL_KMOD_RGUI) != 0);
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_SystemAndroid::getButtons(GHOST_Buttons &buttons) const
{
  buttons = buttons_;
  return GHOST_kSuccess;
}

GHOST_TCapabilityFlag GHOST_SystemAndroid::getCapabilities() const
{
  return GHOST_TCapabilityFlag(
      GHOST_CAPABILITY_FLAG_ALL &
      ~(
          /* The pointer can't be moved by applications. */
          GHOST_kCapabilityCursorWarp |
          /* There is a single full-screen window. */
          GHOST_kCapabilityWindowPosition | GHOST_kCapabilityMultiMonitorPlacement |
          GHOST_kCapabilityWindowDecorationStyles | GHOST_kCapabilityWindowDecorationServerSide |
          GHOST_kCapabilityWindowPath |
          /* Not supported by Android. */
          GHOST_kCapabilityClipboardPrimary | GHOST_kCapabilityDesktopSample |
          GHOST_kCapabilityKeyboardHyperKey |
          /* Not yet implemented. */
          GHOST_kCapabilityClipboardImage | GHOST_kCapabilityCursorRGBA |
          GHOST_kCapabilityCursorGenerator | GHOST_kCapabilityGPUReadFrontBuffer
#ifndef WITH_INPUT_IME
          | GHOST_kCapabilityInputIME
#endif
          ));
}

char *GHOST_SystemAndroid::getClipboard(bool selection) const
{
  if (selection) {
    return nullptr;
  }
  char *sdl_text = SDL_GetClipboardText();
  if (sdl_text == nullptr) {
    return nullptr;
  }
  char *result = strdup(sdl_text);
  SDL_free(sdl_text);
  return result;
}

void GHOST_SystemAndroid::putClipboard(const char *buffer, bool selection) const
{
  if (!selection) {
    SDL_SetClipboardText(buffer);
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Event Processing
 * \{ */

bool GHOST_SystemAndroid::generateWindowExposeEvents()
{
  bool any_processed = false;
  for (GHOST_WindowAndroid *window : dirty_windows_) {
    window->validate();
    pushEvent(
        std::make_unique<GHOST_Event>(getMilliSeconds(), GHOST_kEventWindowUpdate, window));
    any_processed = true;
  }
  dirty_windows_.clear();
  return any_processed;
}

bool GHOST_SystemAndroid::processEvents(bool waitForEvent)
{
  bool any_processed = false;

  do {
    GHOST_TimerManager *timer_manager = getTimerManager();
    const uint64_t now = getMilliSeconds();

    if (waitForEvent && dirty_windows_.empty() && !SDL_HasEvents(SDL_EVENT_FIRST, SDL_EVENT_LAST))
    {
      int64_t timeout = -1;
      const uint64_t next = timer_manager->nextFireTime();
      if (next != GHOST_kFireTimeNever) {
        timeout = (next > now) ? int64_t(next - now) : 0;
      }
      const int64_t touch_timeout = touchTimerTimeout(now);
      if (touch_timeout >= 0 && (timeout < 0 || touch_timeout < timeout)) {
        timeout = touch_timeout;
      }
      SDL_WaitEventTimeout(nullptr, int32_t(std::min<int64_t>(timeout, INT32_MAX)));
    }

    if (timer_manager->fireTimers(getMilliSeconds())) {
      any_processed = true;
    }

    SDL_Event sdl_event;
    while (SDL_PollEvent(&sdl_event)) {
      processEvent(sdl_event);
      any_processed = true;
    }
    flushPenMotion();

    /* Sent while SDL pumps events (see #lifecycleEventWatch). */
    if (processLifecycleEvents()) {
      any_processed = true;
    }

    if (processTouchTimers(getMilliSeconds())) {
      any_processed = true;
    }

    /* The size can change without an event (e.g. while the activity is paused). */
    if (window_ && window_->updateSize()) {
      pushEvent(
          std::make_unique<GHOST_Event>(getMilliSeconds(), GHOST_kEventWindowSize, window_));
      any_processed = true;
    }

    if (generateWindowExposeEvents()) {
      any_processed = true;
    }
  } while (waitForEvent && !any_processed);

  return any_processed;
}

void GHOST_SystemAndroid::processEvent(const SDL_Event &event)
{
  /* A pen motion is followed by its pressure (when it changed). */
  if (event.type != SDL_EVENT_PEN_AXIS) {
    flushPenMotion();
  }

  switch (event.type) {
    case SDL_EVENT_QUIT: {
      pushEvent(std::make_unique<GHOST_Event>(
          SDL_NS_TO_MS(event.quit.timestamp), GHOST_kEventQuitRequest, window_));
      break;
    }

    case SDL_EVENT_WINDOW_EXPOSED: {
      if (window_) {
        pushEvent(std::make_unique<GHOST_Event>(
            SDL_NS_TO_MS(event.window.timestamp), GHOST_kEventWindowUpdate, window_));
      }
      break;
    }
    case SDL_EVENT_WINDOW_RESIZED:
    case SDL_EVENT_WINDOW_PIXEL_SIZE_CHANGED:
    case SDL_EVENT_WINDOW_DISPLAY_SCALE_CHANGED: {
      if (window_) {
        window_->updateSize();
        pushEvent(std::make_unique<GHOST_Event>(
            SDL_NS_TO_MS(event.window.timestamp), GHOST_kEventWindowSize, window_));
        if (event.type == SDL_EVENT_WINDOW_DISPLAY_SCALE_CHANGED) {
          pushEvent(std::make_unique<GHOST_Event>(
              SDL_NS_TO_MS(event.window.timestamp), GHOST_kEventWindowDPIHintChanged, window_));
        }
      }
      break;
    }
    case SDL_EVENT_WINDOW_FOCUS_GAINED: {
      if (window_) {
        window_manager_->setActiveWindow(window_);
        pushEvent(std::make_unique<GHOST_Event>(
            SDL_NS_TO_MS(event.window.timestamp), GHOST_kEventWindowActivate, window_));
      }
      break;
    }
    case SDL_EVENT_WINDOW_FOCUS_LOST: {
      if (window_) {
        window_manager_->setWindowInactive(window_);
        pushEvent(std::make_unique<GHOST_Event>(
            SDL_NS_TO_MS(event.window.timestamp), GHOST_kEventWindowDeactivate, window_));
      }
      break;
    }
    case SDL_EVENT_WINDOW_CLOSE_REQUESTED: {
      if (window_) {
        pushEvent(std::make_unique<GHOST_Event>(
            SDL_NS_TO_MS(event.window.timestamp), GHOST_kEventWindowClose, window_));
      }
      break;
    }

    case SDL_EVENT_KEY_DOWN:
    case SDL_EVENT_KEY_UP: {
      processKeyEvent(event.key);
      break;
    }

    case SDL_EVENT_TEXT_INPUT: {
      processTextEvent(event.text);
      break;
    }

    case SDL_EVENT_MOUSE_MOTION:
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
    case SDL_EVENT_MOUSE_BUTTON_UP:
    case SDL_EVENT_MOUSE_WHEEL: {
      processMouseEvent(event);
      break;
    }

    case SDL_EVENT_PEN_PROXIMITY_IN:
    case SDL_EVENT_PEN_PROXIMITY_OUT:
    case SDL_EVENT_PEN_DOWN:
    case SDL_EVENT_PEN_UP:
    case SDL_EVENT_PEN_BUTTON_DOWN:
    case SDL_EVENT_PEN_BUTTON_UP:
    case SDL_EVENT_PEN_MOTION:
    case SDL_EVENT_PEN_AXIS: {
      processPenEvent(event);
      break;
    }

    case SDL_EVENT_FINGER_DOWN:
    case SDL_EVENT_FINGER_UP:
    case SDL_EVENT_FINGER_MOTION:
    case SDL_EVENT_FINGER_CANCELED: {
      processFingerEvent(event.tfinger);
      break;
    }

    case SDL_EVENT_DROP_FILE: {
      processDropEvent(event.drop.data, SDL_NS_TO_MS(event.drop.timestamp));
      break;
    }

    default: {
      if (event.type == g_event_toggle_keyboard && g_event_toggle_keyboard != 0) {
        if (window_) {
          window_->toggleVirtualKeyboard();
        }
      }
      else if (event.type == g_event_open_file && g_event_open_file != 0) {
        char *filepath = static_cast<char *>(event.user.data1);
        processDropEvent(filepath, getMilliSeconds());
        free(filepath);
      }
      else if (event.type == g_event_surface && g_event_surface != 0) {
        processSurfaceChanged(event.user.code != 0);
      }
      break;
    }
  }
}

void GHOST_SystemAndroid::processDropEvent(const char *filepath, uint64_t time_ms)
{
  if (window_ == nullptr || filepath == nullptr) {
    return;
  }
  /* Freed by #GHOST_EventDragnDrop. */
  GHOST_TStringArray *files = static_cast<GHOST_TStringArray *>(
      malloc(sizeof(GHOST_TStringArray)));
  files->count = 1;
  files->strings = static_cast<uint8_t **>(malloc(sizeof(uint8_t *)));
  files->strings[0] = reinterpret_cast<uint8_t *>(strdup(filepath));
  pushEvent(std::make_unique<GHOST_EventDragnDrop>(time_ms,
                                                   GHOST_kEventDraggingDropDone,
                                                   GHOST_kDragnDropTypeFilenames,
                                                   window_,
                                                   window_->getWidth() / 2,
                                                   window_->getHeight() / 2,
                                                   files));
}

bool GHOST_SystemAndroid::lifecycleEventWatch(void *userdata, SDL_Event *event)
{
  /* Called for every event SDL sends, from any thread (e.g. touch events from the UI thread):
   * only queue the life-cycle events, they are handled on the main thread. */
  switch (event->type) {
    case SDL_EVENT_TERMINATING:
    case SDL_EVENT_LOW_MEMORY:
    case SDL_EVENT_WILL_ENTER_BACKGROUND:
    case SDL_EVENT_DID_ENTER_BACKGROUND:
    case SDL_EVENT_WILL_ENTER_FOREGROUND:
    case SDL_EVENT_DID_ENTER_FOREGROUND: {
      GHOST_SystemAndroid *system = static_cast<GHOST_SystemAndroid *>(userdata);
      std::lock_guard<std::mutex> lock(system->lifecycle_mutex_);
      system->lifecycle_events_.push_back(*event);
      break;
    }
    default:
      break;
  }
  return true;
}

bool GHOST_SystemAndroid::processLifecycleEvents()
{
  std::vector<SDL_Event> events;
  {
    std::lock_guard<std::mutex> lock(lifecycle_mutex_);
    events.swap(lifecycle_events_);
  }
  for (const SDL_Event &event : events) {
    processLifecycleEvent(event);
  }
  return !events.empty();
}

void GHOST_SystemAndroid::processSurfaceChanged(const bool available)
{
  if (window_ == nullptr) {
    return;
  }
  CLOG_INFO(&LOG, "Surface %s", available ? "available" : "destroyed");
  window_->setSurfaceAvailable(available);
  if (available) {
    if (window_->updateSize()) {
      pushEvent(std::make_unique<GHOST_Event>(getMilliSeconds(), GHOST_kEventWindowSize, window_));
    }
    window_->invalidate();
  }
}

void GHOST_SystemAndroid::processLifecycleEvent(const SDL_Event &event)
{
  switch (event.type) {
    case SDL_EVENT_WILL_ENTER_BACKGROUND: {
      CLOG_INFO(&LOG, "Entering background");
      /* Nothing can be presented anymore: the surface is destroyed any time from now on. */
      if (window_) {
        window_->setSurfaceAvailable(false);
      }
      if (g_lifecycle_callback) {
        g_lifecycle_callback(GHOST_kAndroidLifecycleEnterBackground);
      }
      break;
    }
    case SDL_EVENT_DID_ENTER_FOREGROUND: {
      CLOG_INFO(&LOG, "Entered foreground");
      /* SDL only resumes once the activity has a (new) surface. */
      if (window_) {
        window_->updateSize();
        window_->setSurfaceAvailable(true);
        window_->invalidate();
      }
      if (g_lifecycle_callback) {
        g_lifecycle_callback(GHOST_kAndroidLifecycleEnterForeground);
      }
      break;
    }
    case SDL_EVENT_TERMINATING: {
      CLOG_INFO(&LOG, "Terminating");
      if (g_lifecycle_callback) {
        g_lifecycle_callback(GHOST_kAndroidLifecycleTerminating);
      }
      break;
    }
    case SDL_EVENT_LOW_MEMORY: {
      /* Also sent each time the application goes to the background (`TRIM_MEMORY_UI_HIDDEN`). */
      CLOG_INFO(&LOG, "Low memory");
      if (g_lifecycle_callback) {
        g_lifecycle_callback(GHOST_kAndroidLifecycleLowMemory);
      }
      break;
    }
    default:
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Event Helpers
 * \{ */

void GHOST_SystemAndroid::pushCursorMove(uint64_t time_ms,
                                         int32_t x,
                                         int32_t y,
                                         const GHOST_TabletData &tablet)
{
  if (window_ == nullptr) {
    return;
  }
  pushEvent(std::make_unique<GHOST_EventCursor>(
      time_ms, GHOST_kEventCursorMove, window_, x, y, tablet));
}

void GHOST_SystemAndroid::pushButton(uint64_t time_ms,
                                     GHOST_TEventType type,
                                     GHOST_TButton button,
                                     const GHOST_TabletData &tablet)
{
  if (window_ == nullptr) {
    return;
  }
  buttons_.set(button, type == GHOST_kEventButtonDown);
  pushEvent(std::make_unique<GHOST_EventButton>(time_ms, type, window_, button, tablet));
}

void GHOST_SystemAndroid::pushKey(uint64_t time_ms,
                                  GHOST_TEventType type,
                                  GHOST_TKey key,
                                  bool is_repeat)
{
  if (window_ == nullptr) {
    return;
  }
  pushEvent(std::make_unique<GHOST_EventKey>(time_ms, type, window_, key, is_repeat));
}

void GHOST_SystemAndroid::pushTrackpad(uint64_t time_ms,
                                       GHOST_TTrackpadEventSubTypes subtype,
                                       int32_t x,
                                       int32_t y,
                                       int32_t dx,
                                       int32_t dy)
{
  if (window_ == nullptr) {
    return;
  }
  /* Content follows the fingers ("natural" direction). */
  pushEvent(std::make_unique<GHOST_EventTrackpad>(time_ms, window_, subtype, x, y, dx, dy, true));
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Keyboard
 * \{ */

#define GXMAP(k, x, y) \
  case x: \
    k = y; \
    break

static GHOST_TKey convert_sdl_scancode(SDL_Scancode key)
{
  GHOST_TKey type;

  if ((key >= SDL_SCANCODE_A) && (key <= SDL_SCANCODE_Z)) {
    type = GHOST_TKey(key - SDL_SCANCODE_A + int(GHOST_kKeyA));
  }
  else if ((key >= SDL_SCANCODE_1) && (key <= SDL_SCANCODE_0)) {
    type = (key == SDL_SCANCODE_0) ? GHOST_kKey0 :
                                     GHOST_TKey(key - SDL_SCANCODE_1 + int(GHOST_kKey1));
  }
  else if ((key >= SDL_SCANCODE_F1) && (key <= SDL_SCANCODE_F12)) {
    type = GHOST_TKey(key - SDL_SCANCODE_F1 + int(GHOST_kKeyF1));
  }
  else if ((key >= SDL_SCANCODE_F13) && (key <= SDL_SCANCODE_F24)) {
    type = GHOST_TKey(key - SDL_SCANCODE_F13 + int(GHOST_kKeyF13));
  }
  else {
    switch (key) {
      GXMAP(type, SDL_SCANCODE_BACKSPACE, GHOST_kKeyBackSpace);
      GXMAP(type, SDL_SCANCODE_TAB, GHOST_kKeyTab);
      GXMAP(type, SDL_SCANCODE_RETURN, GHOST_kKeyEnter);
      GXMAP(type, SDL_SCANCODE_ESCAPE, GHOST_kKeyEsc);
      /* The Android "back" button/gesture. */
      GXMAP(type, SDL_SCANCODE_AC_BACK, GHOST_kKeyEsc);
      GXMAP(type, SDL_SCANCODE_SPACE, GHOST_kKeySpace);

      GXMAP(type, SDL_SCANCODE_SEMICOLON, GHOST_kKeySemicolon);
      GXMAP(type, SDL_SCANCODE_PERIOD, GHOST_kKeyPeriod);
      GXMAP(type, SDL_SCANCODE_COMMA, GHOST_kKeyComma);
      GXMAP(type, SDL_SCANCODE_APOSTROPHE, GHOST_kKeyQuote);
      GXMAP(type, SDL_SCANCODE_GRAVE, GHOST_kKeyAccentGrave);
      GXMAP(type, SDL_SCANCODE_MINUS, GHOST_kKeyMinus);
      GXMAP(type, SDL_SCANCODE_EQUALS, GHOST_kKeyEqual);

      GXMAP(type, SDL_SCANCODE_SLASH, GHOST_kKeySlash);
      GXMAP(type, SDL_SCANCODE_BACKSLASH, GHOST_kKeyBackslash);
      GXMAP(type, SDL_SCANCODE_KP_EQUALS, GHOST_kKeyEqual);
      GXMAP(type, SDL_SCANCODE_LEFTBRACKET, GHOST_kKeyLeftBracket);
      GXMAP(type, SDL_SCANCODE_RIGHTBRACKET, GHOST_kKeyRightBracket);
      GXMAP(type, SDL_SCANCODE_PAUSE, GHOST_kKeyPause);

      GXMAP(type, SDL_SCANCODE_LSHIFT, GHOST_kKeyLeftShift);
      GXMAP(type, SDL_SCANCODE_RSHIFT, GHOST_kKeyRightShift);
      GXMAP(type, SDL_SCANCODE_LCTRL, GHOST_kKeyLeftControl);
      GXMAP(type, SDL_SCANCODE_RCTRL, GHOST_kKeyRightControl);
      GXMAP(type, SDL_SCANCODE_LALT, GHOST_kKeyLeftAlt);
      GXMAP(type, SDL_SCANCODE_RALT, GHOST_kKeyRightAlt);
      GXMAP(type, SDL_SCANCODE_LGUI, GHOST_kKeyLeftOS);
      GXMAP(type, SDL_SCANCODE_RGUI, GHOST_kKeyRightOS);
      GXMAP(type, SDL_SCANCODE_APPLICATION, GHOST_kKeyApp);
      GXMAP(type, SDL_SCANCODE_MENU, GHOST_kKeyApp);

      GXMAP(type, SDL_SCANCODE_INSERT, GHOST_kKeyInsert);
      GXMAP(type, SDL_SCANCODE_DELETE, GHOST_kKeyDelete);
      GXMAP(type, SDL_SCANCODE_HOME, GHOST_kKeyHome);
      GXMAP(type, SDL_SCANCODE_END, GHOST_kKeyEnd);
      GXMAP(type, SDL_SCANCODE_PAGEUP, GHOST_kKeyUpPage);
      GXMAP(type, SDL_SCANCODE_PAGEDOWN, GHOST_kKeyDownPage);

      GXMAP(type, SDL_SCANCODE_LEFT, GHOST_kKeyLeftArrow);
      GXMAP(type, SDL_SCANCODE_RIGHT, GHOST_kKeyRightArrow);
      GXMAP(type, SDL_SCANCODE_UP, GHOST_kKeyUpArrow);
      GXMAP(type, SDL_SCANCODE_DOWN, GHOST_kKeyDownArrow);

      GXMAP(type, SDL_SCANCODE_CAPSLOCK, GHOST_kKeyCapsLock);
      GXMAP(type, SDL_SCANCODE_SCROLLLOCK, GHOST_kKeyScrollLock);
      GXMAP(type, SDL_SCANCODE_NUMLOCKCLEAR, GHOST_kKeyNumLock);
      GXMAP(type, SDL_SCANCODE_PRINTSCREEN, GHOST_kKeyPrintScreen);

      GXMAP(type, SDL_SCANCODE_KP_0, GHOST_kKeyNumpad0);
      GXMAP(type, SDL_SCANCODE_KP_1, GHOST_kKeyNumpad1);
      GXMAP(type, SDL_SCANCODE_KP_2, GHOST_kKeyNumpad2);
      GXMAP(type, SDL_SCANCODE_KP_3, GHOST_kKeyNumpad3);
      GXMAP(type, SDL_SCANCODE_KP_4, GHOST_kKeyNumpad4);
      GXMAP(type, SDL_SCANCODE_KP_5, GHOST_kKeyNumpad5);
      GXMAP(type, SDL_SCANCODE_KP_6, GHOST_kKeyNumpad6);
      GXMAP(type, SDL_SCANCODE_KP_7, GHOST_kKeyNumpad7);
      GXMAP(type, SDL_SCANCODE_KP_8, GHOST_kKeyNumpad8);
      GXMAP(type, SDL_SCANCODE_KP_9, GHOST_kKeyNumpad9);
      GXMAP(type, SDL_SCANCODE_KP_PERIOD, GHOST_kKeyNumpadPeriod);
      GXMAP(type, SDL_SCANCODE_KP_ENTER, GHOST_kKeyNumpadEnter);
      GXMAP(type, SDL_SCANCODE_KP_PLUS, GHOST_kKeyNumpadPlus);
      GXMAP(type, SDL_SCANCODE_KP_MINUS, GHOST_kKeyNumpadMinus);
      GXMAP(type, SDL_SCANCODE_KP_MULTIPLY, GHOST_kKeyNumpadAsterisk);
      GXMAP(type, SDL_SCANCODE_KP_DIVIDE, GHOST_kKeyNumpadSlash);

      GXMAP(type, SDL_SCANCODE_MEDIA_PLAY, GHOST_kKeyMediaPlay);
      GXMAP(type, SDL_SCANCODE_MEDIA_PLAY_PAUSE, GHOST_kKeyMediaPlay);
      GXMAP(type, SDL_SCANCODE_MEDIA_STOP, GHOST_kKeyMediaStop);
      GXMAP(type, SDL_SCANCODE_MEDIA_PREVIOUS_TRACK, GHOST_kKeyMediaFirst);
      GXMAP(type, SDL_SCANCODE_MEDIA_NEXT_TRACK, GHOST_kKeyMediaLast);

      GXMAP(type, SDL_SCANCODE_NONUSBACKSLASH, GHOST_kKeyGrLess);

      default:
        type = GHOST_kKeyUnknown;
        break;
    }
  }
  return type;
}
#undef GXMAP

/** Encode a code-point as UTF-8, returns false for non printable code-points. */
static bool utf8_from_codepoint(uint32_t codepoint, char r_utf8[6])
{
  if (codepoint < 0x20 || codepoint == 0x7f || (codepoint & SDLK_SCANCODE_MASK)) {
    return false;
  }
  char *dst = r_utf8;
  if (codepoint < 0x80) {
    *dst++ = char(codepoint);
  }
  else if (codepoint < 0x800) {
    *dst++ = char(0xC0 | (codepoint >> 6));
    *dst++ = char(0x80 | (codepoint & 0x3F));
  }
  else if (codepoint < 0x10000) {
    *dst++ = char(0xE0 | (codepoint >> 12));
    *dst++ = char(0x80 | ((codepoint >> 6) & 0x3F));
    *dst++ = char(0x80 | (codepoint & 0x3F));
  }
  else if (codepoint < 0x110000) {
    *dst++ = char(0xF0 | (codepoint >> 18));
    *dst++ = char(0x80 | ((codepoint >> 12) & 0x3F));
    *dst++ = char(0x80 | ((codepoint >> 6) & 0x3F));
    *dst++ = char(0x80 | (codepoint & 0x3F));
  }
  else {
    return false;
  }
  *dst = '\0';
  return true;
}

/**
 * Keyboard ID of key presses simulated by SDL for characters typed with the virtual keyboard
 * (`SDLInputConnection.updateText` calls `nativeGenerateScancodeForUnichar` for ASCII characters,
 * in addition to sending the text).
 */
static constexpr SDL_KeyboardID KEYBOARD_ID_SDL_SIMULATED = 0;

void GHOST_SystemAndroid::processKeyEvent(const SDL_KeyboardEvent &event)
{
  if (window_ == nullptr) {
    return;
  }
  const GHOST_WindowAndroid::TextInputMode text_input_mode = window_->getTextInputMode();
  const uint64_t time_ms = SDL_NS_TO_MS(event.timestamp);
  const GHOST_TEventType type = event.down ? GHOST_kEventKeyDown : GHOST_kEventKeyUp;
  const GHOST_TKey key = convert_sdl_scancode(event.scancode);

  if (text_input_mode == GHOST_WindowAndroid::TextInputMode::IME &&
      event.which == KEYBOARD_ID_SDL_SIMULATED)
  {
    /* Editing text: the text is sent separately (see #processTextEvent), only keep simulated
     * editing keys (backspace, return, tab) and modifiers. */
    const SDL_Keycode keycode = SDL_GetKeyFromScancode(event.scancode, SDL_KMOD_NONE, false);
    if (keycode >= 0x20 && keycode < 0x7f) {
      return;
    }
  }

  /* Derive the text from the key-code using the current keyboard layout,
   * unless editing text: then the text is sent as #SDL_EVENT_TEXT_INPUT. */
  char utf8_buf[sizeof(GHOST_TEventKeyData::utf8_buf)] = {'\0'};
  const bool has_command_modifier = (event.mod & (SDL_KMOD_CTRL | SDL_KMOD_ALT | SDL_KMOD_GUI)) !=
                                    0;
  if (event.down && text_input_mode != GHOST_WindowAndroid::TextInputMode::IME &&
      !has_command_modifier)
  {
    const SDL_Keycode keycode = SDL_GetKeyFromScancode(event.scancode, event.mod, false);
    utf8_from_codepoint(uint32_t(keycode), utf8_buf);
  }
  if (key == GHOST_kKeyUnknown && utf8_buf[0] == '\0') {
    return;
  }
  pushEvent(std::make_unique<GHOST_EventKey>(
      time_ms, type, window_, key, event.repeat != 0, utf8_buf));
}

/** Byte length of the UTF-8 sequence starting with `c`, zero for an invalid lead byte. */
static int utf8_sequence_length(const uint8_t c)
{
  if (c < 0x80) {
    return 1;
  }
  if ((c & 0xE0) == 0xC0) {
    return 2;
  }
  if ((c & 0xF0) == 0xE0) {
    return 3;
  }
  if ((c & 0xF8) == 0xF0) {
    return 4;
  }
  return 0;
}

void GHOST_SystemAndroid::processTextEvent(const SDL_TextInputEvent &event)
{
  if (window_ == nullptr || event.text == nullptr) {
    return;
  }
  const GHOST_WindowAndroid::TextInputMode text_input_mode = window_->getTextInputMode();
  const uint64_t time_ms = SDL_NS_TO_MS(event.timestamp);

  /* Committed text is sent as key presses with text, as typed on a hardware keyboard: each event
   * owns its text. IME composition events can't be used, the window manager stores a single
   * composition per window, several commits handled together would overwrite each other.
   * SDL doesn't report compositions (pre-edit text) on Android. */
  const char *text = event.text;
  while (*text) {
    const int len = utf8_sequence_length(uint8_t(*text));
    if (len == 0) {
      text++;
      continue;
    }
    if (strnlen(text, size_t(len)) < size_t(len)) {
      break;
    }
    /* Typing shortcuts, ASCII characters are also simulated as key presses by SDL
     * (see #processKeyEvent). */
    const bool is_simulated_key = (len == 1);
    if (!(text_input_mode == GHOST_WindowAndroid::TextInputMode::Hotkeys && is_simulated_key) &&
        uint8_t(text[0]) >= 0x20 && text[0] != 0x7f)
    {
      char utf8_buf[sizeof(GHOST_TEventKeyData::utf8_buf)] = {'\0'};
      memcpy(utf8_buf, text, size_t(len));
      pushEvent(std::make_unique<GHOST_EventKey>(
          time_ms, GHOST_kEventKeyDown, window_, GHOST_kKeyUnknown, false, utf8_buf));
      pushEvent(std::make_unique<GHOST_EventKey>(
          time_ms, GHOST_kEventKeyUp, window_, GHOST_kKeyUnknown, false, nullptr));
    }
    text += len;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Mouse (Samsung DeX, Bluetooth or USB)
 * \{ */

static bool ghost_button_from_sdl(uint8_t sdl_button, GHOST_TButton &r_button)
{
  switch (sdl_button) {
    case SDL_BUTTON_LEFT:
      r_button = GHOST_kButtonMaskLeft;
      return true;
    case SDL_BUTTON_MIDDLE:
      r_button = GHOST_kButtonMaskMiddle;
      return true;
    case SDL_BUTTON_RIGHT:
      r_button = GHOST_kButtonMaskRight;
      return true;
    case SDL_BUTTON_X1:
      r_button = GHOST_kButtonMaskButton4;
      return true;
    case SDL_BUTTON_X2:
      r_button = GHOST_kButtonMaskButton5;
      return true;
    default:
      return false;
  }
}

void GHOST_SystemAndroid::processMouseEvent(const SDL_Event &event)
{
  if (window_ == nullptr) {
    return;
  }
  const float pixel_density = SDL_GetWindowPixelDensity(window_->getSDLWindow());

  switch (event.type) {
    case SDL_EVENT_MOUSE_MOTION: {
      const SDL_MouseMotionEvent &motion = event.motion;
      if (motion.which == SDL_TOUCH_MOUSEID || motion.which == SDL_PEN_MOUSEID) {
        return;
      }
      if (relative_mouse_mode_) {
        cursor_[0] += motion.xrel * pixel_density;
        cursor_[1] += motion.yrel * pixel_density;
      }
      else {
        cursor_[0] = motion.x * pixel_density;
        cursor_[1] = motion.y * pixel_density;
      }
      pushCursorMove(SDL_NS_TO_MS(motion.timestamp),
                     int32_t(cursor_[0]),
                     int32_t(cursor_[1]),
                     GHOST_TABLET_DATA_NONE);
      break;
    }
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
    case SDL_EVENT_MOUSE_BUTTON_UP: {
      const SDL_MouseButtonEvent &button_event = event.button;
      if (button_event.which == SDL_TOUCH_MOUSEID || button_event.which == SDL_PEN_MOUSEID) {
        return;
      }
      GHOST_TButton button;
      if (!ghost_button_from_sdl(button_event.button, button)) {
        return;
      }
      if (!relative_mouse_mode_) {
        cursor_[0] = button_event.x * pixel_density;
        cursor_[1] = button_event.y * pixel_density;
      }
      pushButton(SDL_NS_TO_MS(button_event.timestamp),
                 button_event.down ? GHOST_kEventButtonDown : GHOST_kEventButtonUp,
                 button,
                 GHOST_TABLET_DATA_NONE);
      break;
    }
    case SDL_EVENT_MOUSE_WHEEL: {
      const SDL_MouseWheelEvent &wheel = event.wheel;
      if (wheel.which == SDL_TOUCH_MOUSEID || wheel.which == SDL_PEN_MOUSEID) {
        return;
      }
      const float direction = (wheel.direction == SDL_MOUSEWHEEL_FLIPPED) ? -1.0f : 1.0f;
      wheel_accum_[0] += wheel.x * direction;
      wheel_accum_[1] += wheel.y * direction;
      const uint64_t time_ms = SDL_NS_TO_MS(wheel.timestamp);
      for (int axis = 0; axis < 2; axis++) {
        const int32_t steps = int32_t(wheel_accum_[axis]);
        if (steps == 0) {
          continue;
        }
        wheel_accum_[axis] -= float(steps);
        pushEvent(std::make_unique<GHOST_EventWheel>(time_ms,
                                                     window_,
                                                     axis == 0 ? GHOST_kEventWheelAxisHorizontal :
                                                                 GHOST_kEventWheelAxisVertical,
                                                     steps));
      }
      break;
    }
    default:
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Stylus (S Pen)
 * \{ */

void GHOST_SystemAndroid::flushPenMotion()
{
  if (!pen_motion_pending_) {
    return;
  }
  pen_motion_pending_ = false;
  pushCursorMove(pen_motion_time_ms_, int32_t(cursor_[0]), int32_t(cursor_[1]), pen_tablet_);
}

void GHOST_SystemAndroid::processPenEvent(const SDL_Event &event)
{
  if (window_ == nullptr) {
    return;
  }
  const float pixel_density = SDL_GetWindowPixelDensity(window_->getSDLWindow());

  switch (event.type) {
    case SDL_EVENT_PEN_PROXIMITY_IN: {
      pen_tablet_.Active = GHOST_kTabletModeStylus;
      pen_tablet_.Pressure = 0.0f;
      break;
    }
    case SDL_EVENT_PEN_PROXIMITY_OUT: {
      pen_tablet_ = GHOST_TABLET_DATA_NONE;
      break;
    }
    case SDL_EVENT_PEN_AXIS: {
      const SDL_PenAxisEvent &axis = event.paxis;
      switch (axis.axis) {
        case SDL_PEN_AXIS_PRESSURE:
          pen_tablet_.Pressure = std::clamp(axis.value, 0.0f, 1.0f);
          break;
        case SDL_PEN_AXIS_XTILT:
          pen_tablet_.Xtilt = std::clamp(axis.value / 90.0f, -1.0f, 1.0f);
          break;
        case SDL_PEN_AXIS_YTILT:
          pen_tablet_.Ytilt = std::clamp(axis.value / 90.0f, -1.0f, 1.0f);
          break;
        default:
          break;
      }
      flushPenMotion();
      break;
    }
    case SDL_EVENT_PEN_MOTION: {
      const SDL_PenMotionEvent &motion = event.pmotion;
      if (pen_tablet_.Active == GHOST_kTabletModeNone) {
        pen_tablet_.Active = GHOST_kTabletModeStylus;
      }
      cursor_[0] = motion.x * pixel_density;
      cursor_[1] = motion.y * pixel_density;
      /* Sent with the pressure that follows (see #processEvent). */
      pen_motion_pending_ = true;
      pen_motion_time_ms_ = SDL_NS_TO_MS(motion.timestamp);
      break;
    }
    case SDL_EVENT_PEN_DOWN:
    case SDL_EVENT_PEN_UP: {
      const SDL_PenTouchEvent &touch = event.ptouch;
      pen_tablet_.Active = touch.eraser ? GHOST_kTabletModeEraser : GHOST_kTabletModeStylus;
      cursor_[0] = touch.x * pixel_density;
      cursor_[1] = touch.y * pixel_density;
      const uint64_t time_ms = SDL_NS_TO_MS(touch.timestamp);
      pushCursorMove(time_ms, int32_t(cursor_[0]), int32_t(cursor_[1]), pen_tablet_);
      pushButton(time_ms,
                 touch.down ? GHOST_kEventButtonDown : GHOST_kEventButtonUp,
                 GHOST_kButtonMaskLeft,
                 pen_tablet_);
      break;
    }
    case SDL_EVENT_PEN_BUTTON_DOWN:
    case SDL_EVENT_PEN_BUTTON_UP: {
      const SDL_PenButtonEvent &button_event = event.pbutton;
      /* The first barrel button is the right button, the second the middle button. */
      const GHOST_TButton button = (button_event.button == 1) ? GHOST_kButtonMaskRight :
                                                                GHOST_kButtonMaskMiddle;
      pushButton(SDL_NS_TO_MS(button_event.timestamp),
                 button_event.down ? GHOST_kEventButtonDown : GHOST_kEventButtonUp,
                 button,
                 pen_tablet_);
      break;
    }
    default:
      break;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Touch Gestures
 * \{ */

void GHOST_SystemAndroid::touchCenter(float r_center[2]) const
{
  r_center[0] = 0.0f;
  r_center[1] = 0.0f;
  if (touches_.empty()) {
    return;
  }
  for (const TouchPoint &touch : touches_) {
    r_center[0] += touch.xy[0];
    r_center[1] += touch.xy[1];
  }
  r_center[0] /= float(touches_.size());
  r_center[1] /= float(touches_.size());
}

float GHOST_SystemAndroid::touchDistance() const
{
  if (touches_.size() < 2) {
    return 0.0f;
  }
  return std::hypot(touches_[1].xy[0] - touches_[0].xy[0], touches_[1].xy[1] - touches_[0].xy[1]);
}

void GHOST_SystemAndroid::touchGestureBegin(uint64_t /*time_ms*/)
{
  touchCenter(gesture_center_);
  gesture_distance_ = touchDistance();
  gesture_travel_ = 0.0f;
  gesture_kind_ = GestureKind::Undecided;
  gesture_accum_[0] = gesture_accum_[1] = gesture_accum_[2] = 0.0f;

  /* Three finger drag pans (Shift + trackpad pan in the 3D viewport). */
  const bool use_shift = touches_.size() >= 3;
  if (use_shift != gesture_shift_held_) {
    gesture_shift_held_ = use_shift;
    pushKey(getMilliSeconds(),
            use_shift ? GHOST_kEventKeyDown : GHOST_kEventKeyUp,
            GHOST_kKeyLeftShift,
            false);
  }
}

void GHOST_SystemAndroid::touchGestureUpdate(uint64_t time_ms)
{
  float center[2];
  touchCenter(center);
  const float distance = touchDistance();
  const float density = getDensity();

  const float delta[2] = {center[0] - gesture_center_[0], center[1] - gesture_center_[1]};
  const float zoom = (gesture_distance_ > 0.0f && distance > 0.0f) ?
                         (distance / gesture_distance_ - 1.0f) :
                         0.0f;

  if (gesture_kind_ == GestureKind::Undecided) {
    /* The reference stays at the gesture start until the gesture is known. */
    gesture_travel_ = std::hypot(delta[0], delta[1]) / density;
    const float pinch_travel = std::fabs(distance - gesture_distance_) / density;
    if (touches_.size() == 2 && pinch_travel > TOUCH_GESTURE_DECIDE_DP &&
        pinch_travel > gesture_travel_)
    {
      gesture_kind_ = GestureKind::Zoom;
    }
    else if (gesture_travel_ > TOUCH_GESTURE_DECIDE_DP) {
      gesture_kind_ = GestureKind::Pan;
    }
    else {
      /* Wait until the gesture is known, keep the start as reference. */
      return;
    }
  }

  const int32_t x = int32_t(center[0]);
  const int32_t y = int32_t(center[1]);
  if (gesture_kind_ == GestureKind::Pan) {
    gesture_accum_[0] += delta[0] / density * TOUCH_PAN_SCALE;
    gesture_accum_[1] += delta[1] / density * TOUCH_PAN_SCALE;
    const int32_t dx = int32_t(gesture_accum_[0]);
    const int32_t dy = int32_t(gesture_accum_[1]);
    if (dx != 0 || dy != 0) {
      gesture_accum_[0] -= float(dx);
      gesture_accum_[1] -= float(dy);
      /* Trackpad deltas are the scroll amount, the inverse of the content motion. */
      pushTrackpad(time_ms, GHOST_kTrackpadEventScroll, x, y, -dx, -dy);
    }
  }
  else if (gesture_kind_ == GestureKind::Zoom) {
    gesture_accum_[2] += zoom * TOUCH_ZOOM_SCALE;
    const int32_t dz = int32_t(gesture_accum_[2]);
    if (dz != 0) {
      gesture_accum_[2] -= float(dz);
      pushTrackpad(time_ms, GHOST_kTrackpadEventMagnify, x, y, dz, 0);
    }
  }

  gesture_center_[0] = center[0];
  gesture_center_[1] = center[1];
  gesture_distance_ = distance;
}

void GHOST_SystemAndroid::touchGestureEnd(uint64_t /*time_ms*/)
{
  if (gesture_shift_held_) {
    gesture_shift_held_ = false;
    pushKey(getMilliSeconds(), GHOST_kEventKeyUp, GHOST_kKeyLeftShift, false);
  }
  gesture_kind_ = GestureKind::Undecided;
}

void GHOST_SystemAndroid::processFingerEvent(const SDL_TouchFingerEvent &event)
{
  if (window_ == nullptr) {
    return;
  }
  const uint64_t time_ms = SDL_NS_TO_MS(event.timestamp);
  const float xy[2] = {event.x * float(window_->getWidth()),
                       event.y * float(window_->getHeight())};
  const float density = getDensity();

  auto find_touch = [&](SDL_FingerID id) {
    return std::find_if(
        touches_.begin(), touches_.end(), [id](const TouchPoint &t) { return t.id == id; });
  };

  switch (event.type) {
    case SDL_EVENT_FINGER_DOWN: {
      touches_.push_back({event.fingerID, {xy[0], xy[1]}, {xy[0], xy[1]}});
      touch_max_fingers_ = std::max(touch_max_fingers_, int(touches_.size()));

      if (touches_.size() == 1) {
        touch_mode_ = TouchMode::Pending;
        touch_start_ms_ = time_ms;
        cursor_[0] = xy[0];
        cursor_[1] = xy[1];
        /* Move the cursor to the finger so buttons get highlighted. */
        pushCursorMove(time_ms, int32_t(xy[0]), int32_t(xy[1]), GHOST_TABLET_DATA_NONE);
      }
      else {
        if (touch_mode_ == TouchMode::Drag) {
          /* A second finger ends a drag. */
          pushButton(time_ms, GHOST_kEventButtonUp, GHOST_kButtonMaskLeft, GHOST_TABLET_DATA_NONE);
        }
        if (touch_mode_ != TouchMode::Gesture) {
          touch_start_ms_ = time_ms;
        }
        if (touch_mode_ != TouchMode::Ignore) {
          touch_mode_ = TouchMode::Gesture;
          touchGestureBegin(time_ms);
        }
      }
      break;
    }

    case SDL_EVENT_FINGER_MOTION: {
      auto it = find_touch(event.fingerID);
      if (it == touches_.end()) {
        return;
      }
      it->xy[0] = xy[0];
      it->xy[1] = xy[1];

      switch (touch_mode_) {
        case TouchMode::Pending: {
          const float travel = std::hypot(xy[0] - it->start_xy[0], xy[1] - it->start_xy[1]) /
                               density;
          if (travel > TOUCH_SLOP_DP) {
            touch_mode_ = TouchMode::Drag;
            /* Press where the finger went down, then move. */
            pushButton(time_ms,
                       GHOST_kEventButtonDown,
                       GHOST_kButtonMaskLeft,
                       GHOST_TABLET_DATA_NONE);
            cursor_[0] = xy[0];
            cursor_[1] = xy[1];
            pushCursorMove(time_ms, int32_t(xy[0]), int32_t(xy[1]), GHOST_TABLET_DATA_NONE);
          }
          break;
        }
        case TouchMode::Drag: {
          cursor_[0] = xy[0];
          cursor_[1] = xy[1];
          pushCursorMove(time_ms, int32_t(xy[0]), int32_t(xy[1]), GHOST_TABLET_DATA_NONE);
          break;
        }
        case TouchMode::Gesture: {
          touchGestureUpdate(time_ms);
          break;
        }
        default:
          break;
      }
      break;
    }

    case SDL_EVENT_FINGER_UP:
    case SDL_EVENT_FINGER_CANCELED: {
      auto it = find_touch(event.fingerID);
      if (it == touches_.end()) {
        return;
      }
      const bool canceled = (event.type == SDL_EVENT_FINGER_CANCELED);

      switch (touch_mode_) {
        case TouchMode::Pending: {
          if (!canceled) {
            /* Tap: click. */
            pushButton(time_ms,
                       GHOST_kEventButtonDown,
                       GHOST_kButtonMaskLeft,
                       GHOST_TABLET_DATA_NONE);
            pushButton(
                time_ms, GHOST_kEventButtonUp, GHOST_kButtonMaskLeft, GHOST_TABLET_DATA_NONE);
          }
          break;
        }
        case TouchMode::Drag: {
          cursor_[0] = xy[0];
          cursor_[1] = xy[1];
          pushCursorMove(time_ms, int32_t(xy[0]), int32_t(xy[1]), GHOST_TABLET_DATA_NONE);
          pushButton(time_ms, GHOST_kEventButtonUp, GHOST_kButtonMaskLeft, GHOST_TABLET_DATA_NONE);
          break;
        }
        case TouchMode::Gesture: {
          if (touches_.size() == 1 || canceled) {
            const bool is_tap = !canceled && touch_max_fingers_ == 2 &&
                                gesture_kind_ == GestureKind::Undecided &&
                                gesture_travel_ < TOUCH_TWO_FINGER_TAP_SLOP_DP &&
                                (time_ms - touch_start_ms_) < TOUCH_TWO_FINGER_TAP_MS;
            touchGestureEnd(time_ms);
            if (is_tap) {
              /* Two finger tap: right click (context menu). */
              float center[2];
              touchCenter(center);
              cursor_[0] = center[0];
              cursor_[1] = center[1];
              pushCursorMove(
                  time_ms, int32_t(center[0]), int32_t(center[1]), GHOST_TABLET_DATA_NONE);
              pushButton(time_ms,
                         GHOST_kEventButtonDown,
                         GHOST_kButtonMaskRight,
                         GHOST_TABLET_DATA_NONE);
              pushButton(time_ms,
                         GHOST_kEventButtonUp,
                         GHOST_kButtonMaskRight,
                         GHOST_TABLET_DATA_NONE);
            }
          }
          break;
        }
        default:
          break;
      }

      touches_.erase(it);
      if (touches_.empty() || canceled) {
        touches_.clear();
        touch_mode_ = TouchMode::None;
        touch_max_fingers_ = 0;
      }
      else if (touch_mode_ == TouchMode::Gesture) {
        /* Restart with the remaining fingers as reference. */
        touchGestureBegin(time_ms);
      }
      break;
    }
    default:
      break;
  }
}

int64_t GHOST_SystemAndroid::touchTimerTimeout(uint64_t now_ms) const
{
  if (touch_mode_ != TouchMode::Pending) {
    return -1;
  }
  const uint64_t deadline = touch_start_ms_ + TOUCH_LONG_PRESS_MS;
  return (deadline > now_ms) ? int64_t(deadline - now_ms) : 0;
}

bool GHOST_SystemAndroid::processTouchTimers(uint64_t now_ms)
{
  if (touch_mode_ != TouchMode::Pending || now_ms < touch_start_ms_ + TOUCH_LONG_PRESS_MS) {
    return false;
  }
  /* Long press: right click (context menu). */
  touch_mode_ = TouchMode::Ignore;
  pushButton(now_ms, GHOST_kEventButtonDown, GHOST_kButtonMaskRight, GHOST_TABLET_DATA_NONE);
  pushButton(now_ms, GHOST_kEventButtonUp, GHOST_kButtonMaskRight, GHOST_TABLET_DATA_NONE);
  return true;
}

/** \} */

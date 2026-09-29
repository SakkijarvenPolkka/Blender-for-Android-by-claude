/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 */

#include "GHOST_WindowAndroid.hh"
#include "GHOST_SystemAndroid.hh"

#include "GHOST_ContextNone.hh"
#include "GHOST_utildefines.hh"

#include <android/native_window_jni.h>
#include <jni.h>

#include <cstdlib>

/**
 * A new reference to the native window of the activity's surface (`SDLActivity.getNativeSurface`),
 * null when there is no valid surface.
 *
 * SDL's #SDL_PROP_WINDOW_ANDROID_WINDOW_POINTER isn't used: SDL releases the window when the
 * surface is destroyed (on the UI thread) without clearing the property.
 */
static ANativeWindow *activity_native_window_acquire()
{
  JNIEnv *env = static_cast<JNIEnv *>(SDL_GetAndroidJNIEnv());
  if (env == nullptr) {
    return nullptr;
  }
  ANativeWindow *native_window = nullptr;
  jclass activity_class = env->FindClass("org/libsdl/app/SDLActivity");
  if (activity_class) {
    jmethodID method = env->GetStaticMethodID(
        activity_class, "getNativeSurface", "()Landroid/view/Surface;");
    if (method) {
      jobject surface = env->CallStaticObjectMethod(activity_class, method);
      if (surface) {
        /* Null when the surface has been released. */
        native_window = ANativeWindow_fromSurface(env, surface);
        env->DeleteLocalRef(surface);
      }
    }
    env->DeleteLocalRef(activity_class);
  }
  if (env->ExceptionCheck()) {
    env->ExceptionClear();
  }
  return native_window;
}

GHOST_WindowAndroid::GHOST_WindowAndroid(GHOST_SystemAndroid *system,
                                         const char *title,
                                         uint32_t width,
                                         uint32_t height,
                                         GHOST_TWindowState state,
                                         GHOST_TDrawingContextType type,
                                         const GHOST_ContextParams &context_params,
                                         const GHOST_GPUDevice &preferred_device,
                                         const bool exclusive)
    : GHOST_Window(width, height, state, context_params, exclusive),
      system_(system),
      title_(title ? title : ""),
      preferred_device_(preferred_device)
{
  /* The activity has exactly one full-screen surface, the requested size is ignored. */
  SDL_WindowFlags flags = SDL_WINDOW_FULLSCREEN | SDL_WINDOW_RESIZABLE |
                          SDL_WINDOW_HIGH_PIXEL_DENSITY;
  if (type == GHOST_kDrawingContextTypeVulkan) {
    flags |= SDL_WINDOW_VULKAN;
  }
  sdl_win_ = SDL_CreateWindow(title_.c_str(), int(width), int(height), flags);
  if (sdl_win_ == nullptr) {
    return;
  }
  updateSize();
  /* The application only starts once the activity has a surface. */
  setSurfaceAvailable(true);

  if (setDrawingContextType(type) == GHOST_kSuccess) {
    valid_setup_ = true;
  }
}

GHOST_WindowAndroid::~GHOST_WindowAndroid()
{
  if (text_input_mode_ != TextInputMode::None) {
    SDL_StopTextInput(sdl_win_);
  }
  if (custom_cursor_) {
    SDL_DestroyCursor(custom_cursor_);
  }
  releaseNativeHandles();
  if (native_window_) {
    ANativeWindow_release(native_window_);
  }
  if (sdl_win_) {
    SDL_DestroyWindow(sdl_win_);
  }
}

bool GHOST_WindowAndroid::updateSize()
{
  int width = 0, height = 0;
  SDL_GetWindowSizeInPixels(sdl_win_, &width, &height);
  const bool size_changed = (width != size_[0]) || (height != size_[1]);
  size_[0] = width;
  size_[1] = height;
#ifdef WITH_VULKAN_BACKEND
  vulkan_window_info_.size[0] = width;
  vulkan_window_info_.size[1] = height;
#endif
  return size_changed;
}

void GHOST_WindowAndroid::setSurfaceAvailable(const bool available)
{
  /* The Vulkan surface keeps its own reference, releasing this one is always safe. */
  if (native_window_) {
    ANativeWindow_release(native_window_);
    native_window_ = nullptr;
  }
  if (available) {
    native_window_ = activity_native_window_acquire();
  }
#ifdef WITH_VULKAN_BACKEND
  vulkan_window_info_.native_window = native_window_;
  /* Recreate the Vulkan surface even when the same window is returned. */
  vulkan_window_info_.generation++;
#endif
}

GHOST_Context *GHOST_WindowAndroid::newDrawingContext(GHOST_TDrawingContextType type)
{
  switch (type) {
#ifdef WITH_VULKAN_BACKEND
    case GHOST_kDrawingContextTypeVulkan: {
      GHOST_Context *context = new GHOST_ContextVK(
          want_context_params_, &vulkan_window_info_, 1, 2, preferred_device_);
      if (context->initializeDrawingContext()) {
        return context;
      }
      delete context;
      return nullptr;
    }
#endif
    case GHOST_kDrawingContextTypeNone: {
      GHOST_Context *context = new GHOST_ContextNone(want_context_params_);
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

bool GHOST_WindowAndroid::getValid() const
{
  return GHOST_Window::getValid() && valid_setup_;
}

GHOST_TSuccess GHOST_WindowAndroid::invalidate()
{
  if (!invalid_window_) {
    system_->addDirtyWindow(this);
    invalid_window_ = true;
  }
  return GHOST_kSuccess;
}

void GHOST_WindowAndroid::setTitle(const char *title)
{
  title_ = title ? title : "";
}

std::string GHOST_WindowAndroid::getTitle() const
{
  return title_;
}

void GHOST_WindowAndroid::getWindowBounds(GHOST_Rect &bounds) const
{
  getClientBounds(bounds);
}

void GHOST_WindowAndroid::getClientBounds(GHOST_Rect &bounds) const
{
  bounds.l_ = 0;
  bounds.t_ = 0;
  bounds.r_ = size_[0];
  bounds.b_ = size_[1];
}

GHOST_TSuccess GHOST_WindowAndroid::setClientWidth(uint32_t /*width*/)
{
  return GHOST_kFailure;
}

GHOST_TSuccess GHOST_WindowAndroid::setClientHeight(uint32_t /*height*/)
{
  return GHOST_kFailure;
}

GHOST_TSuccess GHOST_WindowAndroid::setClientSize(uint32_t /*width*/, uint32_t /*height*/)
{
  return GHOST_kFailure;
}

void GHOST_WindowAndroid::screenToClient(int32_t inX,
                                         int32_t inY,
                                         int32_t &outX,
                                         int32_t &outY) const
{
  /* The window always covers the whole screen. */
  outX = inX;
  outY = inY;
}

void GHOST_WindowAndroid::clientToScreen(int32_t inX,
                                         int32_t inY,
                                         int32_t &outX,
                                         int32_t &outY) const
{
  outX = inX;
  outY = inY;
}

GHOST_TSuccess GHOST_WindowAndroid::setState(GHOST_TWindowState state)
{
  if (state == GHOST_kWindowStateMinimized) {
    SDL_MinimizeWindow(sdl_win_);
  }
  return GHOST_kSuccess;
}

GHOST_TWindowState GHOST_WindowAndroid::getState() const
{
  const SDL_WindowFlags flags = SDL_GetWindowFlags(sdl_win_);
  if (flags & SDL_WINDOW_MINIMIZED) {
    return GHOST_kWindowStateMinimized;
  }
  return GHOST_kWindowStateFullScreen;
}

uint16_t GHOST_WindowAndroid::getDPIHint()
{
  /* One Blender UI pixel (at 1.0 resolution scale) is one Android "density independent pixel",
   * the resolution scale in the preferences can be used to make the UI smaller or larger. */
  float scale = SDL_GetWindowDisplayScale(sdl_win_);
  if (scale <= 0.0f) {
    scale = 1.0f;
  }
  if (const char *env_scale = std::getenv("BLENDER_ANDROID_UI_SCALE")) {
    const float value = float(std::atof(env_scale));
    if (value > 0.1f && value < 10.0f) {
      scale *= value;
    }
  }
  return uint16_t(96.0f * scale);
}

/* -------------------------------------------------------------------- */
/** \name Text Input (IME & Virtual Keyboard)
 * \{ */

void GHOST_WindowAndroid::startTextInput()
{
  SDL_PropertiesID props = SDL_CreateProperties();
  SDL_SetNumberProperty(props, SDL_PROP_TEXTINPUT_TYPE_NUMBER, SDL_TEXTINPUT_TYPE_TEXT);
  SDL_SetNumberProperty(props, SDL_PROP_TEXTINPUT_CAPITALIZATION_NUMBER, SDL_CAPITALIZE_NONE);
  SDL_SetBooleanProperty(props, SDL_PROP_TEXTINPUT_AUTOCORRECT_BOOLEAN, false);
  SDL_SetBooleanProperty(props, SDL_PROP_TEXTINPUT_MULTILINE_BOOLEAN, false);
  SDL_StartTextInputWithProperties(sdl_win_, props);
  SDL_DestroyProperties(props);
}

void GHOST_WindowAndroid::syncTextInputMode()
{
  /* SDL stops text input itself when the virtual keyboard loses focus. */
  text_input_mode_ = getTextInputMode();
}

#ifdef WITH_INPUT_IME
void GHOST_WindowAndroid::beginIME(
    int32_t x, int32_t y, int32_t w, int32_t h, bool /*completed*/)
{
  syncTextInputMode();
  SDL_Rect rect = {x, y, w > 0 ? w : 1, h > 0 ? h : 1};
  SDL_SetTextInputArea(sdl_win_, &rect, 0);
  if (text_input_mode_ == TextInputMode::None) {
    startTextInput();
  }
  text_input_mode_ = TextInputMode::IME;
}

void GHOST_WindowAndroid::endIME()
{
  syncTextInputMode();
  if (text_input_mode_ == TextInputMode::IME) {
    SDL_StopTextInput(sdl_win_);
    text_input_mode_ = TextInputMode::None;
  }
}
#endif /* WITH_INPUT_IME */

void GHOST_WindowAndroid::toggleVirtualKeyboard()
{
  syncTextInputMode();
  if (text_input_mode_ == TextInputMode::None) {
    SDL_Rect rect = {0, 0, 1, 1};
    SDL_SetTextInputArea(sdl_win_, &rect, 0);
    startTextInput();
    text_input_mode_ = TextInputMode::Hotkeys;
  }
  else {
    SDL_StopTextInput(sdl_win_);
    text_input_mode_ = TextInputMode::None;
  }
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Cursor
 *
 * Only visible with a mouse or when a stylus hovers the screen.
 * \{ */

static bool ghost_cursor_to_sdl(GHOST_TStandardCursor shape, SDL_SystemCursor &r_cursor)
{
  switch (shape) {
    case GHOST_kStandardCursorDefault:
    case GHOST_kStandardCursorRightArrow:
    case GHOST_kStandardCursorLeftArrow:
      r_cursor = SDL_SYSTEM_CURSOR_DEFAULT;
      return true;
    case GHOST_kStandardCursorWait:
      r_cursor = SDL_SYSTEM_CURSOR_WAIT;
      return true;
    case GHOST_kStandardCursorText:
      r_cursor = SDL_SYSTEM_CURSOR_TEXT;
      return true;
    case GHOST_kStandardCursorCrosshair:
      r_cursor = SDL_SYSTEM_CURSOR_CROSSHAIR;
      return true;
    case GHOST_kStandardCursorMove:
    case GHOST_kStandardCursorNSEWScroll:
      r_cursor = SDL_SYSTEM_CURSOR_MOVE;
      return true;
    case GHOST_kStandardCursorNSScroll:
    case GHOST_kStandardCursorUpDown:
    case GHOST_kStandardCursorHorizontalSplit:
      r_cursor = SDL_SYSTEM_CURSOR_NS_RESIZE;
      return true;
    case GHOST_kStandardCursorEWScroll:
    case GHOST_kStandardCursorLeftRight:
    case GHOST_kStandardCursorVerticalSplit:
      r_cursor = SDL_SYSTEM_CURSOR_EW_RESIZE;
      return true;
    case GHOST_kStandardCursorStop:
    case GHOST_kStandardCursorDestroy:
      r_cursor = SDL_SYSTEM_CURSOR_NOT_ALLOWED;
      return true;
    case GHOST_kStandardCursorTopSide:
      r_cursor = SDL_SYSTEM_CURSOR_N_RESIZE;
      return true;
    case GHOST_kStandardCursorBottomSide:
      r_cursor = SDL_SYSTEM_CURSOR_S_RESIZE;
      return true;
    case GHOST_kStandardCursorLeftSide:
      r_cursor = SDL_SYSTEM_CURSOR_W_RESIZE;
      return true;
    case GHOST_kStandardCursorRightSide:
      r_cursor = SDL_SYSTEM_CURSOR_E_RESIZE;
      return true;
    case GHOST_kStandardCursorTopLeftCorner:
      r_cursor = SDL_SYSTEM_CURSOR_NW_RESIZE;
      return true;
    case GHOST_kStandardCursorTopRightCorner:
      r_cursor = SDL_SYSTEM_CURSOR_NE_RESIZE;
      return true;
    case GHOST_kStandardCursorBottomRightCorner:
      r_cursor = SDL_SYSTEM_CURSOR_SE_RESIZE;
      return true;
    case GHOST_kStandardCursorBottomLeftCorner:
      r_cursor = SDL_SYSTEM_CURSOR_SW_RESIZE;
      return true;
    case GHOST_kStandardCursorHandPoint:
      r_cursor = SDL_SYSTEM_CURSOR_POINTER;
      return true;
    default:
      /* Blender uses its own cursor images for the remaining shapes. */
      return false;
  }
}

static SDL_Cursor *ghost_system_cursor_get(SDL_SystemCursor id)
{
  static SDL_Cursor *cursors[SDL_SYSTEM_CURSOR_COUNT] = {nullptr};
  if (cursors[id] == nullptr) {
    cursors[id] = SDL_CreateSystemCursor(id);
  }
  return cursors[id];
}

GHOST_TSuccess GHOST_WindowAndroid::setWindowCursorShape(GHOST_TStandardCursor shape)
{
  SDL_SystemCursor id;
  if (!ghost_cursor_to_sdl(shape, id)) {
    return GHOST_kFailure;
  }
  SDL_Cursor *cursor = ghost_system_cursor_get(id);
  if (cursor == nullptr) {
    return GHOST_kFailure;
  }
  SDL_SetCursor(cursor);
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowAndroid::hasCursorShape(GHOST_TStandardCursor shape)
{
  SDL_SystemCursor id;
  return ghost_cursor_to_sdl(shape, id) ? GHOST_kSuccess : GHOST_kFailure;
}

GHOST_TSuccess GHOST_WindowAndroid::setWindowCustomCursorShape(const uint8_t *bitmap,
                                                               const uint8_t *mask,
                                                               const int size[2],
                                                               const int hot_spot[2],
                                                               bool /*can_invert_color*/)
{
  /* Convert Blender's 1 bit per pixel cursors (LSB first) to ARGB. */
  const int w = size[0], h = size[1];
  const int row_bytes = (w + 7) / 8;
  SDL_Surface *surface = SDL_CreateSurface(w, h, SDL_PIXELFORMAT_ARGB8888);
  if (surface == nullptr) {
    return GHOST_kFailure;
  }
  for (int y = 0; y < h; y++) {
    uint32_t *pixel = reinterpret_cast<uint32_t *>(static_cast<uint8_t *>(surface->pixels) +
                                                   y * surface->pitch);
    for (int x = 0; x < w; x++) {
      const int byte = y * row_bytes + x / 8;
      const int bit = 1 << (x % 8);
      const bool is_set = (bitmap[byte] & bit) != 0;
      const bool is_mask = (mask[byte] & bit) != 0;
      pixel[x] = is_mask ? (is_set ? 0xFFFFFFFF : 0xFF000000) : 0x00000000;
    }
  }
  SDL_Cursor *cursor = SDL_CreateColorCursor(surface, hot_spot[0], hot_spot[1]);
  SDL_DestroySurface(surface);
  if (cursor == nullptr) {
    return GHOST_kFailure;
  }
  if (custom_cursor_) {
    SDL_DestroyCursor(custom_cursor_);
  }
  custom_cursor_ = cursor;
  SDL_SetCursor(custom_cursor_);
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowAndroid::setWindowCursorVisibility(bool visible)
{
  if (visible) {
    SDL_ShowCursor();
  }
  else {
    SDL_HideCursor();
  }
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_WindowAndroid::setWindowCursorGrab(GHOST_TGrabCursorMode mode)
{
  /* The pointer can't be warped on Android, use pointer capture (relative motion) instead.
   * The system accumulates the relative motion into the reported cursor position. */
  const bool relative = ELEM(mode, GHOST_kGrabWrap, GHOST_kGrabHide);
  system_->setRelativeMouseMode(relative);
  SDL_SetWindowRelativeMouseMode(sdl_win_, relative);
  return GHOST_kSuccess;
}

bool GHOST_WindowAndroid::getCursorGrabUseSoftwareDisplay()
{
  /* The system cursor is hidden while the pointer is captured. */
  return cursor_grab_ == GHOST_kGrabWrap;
}

/** \} */

/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Android window, backed by the single full-screen `SDL_Window` of the activity.
 */

#pragma once

#include "GHOST_Window.hh"

#ifdef WITH_VULKAN_BACKEND
#  include "GHOST_ContextVK.hh"
#endif

#include <SDL3/SDL.h>

#include <android/native_window.h>

#include <string>

class GHOST_SystemAndroid;

class GHOST_WindowAndroid : public GHOST_Window {
 public:
  GHOST_WindowAndroid(GHOST_SystemAndroid *system,
                      const char *title,
                      uint32_t width,
                      uint32_t height,
                      GHOST_TWindowState state,
                      GHOST_TDrawingContextType type,
                      const GHOST_ContextParams &context_params,
                      const GHOST_GPUDevice &preferred_device,
                      bool exclusive);

  ~GHOST_WindowAndroid() override;

  SDL_Window *getSDLWindow() const
  {
    return sdl_win_;
  }

  bool getValid() const override;

  void getWindowBounds(GHOST_Rect &bounds) const override;
  void getClientBounds(GHOST_Rect &bounds) const override;

  GHOST_TSuccess invalidate() override;
  void validate()
  {
    invalid_window_ = false;
  }

  /**
   * Update the cached size from SDL.
   * \return true when the size changed.
   */
  bool updateSize();

  /**
   * Take a reference to the activity's current native window (activity resumed), or release it
   * (activity paused: the system destroys the surface at any time, even while the next frame is
   * drawn, SDL doesn't keep the window alive for Vulkan).
   */
  void setSurfaceAvailable(bool available);

  /** Size of the drawable in pixels. */
  int getWidth() const
  {
    return size_[0];
  }
  int getHeight() const
  {
    return size_[1];
  }

  uint16_t getDPIHint() override;

#ifdef WITH_INPUT_IME
  void beginIME(int32_t x, int32_t y, int32_t w, int32_t h, bool completed) override;
  void endIME() override;
#endif

  enum class TextInputMode {
    None,
    /** Editing a text field (IME composition & committed text). */
    IME,
    /** Virtual keyboard opened by the user, typed characters are sent as key presses. */
    Hotkeys,
  };
  /** The virtual keyboard can also be hidden by the system (e.g. "back"), check SDL's state. */
  TextInputMode getTextInputMode() const
  {
    return SDL_TextInputActive(sdl_win_) ? text_input_mode_ : TextInputMode::None;
  }
  /** Show or hide the virtual keyboard for typing shortcuts. */
  void toggleVirtualKeyboard();

 protected:
  bool getCursorGrabUseSoftwareDisplay() override;

  GHOST_Context *newDrawingContext(GHOST_TDrawingContextType type) override;

  GHOST_TSuccess setWindowCursorGrab(GHOST_TGrabCursorMode mode) override;
  GHOST_TSuccess setWindowCursorShape(GHOST_TStandardCursor shape) override;
  GHOST_TSuccess hasCursorShape(GHOST_TStandardCursor shape) override;
  GHOST_TSuccess setWindowCustomCursorShape(const uint8_t *bitmap,
                                            const uint8_t *mask,
                                            const int size[2],
                                            const int hot_spot[2],
                                            bool can_invert_color) override;
  GHOST_TSuccess setWindowCursorVisibility(bool visible) override;

  void setTitle(const char *title) override;
  std::string getTitle() const override;

  GHOST_TSuccess setClientWidth(uint32_t width) override;
  GHOST_TSuccess setClientHeight(uint32_t height) override;
  GHOST_TSuccess setClientSize(uint32_t width, uint32_t height) override;

  void screenToClient(int32_t inX, int32_t inY, int32_t &outX, int32_t &outY) const override;
  void clientToScreen(int32_t inX, int32_t inY, int32_t &outX, int32_t &outY) const override;

  GHOST_TSuccess setState(GHOST_TWindowState state) override;
  GHOST_TWindowState getState() const override;
  GHOST_TSuccess setOrder(GHOST_TWindowOrder /*order*/) override
  {
    return GHOST_kSuccess;
  }

 private:
  GHOST_SystemAndroid *system_;
  SDL_Window *sdl_win_ = nullptr;
  SDL_Cursor *custom_cursor_ = nullptr;
  bool valid_setup_ = false;
  bool invalid_window_ = false;
  TextInputMode text_input_mode_ = TextInputMode::None;
  void startTextInput();
  void syncTextInputMode();
  std::string title_;
  int size_[2] = {0, 0};
  GHOST_GPUDevice preferred_device_;

  /** Owned reference (#ANativeWindow_acquire), null while the activity is in the background. */
  ANativeWindow *native_window_ = nullptr;

#ifdef WITH_VULKAN_BACKEND
  GHOST_ContextVK_AndroidWindowInfo vulkan_window_info_;
#endif
};

/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Android system, uses SDL3 for the activity life-cycle, surfaces and input.
 *
 * Input mapping:
 * - Mouse & keyboard (Samsung DeX, Bluetooth/USB): used as on the desktop.
 * - Stylus (S Pen): left button with pressure & tilt, barrel button is the right button.
 * - Touch, one finger: moves the cursor, tap is a click, drag is a left button drag,
 *   long press is a right click (context menu).
 * - Touch, two fingers: drag is a trackpad pan (orbit in the 3D viewport, pan in 2D editors),
 *   pinch is a trackpad zoom, a quick tap is a right click.
 * - Touch, three fingers: drag is a trackpad pan with Shift held (pan in the 3D viewport).
 * - Android "back" is the escape key.
 */

#pragma once

#include "../GHOST_Android.hh"
#include "../GHOST_Types.hh"
#include "GHOST_Buttons.hh"
#include "GHOST_Event.hh"
#include "GHOST_System.hh"

#include <SDL3/SDL.h>

#include <vector>

class GHOST_WindowAndroid;

class GHOST_SystemAndroid : public GHOST_System {
 public:
  GHOST_SystemAndroid();
  ~GHOST_SystemAndroid() override;

  bool processEvents(bool waitForEvent) override;

  bool setConsoleWindowState(GHOST_TConsoleWindowState /*action*/) override
  {
    return false;
  }

  GHOST_TSuccess getModifierKeys(GHOST_ModifierKeys &keys) const override;
  GHOST_TSuccess getButtons(GHOST_Buttons &buttons) const override;
  GHOST_TCapabilityFlag getCapabilities() const override;

  char *getClipboard(bool selection) const override;
  void putClipboard(const char *buffer, bool selection) const override;

  uint64_t getMilliSeconds() const override;
  uint8_t getNumDisplays() const override;

  GHOST_TSuccess getCursorPosition(int32_t &x, int32_t &y) const override;
  GHOST_TSuccess setCursorPosition(int32_t x, int32_t y) override;

  void getAllDisplayDimensions(uint32_t &width, uint32_t &height) const override;
  void getMainDisplayDimensions(uint32_t &width, uint32_t &height) const override;

  GHOST_IContext *createOffscreenContext(GHOST_GPUSettings gpu_settings) override;
  GHOST_TSuccess disposeContext(GHOST_IContext *context) override;

  void addDirtyWindow(GHOST_WindowAndroid *window);
  void setRelativeMouseMode(bool relative);

 private:
  GHOST_TSuccess init() override;

  GHOST_IWindow *createWindow(const char *title,
                              int32_t left,
                              int32_t top,
                              uint32_t width,
                              uint32_t height,
                              GHOST_TWindowState state,
                              GHOST_GPUSettings gpu_settings,
                              const bool exclusive = false,
                              const bool is_dialog = false,
                              const GHOST_IWindow *parent_window = nullptr) override;

  void processEvent(const SDL_Event &event);
  void processKeyEvent(const SDL_KeyboardEvent &event);
  void processTextEvent(const SDL_Event &event);
  void processMouseEvent(const SDL_Event &event);
  void processPenEvent(const SDL_Event &event);
  void processFingerEvent(const SDL_TouchFingerEvent &event);
  void processLifecycleEvent(const SDL_Event &event);
  void processDropEvent(const char *filepath, uint64_t time_ms);
  /** Send typed characters as key presses (virtual keyboard opened for shortcuts). */
  void processHotkeyText(const char *text, uint64_t time_ms);

  /** Returns true when an event was generated. */
  bool processTouchTimers(uint64_t now_ms);
  /** Milliseconds until the next touch timer fires, or -1. */
  int64_t touchTimerTimeout(uint64_t now_ms) const;

  void pushCursorMove(uint64_t time_ms, int32_t x, int32_t y, const GHOST_TabletData &tablet);
  void pushButton(uint64_t time_ms,
                  GHOST_TEventType type,
                  GHOST_TButton button,
                  const GHOST_TabletData &tablet);
  void pushKey(uint64_t time_ms, GHOST_TEventType type, GHOST_TKey key, bool is_repeat);
  void pushTrackpad(uint64_t time_ms,
                    GHOST_TTrackpadEventSubTypes subtype,
                    int32_t x,
                    int32_t y,
                    int32_t dx,
                    int32_t dy);
  bool generateWindowExposeEvents();
  /** Pixels per "density independent pixel". */
  float getDensity() const;

  GHOST_WindowAndroid *window_ = nullptr;
  std::vector<GHOST_WindowAndroid *> dirty_windows_;

  /** Cursor position in window pixels (can go outside the window during relative motion). */
  float cursor_[2] = {0.0f, 0.0f};
  bool relative_mouse_mode_ = false;
  GHOST_Buttons buttons_;
  /** Fractional mouse wheel motion. */
  float wheel_accum_[2] = {0.0f, 0.0f};

  /* Stylus state. */
  GHOST_TabletData pen_tablet_ = GHOST_TABLET_DATA_NONE;

  /* Touch state. */
  struct TouchPoint {
    SDL_FingerID id;
    float xy[2];
    float start_xy[2];
  };
  enum class TouchMode {
    /** No fingers. */
    None,
    /** One finger down, not decided yet if it's a tap, drag or long press. */
    Pending,
    /** One finger drag (left button held). */
    Drag,
    /** Long press, right click was sent, ignore until all fingers are released. */
    Ignore,
    /** Multi-finger gesture. */
    Gesture,
  };
  enum class GestureKind { Undecided, Pan, Zoom };
  std::vector<TouchPoint> touches_;
  TouchMode touch_mode_ = TouchMode::None;
  GestureKind gesture_kind_ = GestureKind::Undecided;
  uint64_t touch_start_ms_ = 0;
  int touch_max_fingers_ = 0;
  float gesture_center_[2] = {0.0f, 0.0f};
  float gesture_distance_ = 0.0f;
  float gesture_travel_ = 0.0f;
  float gesture_accum_[3] = {0.0f, 0.0f, 0.0f};
  bool gesture_shift_held_ = false;

  /** An IME composition is in progress. */
  bool ime_is_composing_ = false;

  void touchGestureBegin(uint64_t time_ms);
  void touchGestureUpdate(uint64_t time_ms);
  void touchGestureEnd(uint64_t time_ms);
  void touchCenter(float r_center[2]) const;
  float touchDistance() const;
};

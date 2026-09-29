package com.github.sakkijarvenpolkka.blender;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.TextView;

import org.blender.ghost.GhostAndroid;
import org.libsdl.app.SDLActivity;

/**
 * Floating tool-bar for touch screens without a keyboard: modifier keys (sticky), common
 * shortcuts, 3D view presets and the virtual keyboard. Key presses are sent to SDL as if they
 * came from a hardware keyboard.
 *
 * The handle on the left moves the tool-bar (drag) or collapses it (tap).
 */
@SuppressLint("ViewConstructor")
final class TouchToolbar extends LinearLayout {
    private static final int COLOR_BG = 0xCC2B2B2B;
    private static final int COLOR_BUTTON = 0xFF3D3D3D;
    private static final int COLOR_ACTIVE = 0xFF4772B3;
    private static final int COLOR_TEXT = 0xFFE6E6E6;

    private final float density;
    private final LinearLayout buttons;
    private final ModifierButton ctrl;
    private final ModifierButton shift;
    private final ModifierButton alt;

    TouchToolbar(Context context) {
        super(context);
        density = context.getResources().getDisplayMetrics().density;
        setOrientation(HORIZONTAL);
        setPadding(dp(4), dp(4), dp(4), dp(4));
        GradientDrawable background = new GradientDrawable();
        background.setColor(COLOR_BG);
        background.setCornerRadius(dp(8));
        setBackground(background);

        TextView handle = makeButton("☰");
        handle.setOnTouchListener(new HandleTouchListener());
        addView(handle);

        buttons = new LinearLayout(context);
        buttons.setOrientation(HORIZONTAL);
        addView(buttons);

        TextView keyboard = makeButton("⌨");
        keyboard.setContentDescription(context.getString(R.string.toolbar_keyboard));
        keyboard.setOnClickListener(v -> GhostAndroid.toggleVirtualKeyboard());
        buttons.addView(keyboard);

        buttons.addView(makeKeyButton("Esc", KeyEvent.KEYCODE_ESCAPE));
        buttons.addView(makeKeyButton("Tab", KeyEvent.KEYCODE_TAB));

        ctrl = new ModifierButton("Ctrl", KeyEvent.KEYCODE_CTRL_LEFT);
        shift = new ModifierButton("Shift", KeyEvent.KEYCODE_SHIFT_LEFT);
        alt = new ModifierButton("Alt", KeyEvent.KEYCODE_ALT_LEFT);
        buttons.addView(ctrl.view);
        buttons.addView(shift.view);
        buttons.addView(alt.view);

        TextView undo = makeButton("↶");
        undo.setContentDescription(context.getString(R.string.toolbar_undo));
        undo.setOnClickListener(v -> sendShortcut(KeyEvent.KEYCODE_Z, true, false));
        buttons.addView(undo);

        TextView redo = makeButton("↷");
        redo.setContentDescription(context.getString(R.string.toolbar_redo));
        redo.setOnClickListener(v -> sendShortcut(KeyEvent.KEYCODE_Z, true, true));
        buttons.addView(redo);

        buttons.addView(makeKeyButton("Del", KeyEvent.KEYCODE_FORWARD_DEL));

        TextView view = makeButton(context.getString(R.string.toolbar_view));
        view.setOnClickListener(this::showViewMenu);
        buttons.addView(view);
    }

    private int dp(float value) {
        return (int) (value * density + 0.5f);
    }

    private TextView makeButton(String label) {
        TextView button = new TextView(getContext());
        button.setText(label);
        button.setTextColor(COLOR_TEXT);
        button.setTextSize(14);
        button.setTypeface(Typeface.DEFAULT_BOLD);
        button.setGravity(android.view.Gravity.CENTER);
        button.setMinWidth(dp(40));
        button.setMinHeight(dp(36));
        button.setPadding(dp(8), dp(4), dp(8), dp(4));
        GradientDrawable background = new GradientDrawable();
        background.setColor(COLOR_BUTTON);
        background.setCornerRadius(dp(6));
        button.setBackground(background);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        params.setMargins(dp(2), 0, dp(2), 0);
        button.setLayoutParams(params);
        // Don't steal focus from SDL's surface (keyboard input).
        button.setFocusable(false);
        return button;
    }

    private TextView makeKeyButton(String label, int keycode) {
        TextView button = makeButton(label);
        button.setOnClickListener(v -> {
            SDLActivity.onNativeKeyDown(keycode);
            SDLActivity.onNativeKeyUp(keycode);
            releaseModifiers();
        });
        return button;
    }

    /** Press a key with Ctrl and optionally Shift held, respecting the sticky modifiers. */
    private void sendShortcut(int keycode, boolean withCtrl, boolean withShift) {
        boolean pressCtrl = withCtrl && !ctrl.active;
        boolean pressShift = withShift && !shift.active;
        if (pressCtrl) {
            SDLActivity.onNativeKeyDown(KeyEvent.KEYCODE_CTRL_LEFT);
        }
        if (pressShift) {
            SDLActivity.onNativeKeyDown(KeyEvent.KEYCODE_SHIFT_LEFT);
        }
        SDLActivity.onNativeKeyDown(keycode);
        SDLActivity.onNativeKeyUp(keycode);
        if (pressShift) {
            SDLActivity.onNativeKeyUp(KeyEvent.KEYCODE_SHIFT_LEFT);
        }
        if (pressCtrl) {
            SDLActivity.onNativeKeyUp(KeyEvent.KEYCODE_CTRL_LEFT);
        }
        releaseModifiers();
    }

    private void releaseModifiers() {
        ctrl.setActive(false);
        shift.setActive(false);
        alt.setActive(false);
    }

    private void showViewMenu(View anchor) {
        PopupMenu menu = new PopupMenu(getContext(), anchor);
        final int[][] entries = {
            /* label resource, key-code, ctrl */
            {R.string.view_front, KeyEvent.KEYCODE_NUMPAD_1, 0},
            {R.string.view_back, KeyEvent.KEYCODE_NUMPAD_1, 1},
            {R.string.view_right, KeyEvent.KEYCODE_NUMPAD_3, 0},
            {R.string.view_left, KeyEvent.KEYCODE_NUMPAD_3, 1},
            {R.string.view_top, KeyEvent.KEYCODE_NUMPAD_7, 0},
            {R.string.view_bottom, KeyEvent.KEYCODE_NUMPAD_7, 1},
            {R.string.view_camera, KeyEvent.KEYCODE_NUMPAD_0, 0},
            {R.string.view_ortho, KeyEvent.KEYCODE_NUMPAD_5, 0},
            {R.string.view_selected, KeyEvent.KEYCODE_NUMPAD_DOT, 0},
            {R.string.view_all, KeyEvent.KEYCODE_MOVE_HOME, 0},
        };
        for (int i = 0; i < entries.length; i++) {
            menu.getMenu().add(0, i, i, entries[i][0]);
        }
        menu.setOnMenuItemClickListener(item -> {
            int[] entry = entries[item.getItemId()];
            sendShortcut(entry[1], entry[2] != 0, false);
            return true;
        });
        menu.show();
    }

    /** Sticky modifier: tap to hold, tap again (or use another key) to release. */
    private final class ModifierButton {
        final TextView view;
        final int keycode;
        boolean active;

        ModifierButton(String label, int keycode) {
            this.keycode = keycode;
            view = makeButton(label);
            view.setOnClickListener(v -> setActive(!active));
        }

        void setActive(boolean value) {
            if (active == value) {
                return;
            }
            active = value;
            if (active) {
                SDLActivity.onNativeKeyDown(keycode);
            } else {
                SDLActivity.onNativeKeyUp(keycode);
            }
            ((GradientDrawable) view.getBackground()).setColor(active ? COLOR_ACTIVE : COLOR_BUTTON);
        }
    }

    /** Drag to move the tool-bar, tap to collapse/expand it. */
    private final class HandleTouchListener implements OnTouchListener {
        private float downX, downY, startX, startY;
        private boolean dragging;

        @Override
        public boolean onTouch(View v, MotionEvent event) {
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                    downX = event.getRawX();
                    downY = event.getRawY();
                    startX = getTranslationX();
                    startY = getTranslationY();
                    dragging = false;
                    return true;
                case MotionEvent.ACTION_MOVE: {
                    float dx = event.getRawX() - downX;
                    float dy = event.getRawY() - downY;
                    if (!dragging && Math.hypot(dx, dy) > dp(8)) {
                        dragging = true;
                    }
                    if (dragging) {
                        setTranslationX(startX + dx);
                        setTranslationY(startY + dy);
                    }
                    return true;
                }
                case MotionEvent.ACTION_UP:
                    if (!dragging) {
                        buttons.setVisibility(buttons.getVisibility() == VISIBLE ? GONE : VISIBLE);
                    }
                    return true;
                default:
                    return false;
            }
        }
    }
}

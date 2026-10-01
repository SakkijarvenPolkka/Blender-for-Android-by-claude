package com.github.sakkijarvenpolkka.blender;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.util.Log;
import android.view.Gravity;
import android.view.SurfaceHolder;
import android.view.WindowManager;
import android.widget.RelativeLayout;

import org.blender.ghost.GhostAndroid;
import org.libsdl.app.SDLActivity;
import org.libsdl.app.SDLSurface;

/**
 * Hosts Blender. SDL3 provides the surface, input and life-cycle handling,
 * `libblender.so` (with SDL linked statically) runs on SDL's main thread.
 */
public class BlenderActivity extends SDLActivity {
    private static final String TAG = "BlenderActivity";
    static final String EXTRA_BLEND_FILE = "blend_file";
    static final String PREF_UI_SCALE = "ui_scale";
    static final String PREF_AVOID_CUTOUT = "avoid_display_cutout";

    private TouchToolbar toolbar;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        SharedPreferences prefs = getSharedPreferences(LauncherActivity.PREFS, MODE_PRIVATE);
        // Must happen before Blender starts (on SDL's thread, after `super.onCreate`).
        BlenderPaths.setupEnvironment(this, prefs.getFloat(PREF_UI_SCALE, 0.0f));

        super.onCreate(savedInstanceState);

        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        if (mLayout instanceof RelativeLayout) {
            toolbar = new TouchToolbar(this);
            RelativeLayout.LayoutParams params = new RelativeLayout.LayoutParams(
                RelativeLayout.LayoutParams.WRAP_CONTENT, RelativeLayout.LayoutParams.WRAP_CONTENT);
            params.addRule(RelativeLayout.ALIGN_PARENT_TOP);
            params.addRule(RelativeLayout.CENTER_HORIZONTAL);
            params.topMargin = (int) (48 * getResources().getDisplayMetrics().density);
            mLayout.addView(toolbar, params);
            toolbar.setGravity(Gravity.CENTER);
        }
    }

    private int keepAliveCount = 0;

    /**
     * Keep Blender running in the background (called by Blender, see
     * `blender_android_keep_alive` in `creator_android.cc`). Requests are counted.
     */
    public void setKeepAlive(boolean enable) {
        runOnUiThread(() -> {
            keepAliveCount = Math.max(0, keepAliveCount + (enable ? 1 : -1));
            if (keepAliveCount > 0) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                        && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                           != PackageManager.PERMISSION_GRANTED) {
                    // The service runs without, but its notification (to return to Blender or
                    // notice that it's running) is only shown with the permission.
                    requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, 0);
                }
                try {
                    BackgroundService.start(this);
                } catch (RuntimeException e) {
                    Log.w(TAG, "Unable to start the background service", e);
                }
            } else {
                BackgroundService.stop(this);
            }
        });
    }

    @Override
    protected void onDestroy() {
        BackgroundService.stop(this);
        super.onDestroy();
    }

    /**
     * "Back" never closes Blender (it's escape once Blender runs, SDL would finish the activity
     * before that), the application goes to the background instead.
     */
    @Override
    public void onBackPressed() {
        moveTaskToBack(true);
    }

    @Override
    public void superOnBackPressed() {
        moveTaskToBack(true);
    }

    @Override
    protected SDLSurface createSDLSurface(Context context) {
        return new BlenderSurface(context);
    }

    /**
     * SDL's surface, also telling Blender when the surface is destroyed & created again: Blender
     * draws to it with Vulkan and must create a new Vulkan surface. SDL's life-cycle events don't
     * cover all cases (a pause & resume can cancel out before Blender processes events).
     */
    static final class BlenderSurface extends SDLSurface {
        /** The surface was destroyed, Blender must be told when there's a new one. */
        private boolean surfaceLost = false;

        BlenderSurface(Context context) {
            super(context);
        }

        @Override
        public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {
            super.surfaceChanged(holder, format, width, height);
            // Resizes are handled by SDL's window events.
            if (surfaceLost && mIsSurfaceReady) {
                surfaceLost = false;
                GhostAndroid.surfaceChanged(true);
            }
        }

        @Override
        public void surfaceDestroyed(SurfaceHolder holder) {
            super.surfaceDestroyed(holder);
            surfaceLost = true;
            GhostAndroid.surfaceChanged(false);
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String blendFile = intent.getStringExtra(EXTRA_BLEND_FILE);
        if (blendFile != null) {
            // Blender is already running, handle the file as if it was dropped into the window.
            GhostAndroid.openFile(blendFile);
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            applyDisplayCutoutMode();
        }
    }

    /**
     * SDL draws below the camera cut-out in full-screen mode, Blender's UI has no notion of
     * "safe areas", so by default keep the drawing area clear of it.
     */
    private void applyDisplayCutoutMode() {
        SharedPreferences prefs = getSharedPreferences(LauncherActivity.PREFS, MODE_PRIVATE);
        if (!prefs.getBoolean(PREF_AVOID_CUTOUT, true)) {
            return;
        }
        WindowManager.LayoutParams attributes = getWindow().getAttributes();
        if (attributes.layoutInDisplayCutoutMode != WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_NEVER) {
            attributes.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_NEVER;
            getWindow().setAttributes(attributes);
        }
    }

    @Override
    protected String[] getLibraries() {
        // SDL is linked statically into Blender.
        return new String[] {"blender"};
    }

    @Override
    protected String getMainSharedObject() {
        // Already loaded by `loadLibraries()`, the library isn't extracted from the APK so
        // refer to it by name.
        return "libblender.so";
    }

    @Override
    protected String[] getArguments() {
        String blendFile = getIntent() != null ? getIntent().getStringExtra(EXTRA_BLEND_FILE) : null;
        if (blendFile != null) {
            Log.i(TAG, "Opening " + blendFile);
            return new String[] {blendFile};
        }
        return new String[0];
    }
}

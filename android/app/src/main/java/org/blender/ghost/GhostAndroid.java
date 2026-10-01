package org.blender.ghost;

/**
 * Native functions of Blender's Android GHOST back-end (`GHOST_SystemAndroid.cc`).
 * Safe to call from the UI thread, requests are queued for Blender's main thread.
 */
public final class GhostAndroid {
    private GhostAndroid() {}

    /** Show/hide the virtual keyboard for typing shortcuts (characters become key presses). */
    public static native void toggleVirtualKeyboard();

    /** Open a file (a `.blend` file is handled as if dropped into the window). */
    public static native void openFile(String filepath);

    /** The activity's surface was destroyed ({@code available} false) or created again. */
    public static native void surfaceChanged(boolean available);
}

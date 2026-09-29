package com.github.sakkijarvenpolkka.blender;

import android.content.Context;
import android.os.Environment;
import android.system.ErrnoException;
import android.system.Os;
import android.util.Log;

import java.io.File;

/**
 * Locations of Blender's files on the device and the environment variables that tell
 * Blender where to find them.
 *
 * <ul>
 *   <li>System resources (datafiles, scripts, Python): extracted from the APK into the
 *       internal app storage, see {@link DataInstaller}.</li>
 *   <li>User resources (preferences, add-ons, extensions): internal app storage.</li>
 *   <li>Home directory (default location of the file browser): the shared storage when
 *       "All files access" is granted, otherwise the app specific external storage.</li>
 * </ul>
 */
final class BlenderPaths {
    private static final String TAG = "BlenderPaths";

    private BlenderPaths() {}

    /** Root of the extracted data, contains the `<major>.<minor>` directory. */
    static File dataRoot(Context context) {
        return new File(context.getFilesDir(), "blender");
    }

    /** Blender's "system resources" directory: `.../blender/<major>.<minor>`. */
    static File systemResources(Context context) {
        return new File(dataRoot(context), shortVersion());
    }

    static File userResources(Context context) {
        return new File(context.getFilesDir(), "user");
    }

    static File home(Context context) {
        if (Environment.isExternalStorageManager()) {
            File shared = Environment.getExternalStorageDirectory();
            if (shared != null && shared.canWrite()) {
                return shared;
            }
        }
        File external = context.getExternalFilesDir(null);
        return external != null ? external : context.getFilesDir();
    }

    static String shortVersion() {
        String[] parts = BuildConfig.BLENDER_VERSION.split("\\.");
        return parts[0] + "." + parts[1];
    }

    /** Must be called before Blender starts. */
    static void setupEnvironment(Context context, float uiScale) {
        File home = home(context);
        File user = userResources(context);
        File system = systemResources(context);
        File tmp = context.getCacheDir();
        //noinspection ResultOfMethodCallIgnored
        user.mkdirs();

        setenv("HOME", home.getAbsolutePath());
        setenv("TMPDIR", tmp.getAbsolutePath());
        setenv("TEMP", tmp.getAbsolutePath());
        setenv("BLENDER_SYSTEM_RESOURCES", system.getAbsolutePath());
        setenv("BLENDER_USER_RESOURCES", user.getAbsolutePath());
        setenv("LANG", "C.UTF-8");
        setenv("PYTHONDONTWRITEBYTECODE", null);

        // OpenSSL (used by Python's `ssl` module) needs the system certificates.
        String[] certDirs = {
            "/apex/com.android.conscrypt/cacerts",
            "/system/etc/security/cacerts",
        };
        for (String dir : certDirs) {
            if (new File(dir).isDirectory()) {
                setenv("SSL_CERT_DIR", dir);
                break;
            }
        }

        if (uiScale > 0.0f) {
            setenv("BLENDER_ANDROID_UI_SCALE", Float.toString(uiScale));
        }
    }

    private static void setenv(String name, String value) {
        try {
            if (value == null) {
                Os.unsetenv(name);
            } else {
                Os.setenv(name, value, true);
            }
        } catch (ErrnoException e) {
            Log.w(TAG, "Unable to set " + name, e);
        }
    }
}

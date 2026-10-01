package com.github.sakkijarvenpolkka.blender;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.AlertDialog;
import android.app.ApplicationExitInfo;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.util.Log;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.DateFormat;
import java.util.Date;
import java.util.List;

/**
 * Entry point: checks the device, extracts Blender's data on first start (or after an update),
 * optionally asks for "All files access" and then starts {@link BlenderActivity}.
 */
public class LauncherActivity extends Activity {
    private static final String TAG = "BlenderLauncher";
    private static final int REQUEST_ALL_FILES_ACCESS = 1;
    /**
     * Vulkan 1.2 (timeline semaphores, buffer device address ...), encoded as for
     * `android.hardware.vulkan.version`.
     */
    private static final int VULKAN_1_2 = 0x402000;

    static final String PREFS = "blender";
    static final String PREF_ASKED_STORAGE = "asked_all_files_access";
    static final String PREF_EXIT_SHOWN = "exit_info_shown";

    private final Handler handler = new Handler(Looper.getMainLooper());
    private TextView status;
    private ProgressBar progress;
    /** `.blend` file to open (copied from a content URI when needed). */
    private String blendFile;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        // Started from the launcher while Blender runs: return to it instead of starting again.
        Intent launch = getIntent();
        if (!isTaskRoot() && launch != null && Intent.ACTION_MAIN.equals(launch.getAction())
                && launch.hasCategory(Intent.CATEGORY_LAUNCHER)) {
            finish();
            return;
        }

        setContentView(createLayout());

        if (!getPackageManager().hasSystemFeature(PackageManager.FEATURE_VULKAN_HARDWARE_VERSION, VULKAN_1_2)) {
            showFatal(getString(R.string.error_no_vulkan));
            return;
        }

        // Copying an opened file and extracting the data can take a while, not on the UI thread.
        final Intent intent = getIntent();
        final boolean installed = DataInstaller.isInstalled(this);
        if (!installed) {
            status.setText(R.string.launcher_installing);
        }
        final Context appContext = getApplicationContext();
        new Thread(() -> {
            String file = resolveBlendFile(intent);
            try {
                if (!installed) {
                    DataInstaller.install(appContext, (fraction, name) ->
                        runOnUi(() -> progress.setProgress((int) (fraction * 1000))));
                }
                runOnUi(() -> {
                    if (blendFile == null) {
                        blendFile = file;
                    }
                    afterInstall();
                });
            } catch (IOException e) {
                Log.e(TAG, "Installing data failed", e);
                runOnUi(() -> showFatal(getString(R.string.error_install, e.getMessage())));
            }
        }, "BlenderLauncher").start();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        new Thread(() -> {
            String file = resolveBlendFile(intent);
            if (file != null) {
                runOnUi(() -> blendFile = file);
            }
        }, "BlenderLauncherIntent").start();
    }

    /** Run on the UI thread, unless the activity is gone by then. */
    private void runOnUi(Runnable runnable) {
        handler.post(() -> {
            if (!isFinishing() && !isDestroyed()) {
                runnable.run();
            }
        });
    }

    private ViewGroup createLayout() {
        float density = getResources().getDisplayMetrics().density;
        int padding = (int) (32 * density);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setGravity(Gravity.CENTER);
        layout.setPadding(padding, padding, padding, padding);
        layout.setBackgroundColor(0xFF232323);

        TextView title = new TextView(this);
        title.setText(R.string.app_name);
        title.setTextColor(0xFFE6E6E6);
        title.setTextSize(24);
        title.setGravity(Gravity.CENTER);
        layout.addView(title);

        TextView version = new TextView(this);
        version.setText(getString(R.string.launcher_version, BuildConfig.VERSION_NAME));
        version.setTextColor(0xFF9A9A9A);
        version.setGravity(Gravity.CENTER);
        layout.addView(version);

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(1000);
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
            (int) (360 * density), ViewGroup.LayoutParams.WRAP_CONTENT);
        params.topMargin = (int) (24 * density);
        layout.addView(progress, params);

        status = new TextView(this);
        status.setTextColor(0xFFBDBDBD);
        status.setGravity(Gravity.CENTER);
        status.setText(R.string.launcher_starting);
        layout.addView(status);
        return layout;
    }

    private void afterInstall() {
        progress.setProgress(1000);
        showPreviousExit(this::checkDontKeepActivities);
    }

    /**
     * The developer option "Don't keep activities" destroys Blender's activity as soon as it goes
     * to the background, which ends Blender (SDL can't run without its activity).
     */
    private void checkDontKeepActivities() {
        if (Settings.Global.getInt(getContentResolver(), Settings.Global.ALWAYS_FINISH_ACTIVITIES, 0) == 0) {
            askStorageAndStart();
            return;
        }
        new AlertDialog.Builder(this)
            .setTitle(R.string.dont_keep_title)
            .setMessage(R.string.dont_keep_message)
            .setPositiveButton(R.string.dont_keep_settings, (dialog, which) -> {
                try {
                    startActivity(new Intent(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS));
                } catch (Exception e) {
                    Log.w(TAG, "Unable to open the developer options", e);
                }
                askStorageAndStart();
            })
            .setNegativeButton(R.string.dont_keep_continue, (dialog, which) -> askStorageAndStart())
            .setCancelable(false)
            .show();
    }

    /**
     * Tells the user when the previous session ended unexpectedly (crash, killed by the system...)
     * and keeps the details (with the native crash report) in the app's external files folder.
     */
    private void showPreviousExit(Runnable next) {
        ApplicationExitInfo info = null;
        try {
            List<ApplicationExitInfo> infos = getSystemService(ActivityManager.class)
                .getHistoricalProcessExitReasons(getPackageName(), 0, 1);
            if (!infos.isEmpty()) {
                info = infos.get(0);
            }
        } catch (Exception e) {
            Log.w(TAG, "Unable to read the exit reasons", e);
        }
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        if (info == null || info.getTimestamp() <= prefs.getLong(PREF_EXIT_SHOWN, 0)) {
            next.run();
            return;
        }
        prefs.edit().putLong(PREF_EXIT_SHOWN, info.getTimestamp()).apply();
        String reason = exitReasonName(info.getReason());
        Log.i(TAG, "Previous exit: " + reason + " (" + info.getDescription() + ")");
        switch (info.getReason()) {
            case ApplicationExitInfo.REASON_CRASH:
            case ApplicationExitInfo.REASON_CRASH_NATIVE:
            case ApplicationExitInfo.REASON_ANR:
            case ApplicationExitInfo.REASON_LOW_MEMORY:
            case ApplicationExitInfo.REASON_SIGNALED:
            case ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE:
            case ApplicationExitInfo.REASON_INITIALIZATION_FAILURE:
                break;
            default:
                // Quit normally, removed from the recent applications, updated...
                next.run();
                return;
        }
        File report = writeExitReport(info, reason);
        String when = DateFormat.getDateTimeInstance().format(new Date(info.getTimestamp()));
        new AlertDialog.Builder(this)
            .setTitle(R.string.exit_title)
            .setMessage(getString(R.string.exit_message, reason, when,
                                  report != null ? report.getAbsolutePath() : "-"))
            .setPositiveButton(android.R.string.ok, (dialog, which) -> next.run())
            .setCancelable(false)
            .show();
    }

    private static String exitReasonName(int reason) {
        switch (reason) {
            case ApplicationExitInfo.REASON_CRASH: return "crash (Java)";
            case ApplicationExitInfo.REASON_CRASH_NATIVE: return "crash (native)";
            case ApplicationExitInfo.REASON_ANR: return "not responding";
            case ApplicationExitInfo.REASON_LOW_MEMORY: return "low memory";
            case ApplicationExitInfo.REASON_SIGNALED: return "signal";
            case ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE: return "excessive resource usage";
            case ApplicationExitInfo.REASON_INITIALIZATION_FAILURE: return "initialization failure";
            case ApplicationExitInfo.REASON_EXIT_SELF: return "exit";
            case ApplicationExitInfo.REASON_USER_REQUESTED: return "closed by the user";
            default: return "reason " + reason;
        }
    }

    /** Writes the exit information (and the native crash report) next to the user's files. */
    private File writeExitReport(ApplicationExitInfo info, String reason) {
        File dir = getExternalFilesDir(null);
        if (dir == null) {
            return null;
        }
        File report = new File(dir, "last_exit.txt");
        try (OutputStream out = new FileOutputStream(report)) {
            String text = "Reason: " + reason + "\nStatus: " + info.getStatus()
                + "\nDescription: " + info.getDescription()
                + "\nImportance: " + info.getImportance()
                + "\nTime: " + new Date(info.getTimestamp())
                + "\nApp version: " + BuildConfig.VERSION_NAME + "\n";
            out.write(text.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            try (InputStream trace = info.getTraceInputStream()) {
                if (trace != null) {
                    if (info.getReason() == ApplicationExitInfo.REASON_CRASH_NATIVE) {
                        // A tombstone (protobuf, see Android's `tombstone.proto`).
                        try (OutputStream tombstone = new FileOutputStream(new File(dir, "last_exit_tombstone.pb"))) {
                            trace.transferTo(tombstone);
                        }
                        out.write("\nNative crash report: last_exit_tombstone.pb\n".getBytes(
                            java.nio.charset.StandardCharsets.UTF_8));
                    } else {
                        out.write("\nTrace:\n".getBytes(java.nio.charset.StandardCharsets.UTF_8));
                        trace.transferTo(out);
                    }
                }
            }
        } catch (IOException e) {
            Log.w(TAG, "Unable to write " + report, e);
            return null;
        }
        return report;
    }

    private void askStorageAndStart() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        if (!Environment.isExternalStorageManager() && !prefs.getBoolean(PREF_ASKED_STORAGE, false)) {
            prefs.edit().putBoolean(PREF_ASKED_STORAGE, true).apply();
            new AlertDialog.Builder(this)
                .setTitle(R.string.storage_title)
                .setMessage(R.string.storage_message)
                .setPositiveButton(R.string.storage_allow, (dialog, which) -> requestAllFilesAccess())
                .setNegativeButton(R.string.storage_skip, (dialog, which) -> startBlender())
                .setCancelable(false)
                .show();
            return;
        }
        startBlender();
    }

    private void requestAllFilesAccess() {
        try {
            Intent intent = new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                                       Uri.parse("package:" + getPackageName()));
            startActivityForResult(intent, REQUEST_ALL_FILES_ACCESS);
        } catch (Exception e) {
            Log.w(TAG, "Unable to request all files access", e);
            startBlender();
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQUEST_ALL_FILES_ACCESS) {
            startBlender();
        }
    }

    private void startBlender() {
        status.setText(R.string.launcher_starting);
        Intent intent = new Intent(this, BlenderActivity.class);
        if (blendFile != null) {
            intent.putExtra(BlenderActivity.EXTRA_BLEND_FILE, blendFile);
        }
        startActivity(intent);
        finish();
    }

    private void showFatal(String message) {
        status.setText(message);
        progress.setVisibility(ProgressBar.GONE);
        new AlertDialog.Builder(this)
            .setTitle(R.string.app_name)
            .setMessage(message)
            .setPositiveButton(android.R.string.ok, (dialog, which) -> finish())
            .setCancelable(false)
            .show();
    }

    /**
     * Returns a file system path for a `.blend` file passed with a VIEW intent.
     * Called on a worker thread (content URIs are copied).
     */
    private String resolveBlendFile(Intent intent) {
        if (intent == null || !Intent.ACTION_VIEW.equals(intent.getAction()) || intent.getData() == null) {
            return null;
        }
        Uri uri = intent.getData();
        if (ContentResolver.SCHEME_FILE.equals(uri.getScheme())) {
            return uri.getPath();
        }
        // Content URIs: copy into the cache, Blender needs a path.
        String name = "opened.blend";
        try (Cursor cursor = getContentResolver().query(uri, null, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int index = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                if (index >= 0 && cursor.getString(index) != null) {
                    name = new File(cursor.getString(index)).getName();
                }
            }
        } catch (Exception e) {
            Log.w(TAG, "Unable to query " + uri, e);
        }
        File dir = new File(getCacheDir(), "opened");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        File out = new File(dir, name);
        try (InputStream in = getContentResolver().openInputStream(uri);
             OutputStream os = new FileOutputStream(out)) {
            if (in == null) {
                return null;
            }
            in.transferTo(os);
            return out.getAbsolutePath();
        } catch (IOException e) {
            Log.e(TAG, "Unable to copy " + uri, e);
            return null;
        }
    }
}

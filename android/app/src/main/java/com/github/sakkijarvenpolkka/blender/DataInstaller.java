package com.github.sakkijarvenpolkka.blender;

import android.content.Context;
import android.content.res.AssetManager;
import android.util.Log;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Extracts Blender's data files (datafiles, scripts & Python standard library) from the
 * `blender_data.zip` asset into the internal storage. Blender needs real files on disk,
 * this happens on first start and after updates.
 */
final class DataInstaller {
    private static final String TAG = "DataInstaller";
    private static final String ARCHIVE = "blender_data.zip";
    private static final String VERSION_ASSET = "blender_data.version";
    private static final String STAMP = ".installed_version";

    interface Progress {
        /** @param fraction 0..1 */
        void onProgress(float fraction, String currentFile);
    }

    private DataInstaller() {}

    private static String readAssetText(AssetManager assets, String name) throws IOException {
        try (InputStream in = assets.open(name)) {
            byte[] data = in.readAllBytes();
            return new String(data, StandardCharsets.UTF_8).trim();
        }
    }

    /** Identifier of the data packaged in this APK. */
    static String packagedVersion(Context context) {
        try {
            return readAssetText(context.getAssets(), VERSION_ASSET) + "/" + BuildConfig.VERSION_CODE;
        } catch (IOException e) {
            return "unknown/" + BuildConfig.VERSION_CODE;
        }
    }

    static boolean isInstalled(Context context) {
        File stamp = new File(BlenderPaths.dataRoot(context), STAMP);
        if (!stamp.isFile()) {
            return false;
        }
        try {
            String installed = new String(Files.readAllBytes(stamp.toPath()), StandardCharsets.UTF_8);
            return installed.trim().equals(packagedVersion(context));
        } catch (IOException e) {
            return false;
        }
    }

    private static void deleteRecursive(File file) {
        File[] children = file.listFiles();
        if (children != null) {
            for (File child : children) {
                deleteRecursive(child);
            }
        }
        //noinspection ResultOfMethodCallIgnored
        file.delete();
    }

    static void install(Context context, Progress progress) throws IOException {
        File root = BlenderPaths.dataRoot(context);
        File staging = new File(context.getFilesDir(), "blender.staging");
        deleteRecursive(staging);
        if (!staging.mkdirs()) {
            throw new IOException("Unable to create " + staging);
        }

        AssetManager assets = context.getAssets();
        long total = 1;
        try {
            total = Math.max(1, Long.parseLong(readAssetText(assets, ARCHIVE + ".size")));
        } catch (IOException | NumberFormatException e) {
            Log.w(TAG, "Unknown archive size");
        }

        String canonicalStaging = staging.getCanonicalPath() + File.separator;
        byte[] buffer = new byte[256 * 1024];
        long written = 0;
        try (ZipInputStream zip = new ZipInputStream(new BufferedInputStream(assets.open(ARCHIVE), 1 << 20))) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                File out = new File(staging, entry.getName());
                // Guard against "zip slip".
                if (!out.getCanonicalPath().startsWith(canonicalStaging)) {
                    throw new IOException("Invalid entry " + entry.getName());
                }
                if (entry.isDirectory()) {
                    //noinspection ResultOfMethodCallIgnored
                    out.mkdirs();
                    continue;
                }
                File parent = out.getParentFile();
                if (parent != null) {
                    //noinspection ResultOfMethodCallIgnored
                    parent.mkdirs();
                }
                try (OutputStream os = new BufferedOutputStream(new FileOutputStream(out), 1 << 16)) {
                    int n;
                    while ((n = zip.read(buffer)) > 0) {
                        os.write(buffer, 0, n);
                        written += n;
                    }
                }
                progress.onProgress(Math.min(1.0f, (float) written / (float) total), entry.getName());
            }
        }

        // Swap in the new data.
        deleteRecursive(root);
        if (!staging.renameTo(root)) {
            throw new IOException("Unable to move " + staging + " to " + root);
        }
        Files.write(new File(root, STAMP).toPath(),
                    packagedVersion(context).getBytes(StandardCharsets.UTF_8));
        progress.onProgress(1.0f, "");
    }
}

package com.github.sakkijarvenpolkka.blender;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

/**
 * Foreground service keeping Blender running while it's in the background, e.g. while an AI
 * assistant uses Blender through the MCP server add-on from another app. Without it Android
 * freezes (and eventually stops) applications in the background.
 *
 * Started & stopped by {@link BlenderActivity#setKeepAlive}.
 */
public class BackgroundService extends Service {
    private static final String CHANNEL_ID = "background";
    private static final int NOTIFICATION_ID = 1;

    static void start(Context context) {
        context.startForegroundService(new Intent(context, BackgroundService.class));
    }

    static void stop(Context context) {
        context.stopService(new Intent(context, BackgroundService.class));
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(
            CHANNEL_ID, getString(R.string.background_channel), NotificationManager.IMPORTANCE_LOW));

        Intent open = new Intent(this, BlenderActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
        PendingIntent contentIntent = PendingIntent.getActivity(
            this, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        Notification notification = new Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(getString(R.string.background_title))
            .setContentText(getString(R.string.background_text))
            .setContentIntent(contentIntent)
            .setOngoing(true)
            .build();

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(NOTIFICATION_ID, notification,
                            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
        return START_NOT_STICKY;
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}

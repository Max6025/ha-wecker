package de.starnberg.hawecker

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build

object Notifications {

    const val CH_RING = "hawecker_ring"

    /** v2, weil eine bereits angelegte Kanal-Wichtigkeit nicht mehr aenderbar ist. */
    const val CH_PREWARN = "hawecker_prewarn"

    /** Benachrichtigungs-IDs der Vorwarnungen: Basis plus Wecker-ID. */
    const val PRE_NOTIF_BASE = 5000

    private fun nm(ctx: Context) =
        ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

    fun ensureChannels(ctx: Context) {
        val manager = nm(ctx)

        manager.createNotificationChannel(
            NotificationChannel(CH_RING, "Weckruf", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Der klingelnde Wecker"
                setSound(null, null)
                enableVibration(false)
                setBypassDnd(true)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            }
        )

        manager.createNotificationChannel(
            NotificationChannel(CH_PREWARN, "Vorwarnung", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Stummer Hinweis kurz vor dem Weckruf"
                setSound(null, null)
                enableVibration(false)
                setShowBadge(false)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            }
        )

        // Alten Dienst-Kanal aufraeumen
        runCatching { manager.deleteNotificationChannel("hawecker_service") }
    }

    // ------------------------------------------------------------------
    //  Weckruf
    // ------------------------------------------------------------------

    fun showRinging(ctx: Context, alarm: Alarm) {
        nm(ctx).notify(AlarmReceiver.RING_NOTIFICATION_ID, buildRinging(ctx, alarm))
    }

    /** Darf die App eine Vollbild-Benachrichtigung ausloesen? (Android 14+) */
    fun canUseFullScreenIntent(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < 34) return true
        return runCatching { nm(ctx).canUseFullScreenIntent() }.getOrDefault(true)
    }

    fun buildRinging(ctx: Context, alarm: Alarm): Notification {
        ensureChannels(ctx)

        val full = PendingIntent.getActivity(
            ctx, 900 + alarm.id,
            Intent(ctx, RingActivity::class.java)
                .putExtra(AlarmReceiver.EXTRA_ID, alarm.id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val snooze = broadcast(ctx, 910 + alarm.id, AlarmReceiver.ACTION_SNOOZE, alarm.id)
        val dismiss = broadcast(ctx, 920 + alarm.id, AlarmReceiver.ACTION_DISMISS, alarm.id)

        val title = if (alarm.label.isBlank()) "Wecker" else alarm.label
        return Notification.Builder(ctx, CH_RING)
            .setSmallIcon(R.drawable.ic_stat_alarm)
            .setContentTitle("$title - ${alarm.timeString()}")
            .setContentText("Weckruf laeuft")
            .setCategory(Notification.CATEGORY_ALARM)
            .setOngoing(true)
            .setAutoCancel(false)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setFullScreenIntent(full, true)
            .setContentIntent(full)
            .addAction(action("Schlummern", snooze))
            .addAction(action("Stopp", dismiss))
            .build()
    }

    // ------------------------------------------------------------------
    //  Stumme Vorwarnung
    // ------------------------------------------------------------------

    fun showPrewarn(ctx: Context, alarm: Alarm, minutesBefore: Int) {
        ensureChannels(ctx)

        val open = PendingIntent.getActivity(
            ctx, 930 + alarm.id,
            Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        // Wiederkehrender Wecker: nur der naechste Termin faellt aus.
        // Einmaliger Wecker: er wird abgeschaltet.
        val isRepeating = alarm.isRepeating()
        val actionLabel = if (isRepeating) "Nur heute aus" else "Ausschalten"
        val actionIntent = broadcast(
            ctx, 940 + alarm.id,
            if (isRepeating) AlarmReceiver.ACTION_SKIP_TODAY else AlarmReceiver.ACTION_DISABLE,
            alarm.id
        )

        val title = if (alarm.label.isBlank()) "Wecker ${alarm.timeString()}"
        else "${alarm.label} - ${alarm.timeString()}"

        val n = Notification.Builder(ctx, CH_PREWARN)
            .setSmallIcon(R.drawable.ic_stat_alarm)
            .setContentTitle(title)
            .setContentText("Klingelt in $minutesBefore Minuten")
            .setCategory(Notification.CATEGORY_REMINDER)
            .setOnlyAlertOnce(true)
            .setAutoCancel(true)
            .setShowWhen(false)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setTimeoutAfter(minutesBefore * 60_000L + 60_000L)
            .setContentIntent(open)
            .addAction(action(actionLabel, actionIntent))
            .build()

        nm(ctx).notify(PRE_NOTIF_BASE + alarm.id, n)
    }

    fun cancelPrewarn(ctx: Context, id: Int) {
        runCatching { nm(ctx).cancel(PRE_NOTIF_BASE + id) }
    }

    // ------------------------------------------------------------------

    private fun broadcast(ctx: Context, req: Int, action: String, id: Int): PendingIntent =
        PendingIntent.getBroadcast(
            ctx, req,
            Intent(ctx, AlarmReceiver::class.java)
                .setAction(action)
                .putExtra(AlarmReceiver.EXTRA_ID, id),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

    private fun action(label: String, pi: PendingIntent): Notification.Action =
        Notification.Action.Builder(null as android.graphics.drawable.Icon?, label, pi).build()
}

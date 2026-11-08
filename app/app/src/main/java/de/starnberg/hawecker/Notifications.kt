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

    /** Schlafenszeit: stille Dauer-Anzeige, solange das Fenster laeuft. */
    const val CH_SLEEP = "hawecker_sleep"

    /** Benachrichtigungs-IDs der Vorwarnungen: Basis plus Wecker-ID. */
    const val PRE_NOTIF_BASE = 5000
    const val SLEEP_NOTIF_ID = 4800

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
                description = "Stiller Hinweis kurz vor dem Weckruf, als Live-Benachrichtigung"
                setSound(null, null)
                enableVibration(false)
                setShowBadge(false)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            }
        )

        manager.createNotificationChannel(
            NotificationChannel(CH_SLEEP, "Schlafenszeit", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Stille Anzeige waehrend der Schlafenszeit"
                setSound(null, null)
                enableVibration(false)
                setShowBadge(false)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            }
        )

        // Alten Dienst-Kanal aufraeumen
        runCatching { manager.deleteNotificationChannel("hawecker_service") }
        runCatching { manager.deleteNotificationChannel("hawecker_service_v2") }
    }

    // ------------------------------------------------------------------
    //  Live-Benachrichtigung (Android 16 "Live Updates", Samsung-Leiste)
    // ------------------------------------------------------------------

    /**
     * Bittet das System, die Benachrichtigung als Live-Update oben zu zeigen
     * (Statusleisten-Chip, Sperrbildschirm, Samsung Now Bar). Gibt es die
     * Schnittstelle nicht (vor Android 16), bleibt es eine normale laufende
     * Benachrichtigung mit Countdown. Ueber Reflexion, damit die App mit
     * compileSdk 35 gebaut werden kann.
     */
    private fun promote(b: Notification.Builder, shortText: String) {
        if (Build.VERSION.SDK_INT < 36) return
        runCatching {
            Notification.Builder::class.java
                .getMethod("setRequestPromotedOngoing", Boolean::class.javaPrimitiveType)
                .invoke(b, true)
        }
        runCatching {
            Notification.Builder::class.java
                .getMethod("setShortCriticalText", CharSequence::class.java)
                .invoke(b, shortText)
        }
    }

    /** Darf die App Live-Benachrichtigungen zeigen? Vor Android 16 immer "ja". */
    fun canPromote(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < 36) return true
        return runCatching {
            NotificationManager::class.java.getMethod("canPostPromotedNotifications")
                .invoke(nm(ctx)) as Boolean
        }.getOrDefault(true)
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
        val b = Notification.Builder(ctx, CH_RING)
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
        promote(b, "Weckruf")
        return b.build()
    }

    // ------------------------------------------------------------------
    //  Vorwarnung als Live-Benachrichtigung
    // ------------------------------------------------------------------

    /**
     * Erscheint [minutesBefore] Minuten vor dem Weckruf oben als Live-Update
     * mit laufendem Countdown. Antippen oeffnet den kleinen Dialog
     * (heute aus / ausschalten / lassen), die Knoepfe tun es direkt.
     */
    fun showPrewarn(ctx: Context, alarm: Alarm, minutesBefore: Int) {
        ensureChannels(ctx)
        val fireAt = alarm.nextTriggerAt()
        if (fireAt <= 0L) return

        val open = PendingIntent.getActivity(
            ctx, 930 + alarm.id,
            Intent(ctx, PrewarnActivity::class.java)
                .putExtra(AlarmReceiver.EXTRA_ID, alarm.id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val skip = broadcast(ctx, 940 + alarm.id, AlarmReceiver.ACTION_SKIP_TODAY, alarm.id)
        val off = broadcast(ctx, 950 + alarm.id, AlarmReceiver.ACTION_DISABLE, alarm.id)

        val title = if (alarm.label.isBlank()) "Wecker ${alarm.timeString()}"
        else "${alarm.label} - ${alarm.timeString()}"

        val b = Notification.Builder(ctx, CH_PREWARN)
            .setSmallIcon(R.drawable.ic_stat_alarm)
            .setContentTitle(title)
            .setContentText("Klingelt in")
            .setCategory(Notification.CATEGORY_ALARM)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setAutoCancel(false)
            // Countdown bis zum Weckruf laeuft in der Anzeige mit
            .setWhen(fireAt)
            .setShowWhen(true)
            .setUsesChronometer(true)
            .setChronometerCountDown(true)
            .setColor(0xFFFFB23F.toInt())
            .setColorized(true)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setTimeoutAfter(fireAt - System.currentTimeMillis() + 60_000L)
            .setContentIntent(open)
        if (alarm.isRepeating()) b.addAction(action("Nur heute aus", skip))
        b.addAction(action("Ausschalten", off))
        promote(b, "Wecker ${alarm.timeString()}")

        nm(ctx).notify(PRE_NOTIF_BASE + alarm.id, b.build())
    }

    fun cancelPrewarn(ctx: Context, id: Int) {
        runCatching { nm(ctx).cancel(PRE_NOTIF_BASE + id) }
    }

    // ------------------------------------------------------------------
    //  Schlafenszeit
    // ------------------------------------------------------------------

    /** Stille Live-Anzeige "Schlafenszeit bis HH:MM", Countdown bis zum Ende. */
    fun showSleep(ctx: Context, window: SleepTime.Window) {
        ensureChannels(ctx)
        val open = PendingIntent.getActivity(
            ctx, 960,
            Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val next = AlarmScheduler.nextAlarm(ctx)
        val text = if (next != null && next.second <= window.end + 60_000L)
            "Wecker ${next.first.timeString()} - noch"
        else
            "Bis ${SleepTime.timeString(Prefs.sleepEnd(ctx))} - noch"

        val b = Notification.Builder(ctx, CH_SLEEP)
            .setSmallIcon(R.drawable.ic_stat_sleep)
            .setContentTitle("Schlafenszeit")
            .setContentText(text)
            .setCategory(Notification.CATEGORY_STATUS)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setAutoCancel(false)
            .setWhen(window.end)
            .setShowWhen(true)
            .setUsesChronometer(true)
            .setChronometerCountDown(true)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .setTimeoutAfter(window.end - System.currentTimeMillis() + 60_000L)
            .setContentIntent(open)
        promote(b, "Schlafen")
        nm(ctx).notify(SLEEP_NOTIF_ID, b.build())
    }

    fun cancelSleep(ctx: Context) {
        runCatching { nm(ctx).cancel(SLEEP_NOTIF_ID) }
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

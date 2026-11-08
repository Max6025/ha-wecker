package de.starnberg.hawecker

import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.PowerManager

class AlarmReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_FIRE = "de.starnberg.hawecker.FIRE"
        const val ACTION_SNOOZE = "de.starnberg.hawecker.SNOOZE"
        const val ACTION_DISMISS = "de.starnberg.hawecker.DISMISS"
        const val ACTION_PREWARN = "de.starnberg.hawecker.PREWARN"
        const val ACTION_SKIP_TODAY = "de.starnberg.hawecker.SKIP_TODAY"
        const val ACTION_DISABLE = "de.starnberg.hawecker.DISABLE"
        const val ACTION_PUSH_RETRY = "de.starnberg.hawecker.PUSH_RETRY"
        const val ACTION_SLEEP_START = "de.starnberg.hawecker.SLEEP_START"
        const val ACTION_SLEEP_END = "de.starnberg.hawecker.SLEEP_END"
        const val EXTRA_ID = "alarm_id"
        const val RING_NOTIFICATION_ID = 4711

        /** Kuenstliche ID fuer den Testweckruf aus den Einstellungen. */
        const val TEST_ID = -99

        fun resolveAlarm(ctx: Context, id: Int): Alarm? = when {
            id == TEST_ID -> Alarm(
                id = TEST_ID,
                label = "Testweckruf",
                enabled = true,
                catId = CategoryStore.all(ctx).first().id,
                tone = Prefs.defTone(ctx),
                vibe = "Herzschlag",
                snoozeMinutes = 1
            )
            id >= 0 -> AlarmStore.get(ctx, id)
            else -> null
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        val ctx = context.applicationContext
        val id = intent.getIntExtra(EXTRA_ID, -1)

        // Haelt den Prozess waehrend des Netzwerkversands am Leben.
        val pending = goAsync()

        when (intent.action) {
            ACTION_PUSH_RETRY -> {
                HaPush.pushAsync(ctx, pending)
                return
            }

            ACTION_SNOOZE -> {
                stopRinging(ctx)
                if (id >= 0) AlarmScheduler.snooze(ctx, id)
                HaPush.pushAsync(ctx, pending)
                return
            }

            ACTION_DISMISS -> {
                stopRinging(ctx)
                if (id >= 0) AlarmScheduler.dismiss(ctx, id)
                HaPush.pushAsync(ctx, pending)
                return
            }

            ACTION_SLEEP_START, ACTION_SLEEP_END -> {
                // Anzeige nach dem tatsaechlichen Fenster richten und das
                // naechste Ereignis planen; HA bekommt den neuen Zustand.
                AlarmScheduler.scheduleSleep(ctx)
                HaPush.pushAsync(ctx, pending)
                return
            }

            ACTION_PREWARN -> {
                val a = if (id >= 0) AlarmStore.get(ctx, id) else null
                if (a != null && a.enabled && !a.skipNext) {
                    Notifications.showPrewarn(ctx, a, Prefs.prewarnMinutes(ctx))
                }
                runCatching { pending.finish() }
                return
            }

            ACTION_SKIP_TODAY -> {
                Notifications.cancelPrewarn(ctx, id)
                val a = if (id >= 0) AlarmStore.get(ctx, id) else null
                if (a != null) {
                    a.snoozedUntil = 0L
                    if (a.isRepeating()) a.skipNext = true else a.enabled = false
                    AlarmStore.save(ctx, a)
                }
                HaPush.pushAsync(ctx, pending)
                return
            }

            ACTION_DISABLE -> {
                Notifications.cancelPrewarn(ctx, id)
                val a = if (id >= 0) AlarmStore.get(ctx, id) else null
                if (a != null) {
                    a.enabled = false
                    a.snoozedUntil = 0L
                    a.skipNext = false
                    AlarmStore.save(ctx, a)
                }
                HaPush.pushAsync(ctx, pending)
                return
            }
        }

        val alarm = resolveAlarm(ctx, id)
        if (alarm == null || !alarm.enabled) {
            runCatching { pending.finish() }
            return
        }

        val pm = ctx.getSystemService(Context.POWER_SERVICE) as PowerManager
        @Suppress("DEPRECATION")
        val wl = pm.newWakeLock(
            PowerManager.FULL_WAKE_LOCK or PowerManager.ACQUIRE_CAUSES_WAKEUP,
            "hawecker:fire"
        )
        runCatching { wl.acquire(30_000L) }

        // Snooze-Marker loeschen, sonst wuerde sofort wieder geplant werden
        if (id >= 0 && alarm.snoozedUntil > 0L) {
            alarm.snoozedUntil = 0L
            AlarmStore.save(ctx, alarm)
        }

        Notifications.cancelPrewarn(ctx, alarm.id)

        RingState.ringingId = alarm.id
        RingState.ringingSince = System.currentTimeMillis()

        // Der Dienst postet die Vollbild-Benachrichtigung, startet den Ton
        // und oeffnet die Vollbild-Activity.
        RingService.start(ctx, alarm.id)

        if (wl.isHeld) runCatching { wl.release() }
        HaPush.pushAsync(ctx, pending)
    }

    private fun stopRinging(ctx: Context) {
        RingState.ringingId = -1
        RingState.ringingSince = 0L
        RingPlayer.stop()
        RingService.stop(ctx)
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.cancel(RING_NOTIFICATION_ID)
        ctx.sendBroadcast(Intent(RingActivity.ACTION_CLOSE).setPackage(ctx.packageName))
    }
}

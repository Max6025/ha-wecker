package de.starnberg.hawecker

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build

/** Plant alle aktiven Wecker exakt ueber den AlarmManager (setAlarmClock). */
object AlarmScheduler {

    private const val REQ_BASE = 100000
    private const val REQ_PRE = 300000
    private const val REQ_PUSH_RETRY = 400001

    private fun am(ctx: Context) =
        ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager

    private fun pendingFire(ctx: Context, id: Int, create: Boolean): PendingIntent? {
        val i = Intent(ctx, AlarmReceiver::class.java).apply {
            action = AlarmReceiver.ACTION_FIRE
            putExtra(AlarmReceiver.EXTRA_ID, id)
            data = android.net.Uri.parse("hawecker://alarm/$id")
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        if (!create) flags = flags or PendingIntent.FLAG_NO_CREATE
        return PendingIntent.getBroadcast(ctx, REQ_BASE + id, i, flags)
    }

    private fun pendingPrewarn(ctx: Context, id: Int, create: Boolean): PendingIntent? {
        val i = Intent(ctx, AlarmReceiver::class.java).apply {
            action = AlarmReceiver.ACTION_PREWARN
            putExtra(AlarmReceiver.EXTRA_ID, id)
            data = android.net.Uri.parse("hawecker://prewarn/$id")
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        if (!create) flags = flags or PendingIntent.FLAG_NO_CREATE
        return PendingIntent.getBroadcast(ctx, REQ_PRE + id, i, flags)
    }

    fun canScheduleExact(ctx: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= 31) am(ctx).canScheduleExactAlarms() else true
    }

    fun scheduleAll(ctx: Context) {
        val now = System.currentTimeMillis()
        for (a in AlarmStore.all(ctx)) {
            val at = a.nextTriggerAt(now)
            if (at <= 0L) {
                cancel(ctx, a.id)
                Notifications.cancelPrewarn(ctx, a.id)
                continue
            }
            schedulePrewarn(ctx, a, at, now)
            val pi = pendingFire(ctx, a.id, true) ?: continue
            val showIntent = PendingIntent.getActivity(
                ctx, REQ_BASE + 50000 + a.id,
                Intent(ctx, MainActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            )
            try {
                am(ctx).setAlarmClock(AlarmManager.AlarmClockInfo(at, showIntent), pi)
            } catch (_: SecurityException) {
                // Exakte Alarme nicht erlaubt -> bestmoeglicher Fallback
                try {
                    am(ctx).setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
                } catch (_: Exception) {
                    am(ctx).set(AlarmManager.RTC_WAKEUP, at, pi)
                }
            }
        }
    }

    /** Testweckruf in wenigen Sekunden, um Vollbild und Ton zu pruefen. */
    fun scheduleTest(ctx: Context, delaySeconds: Int = 10): Long {
        val i = Intent(ctx, AlarmReceiver::class.java).apply {
            action = AlarmReceiver.ACTION_FIRE
            putExtra(AlarmReceiver.EXTRA_ID, AlarmReceiver.TEST_ID)
            data = android.net.Uri.parse("hawecker://alarm/test")
        }
        val pi = PendingIntent.getBroadcast(
            ctx, REQ_BASE + 99999, i,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val at = System.currentTimeMillis() + delaySeconds * 1000L
        val showIntent = PendingIntent.getActivity(
            ctx, REQ_BASE + 99998,
            Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        try {
            am(ctx).setAlarmClock(AlarmManager.AlarmClockInfo(at, showIntent), pi)
        } catch (_: Exception) {
            runCatching { am(ctx).setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi) }
        }
        return at
    }

    private fun schedulePrewarn(ctx: Context, a: Alarm, at: Long, now: Long) {
        cancelPrewarn(ctx, a.id)
        // Ein uebersprungener Wecker bekommt keine Vorwarnung mehr; eine
        // bereits sichtbare wird entfernt.
        if (a.skipNext) {
            Notifications.cancelPrewarn(ctx, a.id)
            return
        }
        val minutes = Prefs.prewarnMinutes(ctx)
        if (minutes <= 0) {
            Notifications.cancelPrewarn(ctx, a.id)
            return
        }
        val preAt = at - minutes * 60_000L
        if (preAt <= now) return
        val pi = pendingPrewarn(ctx, a.id, true) ?: return
        try {
            am(ctx).setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, preAt, pi)
        } catch (_: Exception) {
            runCatching { am(ctx).set(AlarmManager.RTC_WAKEUP, preAt, pi) }
        }
    }

    private fun cancelPrewarn(ctx: Context, id: Int) {
        pendingPrewarn(ctx, id, false)?.let {
            am(ctx).cancel(it)
            it.cancel()
        }
    }

    // --- Wiederholung eines fehlgeschlagenen Push ------------------------

    private fun pendingPushRetry(ctx: Context, create: Boolean): PendingIntent? {
        val i = Intent(ctx, AlarmReceiver::class.java).apply {
            action = AlarmReceiver.ACTION_PUSH_RETRY
            data = android.net.Uri.parse("hawecker://push/retry")
        }
        var flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        if (!create) flags = flags or PendingIntent.FLAG_NO_CREATE
        return PendingIntent.getBroadcast(ctx, REQ_PUSH_RETRY, i, flags)
    }

    /** Ein einzelner, ungenauer Versuch in ein paar Minuten. Kostet im Leerlauf nichts. */
    fun schedulePushRetry(ctx: Context, minutes: Int = 5) {
        val pi = pendingPushRetry(ctx, true) ?: return
        val at = System.currentTimeMillis() + minutes * 60_000L
        runCatching { am(ctx).setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi) }
    }

    fun cancelPushRetry(ctx: Context) {
        pendingPushRetry(ctx, false)?.let {
            am(ctx).cancel(it)
            it.cancel()
        }
    }

    fun cancel(ctx: Context, id: Int) {
        pendingFire(ctx, id, false)?.let {
            am(ctx).cancel(it)
            it.cancel()
        }
        cancelPrewarn(ctx, id)
    }

    /** Naechster Wecker ueber alle hinweg. */
    fun nextAlarm(ctx: Context): Pair<Alarm, Long>? {
        val now = System.currentTimeMillis()
        return AlarmStore.all(ctx)
            .mapNotNull { a -> a.nextTriggerAt(now).takeIf { it > 0 }?.let { a to it } }
            .minByOrNull { it.second }
    }

    fun snooze(ctx: Context, id: Int) {
        val a = AlarmStore.get(ctx, id) ?: return
        a.snoozedUntil = System.currentTimeMillis() + a.snoozeMinutes * 60_000L
        AlarmStore.save(ctx, a)
    }

    fun dismiss(ctx: Context, id: Int) {
        val a = AlarmStore.get(ctx, id) ?: return
        a.snoozedUntil = 0L
        if (!a.isRepeating()) a.enabled = false
        if (a.skipNext) a.skipNext = false
        AlarmStore.save(ctx, a)
    }
}

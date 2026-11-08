package de.starnberg.hawecker

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

/**
 * Live-Benachrichtigung mit Balken fuer die letzten Minuten vor dem Weckruf.
 * Laeuft nur in diesem Fenster (Vorwarnzeit, meist 5 Minuten) als kurzer
 * Vordergrunddienst und stellt die Anzeige alle 20 s neu - so wie die
 * Kalender-App ihren Terminbalken. Davor laeuft nichts im Hintergrund.
 */
class VorwarnService : Service() {

    companion object {
        const val EXTRA_ID = "vorwarn_alarm_id"
        private const val TAKT = 20_000L

        fun start(ctx: Context, id: Int) {
            val i = Intent(ctx, VorwarnService::class.java).putExtra(EXTRA_ID, id)
            runCatching { ContextCompat.startForegroundService(ctx, i) }
                .onFailure {
                    // Dienst nicht erlaubt (z. B. aus dem Hintergrund): wenigstens
                    // die Benachrichtigung ohne laufenden Balken zeigen.
                    AlarmStore.get(ctx, id)?.let { a -> Notifications.showPrewarn(ctx, a, Prefs.prewarnMinutes(ctx)) }
                }
        }

        fun stop(ctx: Context) {
            runCatching { ctx.stopService(Intent(ctx, VorwarnService::class.java)) }
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var alarmId = -1
    private var fireAt = 0L

    private val takt = object : Runnable {
        override fun run() {
            if (!aktualisieren()) return
            handler.postDelayed(this, TAKT)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val id = intent?.getIntExtra(EXTRA_ID, -1) ?: -1
        val alarm = if (id >= 0) AlarmStore.get(this, id) else null
        val minuten = Prefs.prewarnMinutes(this)
        if (alarm == null || !alarm.enabled || alarm.skipNext || minuten <= 0) {
            // Android verlangt nach startForegroundService ein startForeground
            runCatching { vordergrund(alarm ?: Alarm(id = -1, label = "Wecker"), minuten) }
            stopSelf()
            return START_NOT_STICKY
        }
        alarmId = alarm.id
        fireAt = alarm.nextTriggerAt()
        vordergrund(alarm, minuten)
        handler.removeCallbacks(takt)
        handler.postDelayed(takt, TAKT)
        return START_NOT_STICKY
    }

    private fun vordergrund(alarm: Alarm, minuten: Int) {
        val n = Notifications.buildPrewarn(this, alarm, minuten)
        runCatching {
            if (Build.VERSION.SDK_INT >= 34) {
                ServiceCompat.startForeground(
                    this, Notifications.PRE_NOTIF_BASE + alarm.id, n,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
                )
            } else {
                startForeground(Notifications.PRE_NOTIF_BASE + alarm.id, n)
            }
        }
    }

    /** Anzeige neu stellen; false, wenn der Dienst zu Ende ist. */
    private fun aktualisieren(): Boolean {
        val alarm = AlarmStore.get(this, alarmId)
        val now = System.currentTimeMillis()
        if (alarm == null || !alarm.enabled || alarm.skipNext || alarm.nextTriggerAt(now) != fireAt ||
            now >= fireAt || RingState.ringingId == alarmId
        ) {
            stopSelf()
            return false
        }
        Notifications.showPrewarn(this, alarm, Prefs.prewarnMinutes(this))
        return true
    }

    override fun onDestroy() {
        handler.removeCallbacks(takt)
        // Die Benachrichtigung bleibt nur stehen, solange der Weckruf noch kommt;
        // beim Klingeln, Aussetzen oder Ausschalten raeumt der Empfaenger sie weg.
        super.onDestroy()
    }
}

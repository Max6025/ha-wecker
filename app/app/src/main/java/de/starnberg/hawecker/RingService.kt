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
 * Haelt den laufenden Weckruf. Als Vordergrunddienst, damit Ton und
 * Vollbild-Benachrichtigung auch bei ausgeschaltetem Bildschirm sicher laufen
 * und nicht an der kurzen Lebensdauer eines BroadcastReceivers haengen.
 */
class RingService : Service() {

    companion object {
        const val EXTRA_ID = "ring_alarm_id"
        private const val TIMEOUT_MS = 10 * 60 * 1000L

        fun start(ctx: Context, id: Int) {
            val i = Intent(ctx, RingService::class.java).putExtra(EXTRA_ID, id)
            runCatching { ContextCompat.startForegroundService(ctx, i) }
        }

        fun stop(ctx: Context) {
            runCatching { ctx.stopService(Intent(ctx, RingService::class.java)) }
        }
    }

    private val handler = Handler(Looper.getMainLooper())
    private var timeout: Runnable? = null
    private var vollbildVersuche = 0

    private fun vollbildOeffnen(id: Int) {
        if (RingState.ringingId != id || RingState.seiteOffen || vollbildVersuche >= 4) return
        vollbildVersuche++
        runCatching {
            startActivity(
                Intent(this, RingActivity::class.java)
                    .putExtra(AlarmReceiver.EXTRA_ID, id)
                    .addFlags(
                        Intent.FLAG_ACTIVITY_NEW_TASK or
                            Intent.FLAG_ACTIVITY_CLEAR_TOP or
                            Intent.FLAG_ACTIVITY_NO_USER_ACTION or
                            Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS
                    )
            )
        }
        handler.postDelayed({ vollbildOeffnen(id) }, 1500)
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val id = intent?.getIntExtra(EXTRA_ID, -1) ?: -1
        val alarm = AlarmReceiver.resolveAlarm(this, id)
        if (alarm == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        RingState.ringingId = alarm.id
        RingState.ringingSince = System.currentTimeMillis()

        Notifications.ensureChannels(this)
        val notif = Notifications.buildRinging(this, alarm)
        runCatching {
            if (Build.VERSION.SDK_INT >= 34) {
                ServiceCompat.startForeground(
                    this, AlarmReceiver.RING_NOTIFICATION_ID, notif,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK
                )
            } else {
                startForeground(AlarmReceiver.RING_NOTIFICATION_ID, notif)
            }
        }.onFailure {
            // Falls der Vordergrunddienst abgelehnt wird: wenigstens die
            // Vollbild-Benachrichtigung posten.
            Notifications.showRinging(this, alarm)
        }

        RingPlayer.start(this, alarm)

        // Vollbild direkt oeffnen. Bei ausgeschaltetem Bildschirm macht das der
        // FullScreenIntent der Benachrichtigung; bei eingeschaltetem, entsperrtem
        // Handy zeigt Android davon nur einen Hinweis oben - dann hilft nur der
        // direkte Start, den Android mit der Freigabe "Ueber anderen Apps
        // anzeigen" durchlaesst. Ein paar Anlaeufe, falls der erste verschluckt wird.
        vollbildVersuche = 0
        vollbildOeffnen(alarm.id)

        timeout?.let { handler.removeCallbacks(it) }
        val t = Runnable {
            sendBroadcast(
                Intent(this, AlarmReceiver::class.java)
                    .setAction(AlarmReceiver.ACTION_DISMISS)
                    .putExtra(AlarmReceiver.EXTRA_ID, alarm.id)
            )
        }
        timeout = t
        handler.postDelayed(t, TIMEOUT_MS)

        HaPush.pushAsync(this)
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        timeout?.let { handler.removeCallbacks(it) }
        RingPlayer.stop()
        RingState.ringingId = -1
        RingState.ringingSince = 0L
    }
}

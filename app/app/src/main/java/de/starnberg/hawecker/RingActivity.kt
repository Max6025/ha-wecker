package de.starnberg.hawecker

import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.view.WindowManager
import android.widget.TextView
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class RingActivity : Activity() {

    companion object {
        const val ACTION_CLOSE = "de.starnberg.hawecker.CLOSE_RING"
    }

    private var alarmId = -1
    private val handler = Handler(Looper.getMainLooper())
    private var ticker: Runnable? = null

    private val closeReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            finishAndRemoveTask()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            (getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager)
                .requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            )
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        setContentView(R.layout.activity_ring)

        alarmId = intent.getIntExtra(AlarmReceiver.EXTRA_ID, RingState.ringingId)
        val alarm = AlarmReceiver.resolveAlarm(this, alarmId)

        val label = findViewById<TextView>(R.id.ringLabel)
        val sub = findViewById<TextView>(R.id.ringSub)
        label.text = if (alarm == null || alarm.label.isBlank()) "WECKER" else alarm.label.uppercase(Locale.GERMANY)
        sub.text = if (alarm == null) "" else "Geplant fuer ${alarm.timeString()}"

        startClock()

        if (alarm != null) {
            RingState.ringingId = alarm.id
            if (!RingPlayer.isPlaying()) RingPlayer.start(this, alarm)
            findViewById<TextView>(R.id.btnSnooze).text = "SCHLUMMERN  ${alarm.snoozeMinutes} MIN"
        }

        findViewById<TextView>(R.id.btnSnooze).setOnClickListener { act(AlarmReceiver.ACTION_SNOOZE) }
        findViewById<TextView>(R.id.btnStop).setOnClickListener { act(AlarmReceiver.ACTION_DISMISS) }

        val filter = IntentFilter(ACTION_CLOSE)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(closeReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(closeReceiver, filter)
        }
    }

    private fun startClock() {
        val clock = findViewById<TextView>(R.id.ringClock)
        val date = findViewById<TextView>(R.id.ringDate)
        val fmtT = SimpleDateFormat("HH:mm", Locale.GERMANY)
        val fmtD = SimpleDateFormat("EEEE, d. MMMM", Locale.GERMANY)
        val r = object : Runnable {
            override fun run() {
                val now = Date()
                clock.text = fmtT.format(now)
                date.text = fmtD.format(now)
                handler.postDelayed(this, 1000)
            }
        }
        ticker = r
        handler.post(r)
    }

    private fun act(action: String) {
        sendBroadcast(
            Intent(this, AlarmReceiver::class.java)
                .setAction(action)
                .putExtra(AlarmReceiver.EXTRA_ID, alarmId)
        )
        RingPlayer.stop()
        finishAndRemoveTask()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        // Lautstaerketasten schlummern, Zurueck macht nichts
        return when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_VOLUME_DOWN -> {
                act(AlarmReceiver.ACTION_SNOOZE); true
            }
            KeyEvent.KEYCODE_BACK -> true
            else -> super.onKeyDown(keyCode, event)
        }
    }

    @Deprecated("Zurueck-Taste bewusst blockiert")
    override fun onBackPressed() {
        // nichts
    }

    override fun onDestroy() {
        super.onDestroy()
        ticker?.let { handler.removeCallbacks(it) }
        runCatching { unregisterReceiver(closeReceiver) }
    }
}

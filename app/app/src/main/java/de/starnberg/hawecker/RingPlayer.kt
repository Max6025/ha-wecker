package de.starnberg.hawecker

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/** Spielt den Weckton (Alarm-Stream, Loop) und vibriert. */
object RingPlayer {

    private var player: MediaPlayer? = null
    private var vibrator: Vibrator? = null
    private val handler = Handler(Looper.getMainLooper())
    private var fadeStep = 0
    private var fadeRunnable: Runnable? = null

    fun isPlaying(): Boolean = runCatching { player?.isPlaying == true }.getOrDefault(false)

    fun start(ctx: Context, alarm: Alarm) {
        stop()
        val uri: Uri = alarm.soundUri?.let { runCatching { Uri.parse(it) }.getOrNull() }
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            ?: return

        runCatching {
            val mp = MediaPlayer()
            mp.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            mp.setDataSource(ctx, uri)
            mp.isLooping = true
            mp.prepare()
            mp.setVolume(0.15f, 0.15f)
            mp.start()
            player = mp

            // sanft lauter werden
            fadeStep = 0
            val r = object : Runnable {
                override fun run() {
                    fadeStep++
                    val v = (0.15f + fadeStep * 0.085f).coerceAtMost(1.0f)
                    runCatching { player?.setVolume(v, v) }
                    if (v < 1.0f) handler.postDelayed(this, 2500)
                }
            }
            fadeRunnable = r
            handler.postDelayed(r, 2500)
        }

        // Sicherstellen, dass der Alarm-Stream nicht auf 0 steht
        runCatching {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (am.getStreamVolume(AudioManager.STREAM_ALARM) == 0) {
                val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
                am.setStreamVolume(AudioManager.STREAM_ALARM, (max * 0.6f).toInt(), 0)
            }
        }

        if (alarm.vibrate) {
            val vib = if (Build.VERSION.SDK_INT >= 31) {
                (ctx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                ctx.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }
            vibrator = vib
            val pattern = longArrayOf(0, 600, 700, 600, 1500)
            runCatching {
                vib.vibrate(VibrationEffect.createWaveform(pattern, 0))
            }
        }
    }

    fun stop() {
        fadeRunnable?.let { handler.removeCallbacks(it) }
        fadeRunnable = null
        runCatching {
            player?.let {
                if (it.isPlaying) it.stop()
                it.release()
            }
        }
        player = null
        runCatching { vibrator?.cancel() }
        vibrator = null
    }
}

package de.starnberg.hawecker

import android.content.Context
import android.media.AudioManager
import android.media.AudioTrack
import android.os.Handler
import android.os.Looper

/**
 * Spielt den Weckton (ToneSynth, Alarm-Kanal, Schleife alle 1,6 s) und laesst
 * das Vibrationsmuster des Weckers laufen. Lautstaerke und „langsam lauter
 * werden" kommen aus den Einstellungen.
 */
object RingPlayer {

    private var track: AudioTrack? = null
    private var preview: AudioTrack? = null
    private val handler = Handler(Looper.getMainLooper())
    private var fadeRunnable: Runnable? = null
    private var previewEnde: Runnable? = null

    @Volatile
    private var playing = false

    fun isPlaying(): Boolean = playing

    fun start(ctx: Context, alarm: Alarm) {
        stop()
        val vol = Prefs.vol(ctx) / 100f
        val fade = Prefs.fade(ctx)

        runCatching {
            val t = ToneSynth.track(alarm.tone, fade, loop = true)
            val startPegel = if (fade) 0.15f else 1f
            t.setVolume(vol * startPegel)
            t.play()
            track = t
            playing = true

            if (fade) {
                var schritt = 0
                val r = object : Runnable {
                    override fun run() {
                        schritt++
                        val p = (0.15f + schritt * 0.085f).coerceAtMost(1f)
                        runCatching { track?.setVolume(vol * p) }
                        if (p < 1f) handler.postDelayed(this, 2500)
                    }
                }
                fadeRunnable = r
                handler.postDelayed(r, 2500)
            }
        }

        // Sicherstellen, dass der Alarm-Kanal nicht auf 0 steht
        runCatching {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (am.getStreamVolume(AudioManager.STREAM_ALARM) == 0) {
                val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
                am.setStreamVolume(AudioManager.STREAM_ALARM, (max * 0.6f).toInt(), 0)
            }
        }

        if (Prefs.vib(ctx) && alarm.vibrate) Haptik.musterEndlos(ctx, alarm.vibe)
    }

    fun stop() {
        fadeRunnable?.let { handler.removeCallbacks(it) }
        fadeRunnable = null
        runCatching {
            track?.let {
                if (it.playState == AudioTrack.PLAYSTATE_PLAYING) it.stop()
                it.release()
            }
        }
        track = null
        playing = false
        Haptik.stopp()
    }

    /** Einmaliges Anspielen eines Tons in der Auswahlliste. */
    fun preview(ctx: Context, tone: String) {
        stopPreview()
        runCatching {
            val t = ToneSynth.track(tone, Prefs.fade(ctx), loop = false)
            t.setVolume(Prefs.vol(ctx) / 100f)
            t.play()
            preview = t
            val r = Runnable { stopPreview() }
            previewEnde = r
            handler.postDelayed(r, 1700)
        }
    }

    fun stopPreview() {
        previewEnde?.let { handler.removeCallbacks(it) }
        previewEnde = null
        runCatching {
            preview?.let {
                if (it.playState == AudioTrack.PLAYSTATE_PLAYING) it.stop()
                it.release()
            }
        }
        preview = null
    }
}

package de.starnberg.hawecker

import android.content.Context
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper

/**
 * Spielt den Weckton des Handys (Toene, Alarm-Kanal, Schleife) und laesst das
 * Vibrationsmuster des Weckers laufen. Lautstaerke und „langsam lauter werden"
 * kommen aus den Einstellungen.
 */
object RingPlayer {

    private var player: MediaPlayer? = null
    private var preview: MediaPlayer? = null
    private val handler = Handler(Looper.getMainLooper())
    private var fadeRunnable: Runnable? = null
    private var previewEnde: Runnable? = null

    @Volatile
    private var playing = false

    fun isPlaying(): Boolean = playing

    private fun neuerPlayer(ctx: Context, uriText: String, loop: Boolean): MediaPlayer? {
        val uri = Toene.uri(ctx, uriText) ?: return null
        return runCatching {
            val mp = MediaPlayer()
            mp.setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            mp.setDataSource(ctx, uri)
            mp.isLooping = loop
            mp.prepare()
            mp
        }.getOrNull()
    }

    fun start(ctx: Context, alarm: Alarm) {
        stop()
        val vol = Prefs.vol(ctx) / 100f
        val fade = Prefs.fade(ctx)

        neuerPlayer(ctx, alarm.tone, loop = true)?.let { mp ->
            val startPegel = if (fade) 0.15f else 1f
            mp.setVolume(vol * startPegel, vol * startPegel)
            mp.start()
            player = mp
            playing = true

            if (fade) {
                var schritt = 0
                val r = object : Runnable {
                    override fun run() {
                        schritt++
                        val p = (0.15f + schritt * 0.085f).coerceAtMost(1f)
                        runCatching { player?.setVolume(vol * p, vol * p) }
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
            player?.let {
                if (it.isPlaying) it.stop()
                it.release()
            }
        }
        player = null
        playing = false
        Haptik.stopp()
    }

    /** Anspielen eines Tons in der Auswahlliste, hoechstens ein paar Sekunden. */
    fun preview(ctx: Context, uriText: String) {
        stopPreview()
        neuerPlayer(ctx, uriText, loop = false)?.let { mp ->
            val vol = Prefs.vol(ctx) / 100f
            mp.setVolume(vol, vol)
            mp.setOnCompletionListener { stopPreview() }
            mp.start()
            preview = mp
            val r = Runnable { stopPreview() }
            previewEnde = r
            handler.postDelayed(r, 6000)
        }
    }

    fun stopPreview() {
        previewEnde?.let { handler.removeCallbacks(it) }
        previewEnde = null
        runCatching {
            preview?.let {
                if (it.isPlaying) it.stop()
                it.release()
            }
        }
        preview = null
    }
}

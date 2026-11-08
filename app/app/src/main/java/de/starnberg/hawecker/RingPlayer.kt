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

    /** Alarm-Lautstaerke des Handys vor der Vorschau; -1 = nichts verstellt. */
    private var lautstaerkeVorher = -1
    private const val VORSCHAU_ANTEIL = 0.03f

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
        stopPreview(ctx)
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

    /**
     * Anspielen eines Tons in der Auswahlliste, hoechstens ein paar Sekunden.
     * Dabei steht der Alarm-Kanal des Handys auf 3 %; nach der Vorschau kommt
     * der vorherige Wert zurueck.
     */
    fun preview(ctx: Context, uriText: String) {
        stopPreview(ctx)
        leiseStellen(ctx)
        neuerPlayer(ctx, uriText, loop = false)?.let { mp ->
            mp.setVolume(1f, 1f)
            mp.setOnCompletionListener { stopPreview(ctx) }
            mp.start()
            preview = mp
            val r = Runnable { stopPreview(ctx) }
            previewEnde = r
            handler.postDelayed(r, 6000)
        }
    }

    fun stopPreview(ctx: Context? = null) {
        previewEnde?.let { handler.removeCallbacks(it) }
        previewEnde = null
        runCatching {
            preview?.let {
                if (it.isPlaying) it.stop()
                it.release()
            }
        }
        preview = null
        ctx?.let { zurueckstellen(it) }
    }

    private fun leiseStellen(ctx: Context) {
        runCatching {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (lautstaerkeVorher < 0) lautstaerkeVorher = am.getStreamVolume(AudioManager.STREAM_ALARM)
            val max = am.getStreamMaxVolume(AudioManager.STREAM_ALARM)
            val leise = Math.round(max * VORSCHAU_ANTEIL).coerceAtLeast(1)
            am.setStreamVolume(AudioManager.STREAM_ALARM, leise, 0)
        }
    }

    private fun zurueckstellen(ctx: Context) {
        if (lautstaerkeVorher < 0) return
        runCatching {
            val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            am.setStreamVolume(AudioManager.STREAM_ALARM, lautstaerkeVorher, 0)
        }
        lautstaerkeVorher = -1
    }
}

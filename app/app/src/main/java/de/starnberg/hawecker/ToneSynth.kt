package de.starnberg.hawecker

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.pow
import kotlin.math.sin

/**
 * Erzeugt die acht Wecktoene genau wie die Vorschau im Mockup: ein Paar
 * Frequenzen, dreimal angeschlagen mit 0,22 s Abstand, kurzer Anstieg und
 * exponentielles Ausklingen bis 0,72 s, Wiederholung alle 1,6 s.
 */
object ToneSynth {

    const val SR = 44100
    const val PERIODE_S = 1.6

    val TONES = listOf(
        "Radar", "Morgentau", "Werkstatt", "Vogelzug",
        "Signalhorn", "Sanfter Anstieg", "Funkwecker", "Isar"
    )

    private val HZ = mapOf(
        "Radar" to (660.0 to 880.0),
        "Morgentau" to (523.0 to 784.0),
        "Werkstatt" to (300.0 to 300.0),
        "Vogelzug" to (990.0 to 1320.0),
        "Signalhorn" to (220.0 to 330.0),
        "Sanfter Anstieg" to (440.0 to 660.0),
        "Funkwecker" to (1000.0 to 1000.0),
        "Isar" to (392.0 to 587.0)
    )

    private enum class Welle { SINUS, RECHTECK, DREIECK }

    /** Eine Periode (1,6 s) als 16-Bit-PCM, mono. */
    fun pcm(tone: String, fade: Boolean): ShortArray {
        val (f1, f2) = HZ[tone] ?: (660.0 to 880.0)
        val welle = when (tone) {
            "Werkstatt" -> Welle.RECHTECK
            "Sanfter Anstieg" -> Welle.SINUS
            else -> Welle.DREIECK
        }
        val n = (SR * PERIODE_S).toInt()
        val out = ShortArray(n)
        val anstieg = if (fade) 0.25 else 0.03
        val ende = 0.72
        val schlaege = doubleArrayOf(0.0, 0.22, 0.44)
        val dauer = 0.18
        val pegel = when (welle) { Welle.RECHTECK -> 0.45; Welle.DREIECK -> 0.8; Welle.SINUS -> 0.9 }

        for (i in 0 until n) {
            val t = i.toDouble() / SR
            // Huellkurve der ganzen Gruppe: linear hoch, dann exponentiell auf 0,0001 bei 0,72 s
            val g = when {
                t < anstieg -> t / anstieg
                t < ende -> 0.0001.pow((t - anstieg) / (ende - anstieg))
                else -> 0.0
            }
            if (g <= 0.0) continue
            var s = 0.0
            for ((k, off) in schlaege.withIndex()) {
                val lt = t - off
                if (lt < 0 || lt >= dauer) continue
                val f = if (k % 2 == 0) f1 else f2
                // weiche Flanken je Anschlag gegen Knacken
                val fl = minOf(1.0, lt / 0.005, (dauer - lt) / 0.02)
                s += osc(welle, f, lt) * fl
            }
            val v = (s * g * pegel).coerceIn(-1.0, 1.0)
            out[i] = (v * 32767).toInt().toShort()
        }
        return out
    }

    private fun osc(w: Welle, f: Double, t: Double): Double {
        val ph = f * t
        return when (w) {
            Welle.SINUS -> sin(2 * PI * ph)
            Welle.RECHTECK -> if (sin(2 * PI * ph) >= 0) 1.0 else -1.0
            Welle.DREIECK -> 2 * abs(2 * (ph - floor(ph + 0.5))) - 1
        }
    }

    /** Fertige Spur auf dem Alarm-Kanal; mit [loop] endlos. */
    fun track(tone: String, fade: Boolean, loop: Boolean): AudioTrack {
        val data = pcm(tone, fade)
        val track = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_ALARM)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SR)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO)
                    .build()
            )
            .setBufferSizeInBytes(data.size * 2)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .build()
        track.write(data, 0, data.size)
        if (loop) track.setLoopPoints(0, data.size, -1)
        return track
    }
}

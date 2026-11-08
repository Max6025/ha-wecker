package de.starnberg.hawecker

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/** Vibration: kurze Haptik der Oberflaeche und die Muster des Weckrufs. */
object Haptik {

    /** Muster in ms (Pause, Puls, Pause, ...), zusammen 1,6 s wie der Weckton. */
    private val MUSTER = mapOf(
        "Herzschlag" to longArrayOf(0, 220, 120, 220, 1040),
        "Kurz" to longArrayOf(0, 120, 1480),
        "Stakkato" to longArrayOf(0, 70, 70, 70, 70, 70, 70, 70, 70, 70, 1040),
        "Welle" to longArrayOf(0, 60, 60, 120, 60, 260, 60, 120, 60, 60, 740)
    )

    private var laufend: Vibrator? = null

    private fun vib(ctx: Context): Vibrator? = runCatching {
        if (Build.VERSION.SDK_INT >= 31) {
            (ctx.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            ctx.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        }
    }.getOrNull()

    fun kurz(ctx: Context, ms: Int) {
        val v = vib(ctx) ?: return
        runCatching {
            v.vibrate(VibrationEffect.createOneShot(ms.coerceIn(1, 500).toLong(), VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    /** Radschritt: 8 ms, sehr leise. */
    fun tick(ctx: Context) {
        val v = vib(ctx) ?: return
        runCatching { v.vibrate(VibrationEffect.createOneShot(8, 40)) }
    }

    /** Ein Durchlauf des Musters (Vorschau in der Auswahl). */
    fun muster(ctx: Context, name: String) {
        val m = MUSTER[name] ?: return
        val v = vib(ctx) ?: return
        runCatching { v.vibrate(VibrationEffect.createWaveform(m, -1)) }
    }

    /** Muster endlos, bis stopp(). */
    fun musterEndlos(ctx: Context, name: String) {
        val m = MUSTER[name] ?: MUSTER["Herzschlag"]!!
        val v = vib(ctx) ?: return
        laufend = v
        runCatching { v.vibrate(VibrationEffect.createWaveform(m, 0)) }
    }

    fun stopp() {
        runCatching { laufend?.cancel() }
        laufend = null
    }
}

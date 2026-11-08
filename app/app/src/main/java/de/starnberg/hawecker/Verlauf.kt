package de.starnberg.hawecker

import android.graphics.Color
import androidx.core.app.NotificationCompat

/**
 * Baut die Segmente fuer NotificationCompat.ProgressStyle (Live-Balken oben).
 * Uebernommen aus der Kalender-App; dort hat sich gezeigt:
 *  1. Die Laengen aller Segmente muessen zusammen exakt 100 ergeben.
 *  2. Die Farben muessen deckend sein, halbtransparente Werte fliegen raus.
 *  3. setStyledByProgress(false) ist Pflicht, sonst ueberschreibt Android die Abstufung.
 * Fehlt eines davon, zeichnet Android einen einfachen weissen Balken.
 */
object Verlauf {

    const val SEGMENTE = 10
    private const val LAENGE = 10

    /**
     * Verbrauchte Segmente in voller Farbe, noch nicht erreichte abgedunkelt,
     * das laufende anteilig gemischt - die Fuellung wandert weich.
     */
    fun segmente(von: Int, bis: Int, prozent: Int): List<NotificationCompat.ProgressStyle.Segment> {
        val liste = ArrayList<NotificationCompat.ProgressStyle.Segment>(SEGMENTE)
        val leer = deckend(mische(bis, Color.BLACK, 0.78f))
        for (i in 0 until SEGMENTE) {
            val start = i * LAENGE
            val ende = start + LAENGE
            val ton = deckend(mische(von, bis, i.toFloat() / (SEGMENTE - 1)))
            val farbe = when {
                prozent >= ende -> ton
                prozent <= start -> leer
                else -> deckend(mische(leer, ton, (prozent - start).toFloat() / LAENGE))
            }
            liste += NotificationCompat.ProgressStyle.Segment(LAENGE).setColor(farbe)
        }
        return liste
    }

    /** "#RRGGBB" der Kategorie -> deckende Farbe; Fallback Akzent des Mockups. */
    fun farbe(hex: String?): Int =
        runCatching { deckend(Color.parseColor(hex)) }.getOrDefault(0xFF74B4FF.toInt())

    /** Etwas hellere Variante fuer den Anfang des Verlaufs. */
    fun hell(c: Int): Int = deckend(mische(c, Color.WHITE, 0.35f))

    private fun deckend(c: Int): Int = Color.rgb(Color.red(c), Color.green(c), Color.blue(c))

    private fun mische(a: Int, b: Int, t: Float): Int {
        val f = t.coerceIn(0f, 1f)
        return Color.rgb(
            (Color.red(a) + (Color.red(b) - Color.red(a)) * f).toInt(),
            (Color.green(a) + (Color.green(b) - Color.green(a)) * f).toInt(),
            (Color.blue(a) + (Color.blue(b) - Color.blue(a)) * f).toInt()
        )
    }
}

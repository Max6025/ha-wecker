package de.starnberg.hawecker

import android.content.Context
import java.util.Calendar
import java.util.Locale

/**
 * Schlafenszeit: ein taegliches Fenster von Beginn bis Ende (Ende darf nach
 * Mitternacht liegen). Waehrend des Fensters zeigt die App eine stille
 * Live-Benachrichtigung und meldet "Schlafenszeit aktiv" an Home Assistant.
 */
object SleepTime {

    data class Window(val start: Long, val end: Long) {
        fun contains(t: Long) = t >= start && t < end
    }

    fun timeString(minutes: Int): String =
        String.format(Locale.GERMANY, "%02d:%02d", minutes / 60, minutes % 60)

    /** "22:30" -> 1350, null bei Unsinn. */
    fun parse(text: String): Int? {
        val m = Regex("^\\s*(\\d{1,2})[:.](\\d{2})\\s*$").find(text) ?: return null
        val h = m.groupValues[1].toInt()
        val min = m.groupValues[2].toInt()
        if (h !in 0..23 || min !in 0..59) return null
        return h * 60 + min
    }

    private fun at(dayBase: Calendar, minutes: Int): Long {
        val c = dayBase.clone() as Calendar
        c.set(Calendar.HOUR_OF_DAY, minutes / 60)
        c.set(Calendar.MINUTE, minutes % 60)
        c.set(Calendar.SECOND, 0)
        c.set(Calendar.MILLISECOND, 0)
        return c.timeInMillis
    }

    /**
     * Das Fenster, das gerade laeuft, sonst das naechste. null wenn aus.
     * Geprueft werden die Fenster, die gestern, heute und an den Folgetagen beginnen.
     */
    fun window(ctx: Context, now: Long = System.currentTimeMillis()): Window? {
        if (!Prefs.sleepEnabled(ctx)) return null
        val startMin = Prefs.sleepStart(ctx)
        val endMin = Prefs.sleepEnd(ctx)
        val days = Prefs.sleepDays(ctx)
        if (days == 0) return null
        val base = Calendar.getInstance().apply { timeInMillis = now; add(Calendar.DAY_OF_YEAR, -1) }
        for (i in 0 until 9) {
            if (((days shr Alarm.isoIndex(base)) and 1) == 1) {
                val start = at(base, startMin)
                var end = at(base, endMin)
                if (end <= start) end += 24 * 3600_000L
                if (end > now) return Window(start, end)
            }
            base.add(Calendar.DAY_OF_YEAR, 1)
        }
        return null
    }

    fun isActive(ctx: Context, now: Long = System.currentTimeMillis()): Boolean =
        window(ctx, now)?.contains(now) == true

    fun label(ctx: Context): String =
        "${timeString(Prefs.sleepStart(ctx))} - ${timeString(Prefs.sleepEnd(ctx))}"
}

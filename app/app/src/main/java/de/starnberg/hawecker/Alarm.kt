package de.starnberg.hawecker

import org.json.JSONObject
import java.util.Calendar
import java.util.Locale

/**
 * Ein einzelner Wecker.
 * days ist eine Bitmaske: Bit 0 = Montag ... Bit 6 = Sonntag. 0 = einmalig.
 */
data class Alarm(
    var id: Int,
    var label: String = "",
    var hour: Int = 7,
    var minute: Int = 0,
    var days: Int = 0,
    var enabled: Boolean = true,
    var vibrate: Boolean = true,
    var snoozeMinutes: Int = 9,
    var soundUri: String? = null,
    var skipNext: Boolean = false,
    var snoozedUntil: Long = 0L
) {

    fun timeString(): String = String.format(Locale.GERMANY, "%02d:%02d", hour, minute)

    fun isRepeating(): Boolean = days != 0

    /** Liefert die naechsten [count] Ausloesezeitpunkte (ohne Snooze-Beruecksichtigung). */
    fun occurrences(now: Long, count: Int): List<Long> {
        val result = ArrayList<Long>()
        val cal = Calendar.getInstance()
        cal.timeInMillis = now
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)
        cal.set(Calendar.HOUR_OF_DAY, hour)
        cal.set(Calendar.MINUTE, minute)
        if (cal.timeInMillis <= now) cal.add(Calendar.DAY_OF_YEAR, 1)
        var guard = 0
        while (result.size < count && guard < 400) {
            if (days == 0 || ((days shr isoIndex(cal)) and 1) == 1) {
                result.add(cal.timeInMillis)
            }
            cal.add(Calendar.DAY_OF_YEAR, 1)
            guard++
        }
        return result
    }

    /** Naechster echter Ausloesezeitpunkt in Millis, 0 wenn der Wecker aus ist. */
    fun nextTriggerAt(now: Long = System.currentTimeMillis()): Long {
        if (!enabled) return 0L
        if (snoozedUntil > now) return snoozedUntil
        val n = if (skipNext) 2 else 1
        val occ = occurrences(now, n)
        return if (occ.size >= n) occ[n - 1] else 0L
    }

    fun daysLabel(): String = when (days) {
        0 -> "Einmalig"
        ALL_DAYS -> "Taeglich"
        WORKDAYS -> "Mo-Fr"
        WEEKEND -> "Sa+So"
        else -> (0..6).filter { ((days shr it) and 1) == 1 }
            .joinToString(" ") { DAY_SHORT[it] }
    }

    fun toJson(): JSONObject {
        val o = JSONObject()
        o.put("id", id)
        o.put("label", label)
        o.put("hour", hour)
        o.put("minute", minute)
        o.put("days", days)
        o.put("enabled", enabled)
        o.put("vibrate", vibrate)
        o.put("snoozeMinutes", snoozeMinutes)
        o.put("soundUri", soundUri ?: JSONObject.NULL)
        o.put("skipNext", skipNext)
        o.put("snoozedUntil", snoozedUntil)
        return o
    }

    companion object {
        const val ALL_DAYS = 0b1111111
        const val WORKDAYS = 0b0011111
        const val WEEKEND = 0b1100000
        val DAY_SHORT = arrayOf("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

        /** Calendar-Wochentag -> 0 = Montag ... 6 = Sonntag */
        fun isoIndex(cal: Calendar): Int = (cal.get(Calendar.DAY_OF_WEEK) + 5) % 7

        fun fromJson(o: JSONObject): Alarm = Alarm(
            id = o.optInt("id"),
            label = o.optString("label", ""),
            hour = o.optInt("hour", 7),
            minute = o.optInt("minute", 0),
            days = o.optInt("days", 0),
            enabled = o.optBoolean("enabled", true),
            vibrate = o.optBoolean("vibrate", true),
            snoozeMinutes = o.optInt("snoozeMinutes", 9),
            soundUri = if (o.isNull("soundUri")) null else o.optString("soundUri", "").ifEmpty { null },
            skipNext = o.optBoolean("skipNext", false),
            snoozedUntil = o.optLong("snoozedUntil", 0L)
        )
    }
}

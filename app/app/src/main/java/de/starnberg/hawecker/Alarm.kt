package de.starnberg.hawecker

import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar
import java.util.Locale

/**
 * Ein einzelner Wecker.
 * days ist eine Bitmaske: Bit 0 = Montag ... Bit 6 = Sonntag. 0 = einmalig.
 * Die Oberflaeche rechnet mit JS-Wochentagen (0 = Sonntag), siehe daysJs().
 */
data class Alarm(
    var id: Int,
    var label: String = "",
    var hour: Int = 7,
    var minute: Int = 0,
    var days: Int = 0,
    var enabled: Boolean = true,
    /** Kategorie (CategoryStore), bestimmt Bild und Farbe. */
    var catId: String = "k1",
    /** Weckton als URI aus dem Handy (Toene); leer = Standard-Alarmton. */
    var tone: String = "",
    /** Vibrationsmuster: Herzschlag, Kurz, Stakkato, Welle oder Aus. */
    var vibe: String = "Herzschlag",
    var snoozeMinutes: Int = 9,
    var skipNext: Boolean = false,
    var snoozedUntil: Long = 0L
) {

    val vibrate: Boolean get() = vibe != "Aus"

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

    /** Wochentage als JS-Liste (0 = Sonntag ... 6 = Samstag). */
    fun daysJs(): JSONArray {
        val a = JSONArray()
        for (i in 0..6) if (((days shr i) and 1) == 1) a.put((i + 1) % 7)
        return a
    }

    fun toJson(): JSONObject {
        val o = JSONObject()
        o.put("id", id)
        o.put("label", label)
        o.put("hour", hour)
        o.put("minute", minute)
        o.put("days", days)
        o.put("enabled", enabled)
        o.put("cat", catId)
        o.put("tone", tone)
        o.put("vibe", vibe)
        o.put("snoozeMinutes", snoozeMinutes)
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

        /** JS-Wochentagsliste (0 = Sonntag) -> Bitmaske (Bit 0 = Montag). */
        fun daysFromJs(arr: JSONArray?): Int {
            var mask = 0
            if (arr == null) return 0
            for (i in 0 until arr.length()) {
                val js = arr.optInt(i, -1)
                if (js in 0..6) mask = mask or (1 shl ((js + 6) % 7))
            }
            return mask
        }

        fun fromJson(o: JSONObject): Alarm = Alarm(
            id = o.optInt("id"),
            label = o.optString("label", ""),
            hour = o.optInt("hour", 7),
            minute = o.optInt("minute", 0),
            days = o.optInt("days", 0),
            enabled = o.optBoolean("enabled", true),
            catId = o.optString("cat", "k1").ifEmpty { "k1" },
            // Ton ist eine URI; Namen aus 2.0 (Radar, Isar ...) und leer = Standard-Alarmton
            tone = o.optString("tone", "").let { if (it.contains("://")) it else "" },
            // bis 1.7 gab es nur den Schalter "vibrate"
            vibe = o.optString(
                "vibe",
                if (o.has("vibrate") && !o.optBoolean("vibrate", true)) "Aus" else "Herzschlag"
            ).ifEmpty { "Herzschlag" },
            snoozeMinutes = o.optInt("snoozeMinutes", 9),
            skipNext = o.optBoolean("skipNext", false),
            snoozedUntil = o.optLong("snoozedUntil", 0L)
        )
    }
}

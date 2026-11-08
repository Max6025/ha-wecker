package de.starnberg.hawecker

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

/** Baut die JSON-Antwort fuer Home Assistant. */
object ApiPayload {

    private fun isoFmt(): SimpleDateFormat =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.US)

    fun iso(ts: Long): String = isoFmt().format(Date(ts))

    fun humanIn(ms: Long): String {
        if (ms <= 0) return "jetzt"
        val total = ms / 60000L
        val d = total / 1440
        val h = (total % 1440) / 60
        val m = total % 60
        return buildString {
            if (d > 0) append("${d} Tg ")
            if (d > 0 || h > 0) append("${h} Std ")
            append("${m} Min")
        }.trim()
    }

    private fun alarmJson(ctx: Context, a: Alarm, now: Long): JSONObject {
        val o = JSONObject()
        val next = a.nextTriggerAt(now)
        o.put("id", a.id)
        o.put("name", if (a.label.isBlank()) "Wecker ${a.timeString()}" else a.label)
        o.put("label", a.label)
        o.put("time", a.timeString())
        o.put("hour", a.hour)
        o.put("minute", a.minute)
        o.put("enabled", a.enabled)
        o.put("repeating", a.isRepeating())
        o.put("days_mask", a.days)
        o.put("days_label", a.daysLabel())
        val dl = JSONArray()
        for (i in 0..6) if (((a.days shr i) and 1) == 1) dl.put(Alarm.DAY_SHORT[i])
        o.put("days", dl)
        o.put("vibrate", a.vibrate)
        o.put("vibration", a.vibe)
        o.put("ton", Toene.name(ctx, a.tone))
        val k = CategoryStore.get(ctx, a.catId)
        o.put("kategorie", JSONObject()
            .put("id", k.id).put("name", k.name).put("bild", k.bild).put("farbe", k.farbe))
        o.put("snooze_minutes", a.snoozeMinutes)
        o.put("skip_next", a.skipNext)
        o.put("snoozed", a.snoozedUntil > now)
        o.put("snoozed_until", if (a.snoozedUntil > now) iso(a.snoozedUntil) else JSONObject.NULL)
        o.put("ringing", RingState.ringingId == a.id)
        if (next > 0) {
            o.put("next_trigger", iso(next))
            o.put("next_trigger_ts", next / 1000L)
            o.put("next_trigger_in", humanIn(next - now))
            o.put("next_trigger_in_minutes", ((next - now) / 60000L))
        } else {
            o.put("next_trigger", JSONObject.NULL)
            o.put("next_trigger_ts", JSONObject.NULL)
            o.put("next_trigger_in", JSONObject.NULL)
            o.put("next_trigger_in_minutes", JSONObject.NULL)
        }
        return o
    }

    fun build(ctx: Context): JSONObject {
        val now = System.currentTimeMillis()
        val all = AlarmStore.all(ctx)
        val root = JSONObject()

        val arrAll = JSONArray()
        val arrOn = JSONArray()
        val arrOff = JSONArray()
        for (a in all) {
            val j = alarmJson(ctx, a, now)
            arrAll.put(j)
            if (a.enabled) arrOn.put(j) else arrOff.put(j)
        }

        val next = AlarmScheduler.nextAlarm(ctx)

        root.put("state", if (next != null) iso(next.second) else "")
        root.put("next_alarm", if (next != null) alarmJson(ctx, next.first, now) else JSONObject.NULL)
        root.put("next_alarm_time", if (next != null) next.first.timeString() else JSONObject.NULL)
        root.put("next_alarm_ts", if (next != null) next.second / 1000L else JSONObject.NULL)
        root.put("next_alarm_in", if (next != null) humanIn(next.second - now) else JSONObject.NULL)
        root.put(
            "next_alarm_name",
            if (next != null) {
                if (next.first.label.isBlank()) "Wecker ${next.first.timeString()}" else next.first.label
            } else JSONObject.NULL
        )

        root.put("total_count", all.size)
        root.put("active_count", all.count { it.enabled })
        root.put("inactive_count", all.count { !it.enabled })
        root.put("ringing", RingState.isRinging())
        root.put("ringing_id", if (RingState.isRinging()) RingState.ringingId else JSONObject.NULL)
        root.put("snoozed", all.any { it.snoozedUntil > now })
        root.put("skipped_count", all.count { it.skipNext && it.enabled })

        root.put("alarms", arrAll)
        root.put("active_alarms", arrOn)
        root.put("inactive_alarms", arrOff)

        val sum = StringBuilder()
        for (a in all) {
            val mark = if (a.enabled) "AN " else "AUS"
            sum.append(mark).append("  ").append(a.timeString()).append("  ")
                .append(a.daysLabel())
            if (a.label.isNotBlank()) sum.append("  (").append(a.label).append(")")
            sum.append("\n")
        }
        root.put("summary", sum.toString().trim())

        // Schlafenszeit
        val sleep = JSONObject()
        val w = SleepTime.window(ctx, now)
        val sleepActive = w?.contains(now) == true
        sleep.put("enabled", Prefs.sleepEnabled(ctx))
        sleep.put("active", sleepActive)
        sleep.put("start", SleepTime.timeString(Prefs.sleepStart(ctx)))
        sleep.put("end", SleepTime.timeString(Prefs.sleepEnd(ctx)))
        sleep.put("days_mask", Prefs.sleepDays(ctx))
        sleep.put("next_start", if (w != null && !sleepActive) iso(w.start) else JSONObject.NULL)
        sleep.put("next_end", if (w != null) iso(w.end) else JSONObject.NULL)
        sleep.put("remaining_minutes", if (w != null && sleepActive) (w.end - now) / 60000L else JSONObject.NULL)
        root.put("sleep", sleep)
        root.put("sleep_active", sleepActive)

        val kats = JSONArray()
        for (k in CategoryStore.all(ctx)) {
            kats.put(JSONObject().put("id", k.id).put("name", k.name).put("bild", k.bild).put("farbe", k.farbe)
                .put("wecker", all.count { it.catId == k.id }))
        }
        root.put("kategorien", kats)

        root.put("prewarn_minutes", Prefs.prewarnMinutes(ctx))
        root.put("device_time", iso(now))
        root.put("timezone", TimeZone.getDefault().id)
        root.put("api_version", 3)
        return root
    }
}

package de.starnberg.hawecker

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import org.json.JSONArray
import org.json.JSONObject

/**
 * Der komplette Zustand fuer die Oberflaeche (assets/ui/app.js) als JSON -
 * und der Weg zurueck: die Oberflaeche schickt denselben Aufbau, hier wird er
 * in Wecker, Kategorien und Einstellungen zerlegt, geplant und an HA gemeldet.
 */
object UiState {

    fun json(ctx: Context): String {
        val now = System.currentTimeMillis()
        val root = JSONObject()

        root.put("vol", Prefs.vol(ctx))
        root.put("fade", Prefs.fade(ctx))
        root.put("vib", Prefs.vib(ctx))
        root.put("defTone", Prefs.defTone(ctx))
        root.put("defToneName", Toene.name(ctx, Prefs.defTone(ctx)))
        root.put("defSnooze", Prefs.defSnooze(ctx))
        root.put("prewarn", Prefs.prewarnMinutes(ctx))

        val cats = JSONArray()
        CategoryStore.all(ctx).forEach { cats.put(it.toJson()) }
        root.put("cats", cats)

        val alarms = JSONArray()
        for (a in AlarmStore.all(ctx)) {
            val o = JSONObject()
            o.put("id", a.id)
            o.put("h", a.hour)
            o.put("m", a.minute)
            o.put("label", a.label)
            o.put("cat", a.catId)
            o.put("days", a.daysJs())
            o.put("on", a.enabled)
            o.put("tone", a.tone)
            o.put("toneName", Toene.name(ctx, a.tone))
            o.put("vibe", a.vibe)
            o.put("snooze", a.snoozeMinutes)
            o.put("skipNext", a.skipNext)
            o.put("snoozedUntil", a.snoozedUntil)
            val next = a.nextTriggerAt(now)
            o.put("next", if (next > 0) next else JSONObject.NULL)
            alarms.put(o)
        }
        root.put("alarms", alarms)

        val api = JSONObject()
        api.put("url", Prefs.haAdresse(ctx))
        api.put("id", Prefs.webhookId(ctx))
        api.put("on", Prefs.pushEnabled(ctx))
        api.put("letzter", Prefs.lastPushResult(ctx))
        root.put("api", api)

        val sleep = JSONObject()
        sleep.put("on", Prefs.sleepEnabled(ctx))
        sleep.put("start", SleepTime.timeString(Prefs.sleepStart(ctx)))
        sleep.put("end", SleepTime.timeString(Prefs.sleepEnd(ctx)))
        sleep.put("notify", Prefs.sleepNotify(ctx))
        sleep.put("active", SleepTime.isActive(ctx, now))
        root.put("sleep", sleep)

        val perms = JSONObject()
        val pm = ctx.getSystemService(Context.POWER_SERVICE) as PowerManager
        perms.put(
            "notify",
            Build.VERSION.SDK_INT < 33 ||
                ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
        )
        perms.put("fullscreen", Notifications.canUseFullScreenIntent(ctx))
        perms.put("exact", AlarmScheduler.canScheduleExact(ctx))
        perms.put("battery", pm.isIgnoringBatteryOptimizations(ctx.packageName))
        perms.put("promote", Notifications.canPromote(ctx))
        perms.put("overlay", Settings.canDrawOverlays(ctx))
        root.put("perms", perms)

        root.put("ringing", RingState.ringingId)
        root.put("version", runCatching {
            ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName
        }.getOrNull() ?: "")
        return root.toString()
    }

    /**
     * Zustand aus der Oberflaeche uebernehmen. Neue Wecker (id 0) und neue
     * Kategorien (leere id) bekommen hier ihre Nummer. Liefert den frischen
     * Zustand zurueck, damit die Oberflaeche IDs und naechste Ausloesung kennt.
     */
    fun apply(ctx: Context, json: String, pushen: Boolean): String {
        val o = JSONObject(json)

        Prefs.setVol(ctx, o.optInt("vol", Prefs.vol(ctx)))
        Prefs.setFade(ctx, o.optBoolean("fade", Prefs.fade(ctx)))
        Prefs.setVib(ctx, o.optBoolean("vib", Prefs.vib(ctx)))
        Prefs.setDefTone(ctx, o.optString("defTone", Prefs.defTone(ctx)))
        Prefs.setDefSnooze(ctx, o.optInt("defSnooze", Prefs.defSnooze(ctx)))
        Prefs.setPrewarnMinutes(ctx, o.optInt("prewarn", Prefs.prewarnMinutes(ctx)).coerceIn(0, 240))

        // Kategorien
        val cats = ArrayList<Category>()
        o.optJSONArray("cats")?.let { arr ->
            for (i in 0 until arr.length()) {
                val c = Category.fromJson(arr.getJSONObject(i))
                if (c.id.isEmpty()) c.id = CategoryStore.nextId(ctx)
                cats.add(c)
            }
        }
        if (cats.isEmpty()) cats.addAll(CategoryStore.DEFAULTS.map { it.copy() })
        CategoryStore.saveAll(ctx, cats)
        val catIds = cats.map { it.id }.toSet()

        // Wecker
        o.optJSONArray("alarms")?.let { arr ->
            val list = ArrayList<Alarm>()
            for (i in 0 until arr.length()) {
                val j = arr.getJSONObject(i)
                var id = j.optInt("id", 0)
                if (id <= 0) id = AlarmStore.nextId(ctx)
                val a = Alarm(
                    id = id,
                    label = j.optString("label", "").trim(),
                    hour = j.optInt("h", 6).coerceIn(0, 23),
                    minute = j.optInt("m", 30).coerceIn(0, 59),
                    days = Alarm.daysFromJs(j.optJSONArray("days")),
                    enabled = j.optBoolean("on", true),
                    catId = j.optString("cat", cats[0].id),
                    tone = j.optString("tone", "").let { if (it.contains("://")) it else "" },
                    vibe = j.optString("vibe", "Herzschlag").ifEmpty { "Herzschlag" },
                    snoozeMinutes = j.optInt("snooze", Prefs.defSnooze(ctx)).coerceIn(0, 180),
                    skipNext = j.optBoolean("skipNext", false),
                    snoozedUntil = j.optLong("snoozedUntil", 0L)
                )
                if (!catIds.contains(a.catId)) a.catId = cats[0].id
                if (!a.enabled) {
                    a.skipNext = false
                    a.snoozedUntil = 0L
                }
                list.add(a)
            }
            AlarmStore.replaceAll(ctx, list)
        }

        // Schnittstelle
        o.optJSONObject("api")?.let { api ->
            Prefs.setHaAdresse(ctx, api.optString("url", ""))
            Prefs.setWebhookId(ctx, api.optString("id", ""))
            Prefs.setPushEnabled(ctx, api.optBoolean("on", true))
        }

        // Schlafenszeit
        o.optJSONObject("sleep")?.let { s ->
            Prefs.setSleepEnabled(ctx, s.optBoolean("on", false))
            Prefs.setSleepNotify(ctx, s.optBoolean("notify", true))
            SleepTime.parse(s.optString("start", ""))?.let { Prefs.setSleepStart(ctx, it) }
            SleepTime.parse(s.optString("end", ""))?.let { Prefs.setSleepEnd(ctx, it) }
        }

        AlarmScheduler.scheduleAll(ctx)
        if (pushen) HaPush.pushAsync(ctx)
        return json(ctx)
    }
}

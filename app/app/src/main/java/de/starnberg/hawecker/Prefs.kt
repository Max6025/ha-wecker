package de.starnberg.hawecker

import android.content.Context

/** App-Einstellungen: Klang, Vorgaben, Vorwarnung, Schlafenszeit und Push an Home Assistant. */
object Prefs {
    private const val PREFS = "hawecker_prefs"

    private fun p(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // --- Klang und Vorgaben fuer neue Wecker ------------------------------
    /** Lautstaerke 0-100, wirkt auf den Weckton. */
    fun vol(ctx: Context): Int = p(ctx).getInt("vol", 75)
    fun setVol(ctx: Context, v: Int) = p(ctx).edit().putInt("vol", v.coerceIn(0, 100)).apply()

    /** Langsam lauter werden. */
    fun fade(ctx: Context): Boolean = p(ctx).getBoolean("fade", true)
    fun setFade(ctx: Context, v: Boolean) = p(ctx).edit().putBoolean("fade", v).apply()

    /** Vibration grundsaetzlich erlauben (Weckruf, Haptik der Oberflaeche). */
    fun vib(ctx: Context): Boolean = p(ctx).getBoolean("vib", true)
    fun setVib(ctx: Context, v: Boolean) = p(ctx).edit().putBoolean("vib", v).apply()

    /** Weckton-URI fuer neue Wecker; leer = Standard-Alarmton des Handys. Alte Namen (bis 2.0) zaehlen als leer. */
    fun defTone(ctx: Context): String {
        val v = p(ctx).getString("def_tone", "") ?: ""
        return if (v.contains("://")) v else ""
    }
    fun setDefTone(ctx: Context, v: String) = p(ctx).edit().putString("def_tone", v).apply()

    fun defSnooze(ctx: Context): Int = p(ctx).getInt("def_snooze", 9)
    fun setDefSnooze(ctx: Context, v: Int) = p(ctx).edit().putInt("def_snooze", v.coerceIn(0, 180)).apply()

    /** Minuten vor dem Weckruf fuer die Vorwarnung (Live-Benachrichtigung). 0 = aus. */
    fun prewarnMinutes(ctx: Context): Int = p(ctx).getInt("prewarn_minutes", 5)
    fun setPrewarnMinutes(ctx: Context, v: Int) = p(ctx).edit().putInt("prewarn_minutes", v).apply()

    // --- Schlafenszeit -----------------------------------------------------
    fun sleepEnabled(ctx: Context): Boolean = p(ctx).getBoolean("sleep_enabled", false)
    fun setSleepEnabled(ctx: Context, v: Boolean) = p(ctx).edit().putBoolean("sleep_enabled", v).apply()

    /** Beginn und Ende als Minuten seit Mitternacht. Ende <= Beginn heisst: am naechsten Tag. */
    fun sleepStart(ctx: Context): Int = p(ctx).getInt("sleep_start", 22 * 60 + 30)
    fun setSleepStart(ctx: Context, v: Int) = p(ctx).edit().putInt("sleep_start", v).apply()
    fun sleepEnd(ctx: Context): Int = p(ctx).getInt("sleep_end", 6 * 60 + 30)
    fun setSleepEnd(ctx: Context, v: Int) = p(ctx).edit().putInt("sleep_end", v).apply()

    /** Wochentage, an denen die Schlafenszeit beginnt (Bitmaske wie beim Wecker). */
    fun sleepDays(ctx: Context): Int = p(ctx).getInt("sleep_days", Alarm.ALL_DAYS)
    fun setSleepDays(ctx: Context, v: Int) = p(ctx).edit().putInt("sleep_days", v).apply()

    /** Waehrend der Schlafenszeit eine stille Live-Benachrichtigung zeigen. */
    fun sleepNotify(ctx: Context): Boolean = p(ctx).getBoolean("sleep_notify", true)
    fun setSleepNotify(ctx: Context, v: Boolean) = p(ctx).edit().putBoolean("sleep_notify", v).apply()

    // --- Push an Home Assistant (Webhook, auch unterwegs) -----------------

    /** Fest eingebaute HA-Adresse; die App benutzt nur einer. Ohne Port, HA haengt hinter HTTPS. */
    const val HA_ADRESSE_STANDARD = "https://crespina.eurasburg.org"

    /** HA-Adresse (Basis, ohne /api/webhook). Leer heisst: eingebaute Adresse. */
    fun haAdresse(ctx: Context): String {
        migrate(ctx)
        val v = (p(ctx).getString("ha_adresse", "") ?: "").trim().trimEnd('/')
        return if (v.isEmpty()) HA_ADRESSE_STANDARD else v
    }
    fun setHaAdresse(ctx: Context, v: String) =
        p(ctx).edit().putString("ha_adresse", v.trim().trimEnd('/')).apply()

    /** Webhook-ID, wie die Integration sie beim Anlegen des Weckers anzeigt. */
    fun webhookId(ctx: Context): String {
        migrate(ctx)
        return (p(ctx).getString("webhook_id", "") ?: "").trim()
    }
    fun setWebhookId(ctx: Context, v: String) {
        var id = v.trim()
        // Ganze Adresse eingefuegt? Dann Basis und ID auseinandernehmen.
        val i = id.indexOf("/api/webhook/")
        if (i >= 0) {
            setHaAdresse(ctx, id.substring(0, i))
            id = id.substring(i + "/api/webhook/".length)
        }
        p(ctx).edit().putString("webhook_id", id.trim('/')).apply()
    }

    /** Vollstaendige Webhook-Adresse aus Basis und ID; leer ohne ID. */
    fun webhookUrl(ctx: Context): String {
        val id = webhookId(ctx)
        if (id.isEmpty()) return ""
        return "${haAdresse(ctx)}/api/webhook/$id"
    }

    /** Bis 1.6 stand die ganze Adresse in einem Feld. Einmal aufteilen. */
    private fun migrate(ctx: Context) {
        val alt = p(ctx).getString("webhook_url", null) ?: return
        val i = alt.indexOf("/api/webhook/")
        val e = p(ctx).edit().remove("webhook_url")
        if (i >= 0) {
            e.putString("ha_adresse", alt.substring(0, i).trim().trimEnd('/'))
            e.putString("webhook_id", alt.substring(i + "/api/webhook/".length).trim().trim('/'))
        }
        e.apply()
    }

    fun pushEnabled(ctx: Context): Boolean = p(ctx).getBoolean("push_enabled", true)
    fun setPushEnabled(ctx: Context, v: Boolean) = p(ctx).edit().putBoolean("push_enabled", v).apply()

    fun lastPushResult(ctx: Context): String = p(ctx).getString("push_result", "noch nie") ?: "noch nie"
    fun setLastPushResult(ctx: Context, v: String) = p(ctx).edit().putString("push_result", v).apply()
}

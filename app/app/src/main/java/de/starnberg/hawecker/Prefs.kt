package de.starnberg.hawecker

import android.content.Context

/** App-Einstellungen: Vorwarnung, Schlafenszeit und Push an Home Assistant. */
object Prefs {
    private const val PREFS = "hawecker_prefs"

    private fun p(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

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
    /** Vollstaendige Webhook-Adresse, z. B. https://ha.x.de/api/webhook/abc */
    fun webhookUrl(ctx: Context): String = (p(ctx).getString("webhook_url", "") ?: "").trim()
    fun setWebhookUrl(ctx: Context, v: String) = p(ctx).edit().putString("webhook_url", v.trim()).apply()

    fun pushEnabled(ctx: Context): Boolean = p(ctx).getBoolean("push_enabled", true)
    fun setPushEnabled(ctx: Context, v: Boolean) = p(ctx).edit().putBoolean("push_enabled", v).apply()

    fun lastPushResult(ctx: Context): String = p(ctx).getString("push_result", "noch nie") ?: "noch nie"
    fun setLastPushResult(ctx: Context, v: String) = p(ctx).edit().putString("push_result", v).apply()
}

package de.starnberg.hawecker

import android.content.Context

/** App-Einstellungen: Vorwarnung und Push an Home Assistant. */
object Prefs {
    private const val PREFS = "hawecker_prefs"

    private fun p(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)



    /** Minuten vor dem Weckruf fuer die stumme Vorwarnung. 0 = aus. */
    fun prewarnMinutes(ctx: Context): Int = p(ctx).getInt("prewarn_minutes", 10)
    fun setPrewarnMinutes(ctx: Context, v: Int) = p(ctx).edit().putInt("prewarn_minutes", v).apply()

    // --- Push an Home Assistant (Webhook, auch unterwegs) -----------------
    /** Vollstaendige Webhook-Adresse, z. B. https://ha.x.de/api/webhook/abc */
    fun webhookUrl(ctx: Context): String = (p(ctx).getString("webhook_url", "") ?: "").trim()
    fun setWebhookUrl(ctx: Context, v: String) = p(ctx).edit().putString("webhook_url", v.trim()).apply()

    fun pushEnabled(ctx: Context): Boolean = p(ctx).getBoolean("push_enabled", true)
    fun setPushEnabled(ctx: Context, v: Boolean) = p(ctx).edit().putBoolean("push_enabled", v).apply()

    fun lastPushResult(ctx: Context): String = p(ctx).getString("push_result", "noch nie") ?: "noch nie"
    fun setLastPushResult(ctx: Context, v: String) = p(ctx).edit().putString("push_result", v).apply()

}

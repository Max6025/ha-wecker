package de.starnberg.hawecker

import android.content.BroadcastReceiver
import android.content.Context
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Meldet den Weckerstand an Home Assistant - per Webhook, rein ereignisgesteuert.
 *
 * Kein Dienst, kein Intervall, kein Hintergrundbetrieb: gesendet wird nur,
 * wenn sich wirklich etwas aendert (Wecker angelegt, geaendert, geschaltet,
 * klingelt, geschlummert, gestoppt) sowie nach einem Neustart. Dazwischen
 * laeuft nichts. Schlaegt ein Versand fehl, plant die App genau einen
 * Wiederholungsversuch ueber den AlarmManager - auch das kostet im Leerlauf
 * nichts.
 */
object HaPush {

    @Volatile
    private var busy = false

    fun configured(ctx: Context): Boolean {
        val url = Prefs.webhookUrl(ctx)
        return Prefs.pushEnabled(ctx) && url.startsWith("http")
    }

    /**
     * Push im Hintergrundthread. [pending] ist das Ergebnis von goAsync() eines
     * BroadcastReceivers - damit bleibt der Prozess bis zum Ende am Leben.
     */
    fun pushAsync(
        ctx: Context,
        pending: BroadcastReceiver.PendingResult? = null
    ) {
        val app = ctx.applicationContext
        if (!configured(app) || busy) {
            runCatching { pending?.finish() }
            return
        }
        busy = true
        Thread {
            try {
                val ok = send(app)
                if (ok) {
                    AlarmScheduler.cancelPushRetry(app)
                } else {
                    AlarmScheduler.schedulePushRetry(app)
                }
            } catch (_: Exception) {
                runCatching { AlarmScheduler.schedulePushRetry(app) }
            } finally {
                busy = false
                runCatching { pending?.finish() }
            }
        }.apply { isDaemon = true; name = "hawecker-push" }.start()
    }

    private fun send(ctx: Context): Boolean {
        val target = Prefs.webhookUrl(ctx)
        val body = ApiPayload.build(ctx).toString()
        val stamp = SimpleDateFormat("dd.MM. HH:mm:ss", Locale.GERMANY).format(Date())

        var conn: HttpURLConnection? = null
        return try {
            conn = URL(target).openConnection() as HttpURLConnection
            conn.requestMethod = "POST"
            conn.connectTimeout = 15000
            conn.readTimeout = 15000
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            conn.outputStream.use { it.write(body.toByteArray(StandardCharsets.UTF_8)) }
            val code = conn.responseCode
            if (code in 200..299) {
                Prefs.setLastPushResult(ctx, "$stamp OK ($code)")
                true
            } else {
                val msg = runCatching {
                    conn.errorStream?.bufferedReader()?.use(BufferedReader::readText)
                }.getOrNull()?.take(60).orEmpty()
                Prefs.setLastPushResult(ctx, "$stamp Fehler $code $msg".trim())
                false
            }
        } catch (e: Exception) {
            Prefs.setLastPushResult(ctx, "$stamp ${e.message?.take(70) ?: "Netzwerkfehler"}")
            false
        } finally {
            runCatching { conn?.disconnect() }
        }
    }
}

package de.starnberg.hawecker

import android.content.Intent
import android.webkit.JavascriptInterface
import android.widget.Toast
import org.json.JSONObject

/**
 * Bruecke zwischen der Oberflaeche (WebView, assets/ui/app.js) und dem
 * Backend. Alle Methoden laufen auf dem JS-Thread der WebView; was die
 * Oberflaeche beruehrt, geht ueber runOnUiThread.
 */
class UiBridge(private val act: MainActivity) {

    private val ctx get() = act.applicationContext

    @JavascriptInterface
    fun zustand(): String = UiState.json(ctx)

    @JavascriptInterface
    fun speichern(json: String, pushen: Boolean): String =
        runCatching { UiState.apply(ctx, json, pushen) }.getOrElse { UiState.json(ctx) }

    /** Nur die Zugangsdaten sichern, ohne Planung und ohne Push (bei jeder Eingabe). */
    @JavascriptInterface
    fun apiSpeichern(url: String, id: String, an: Boolean) {
        Prefs.setHaAdresse(ctx, url)
        Prefs.setWebhookId(ctx, id)
        Prefs.setPushEnabled(ctx, an)
    }

    @JavascriptInterface
    fun apiTesten() {
        Thread {
            val (ok, text) = HaPush.testen(ctx)
            act.js("window.apiErgebnis&&window.apiErgebnis($ok, ${JSONObject.quote(text)})")
        }.apply { isDaemon = true }.start()
    }

    @JavascriptInterface
    fun tonVorschau(name: String) = act.runOnUiThread { RingPlayer.preview(ctx, name) }

    @JavascriptInterface
    fun tonStopp() = act.runOnUiThread { RingPlayer.stopPreview() }

    @JavascriptInterface
    fun vibrationVorschau(vibe: String) {
        if (Prefs.vib(ctx)) Haptik.muster(ctx, vibe)
    }

    @JavascriptInterface
    fun haptik(ms: Int) {
        if (Prefs.vib(ctx)) Haptik.kurz(ctx, ms)
    }

    /** Radschritt im Zeitrad: sehr kurz und leise, zusaetzlich zum Klickton. */
    @JavascriptInterface
    fun radTick() {
        if (Prefs.vib(ctx)) Haptik.tick(ctx)
    }

    /** „Weckruf testen" aus der Bearbeiten-Seite: Vollbild mit dem Entwurf. */
    @JavascriptInterface
    fun weckrufVorschau(json: String) {
        act.startActivity(
            Intent(act, RingActivity::class.java)
                .putExtra(RingActivity.EXTRA_VORSCHAU, json)
        )
    }

    /** Echter Testweckruf ueber den AlarmManager, zum Pruefen bei gesperrtem Bildschirm. */
    @JavascriptInterface
    fun testWeckruf(sekunden: Int) {
        AlarmScheduler.scheduleTest(ctx, sekunden.coerceIn(5, 120))
        act.runOnUiThread {
            Toast.makeText(ctx, "Testweckruf in $sekunden Sekunden – Bildschirm ausschalten", Toast.LENGTH_LONG).show()
        }
    }

    @JavascriptInterface
    fun berechtigung(name: String) = act.runOnUiThread { act.berechtigung(name) }
}

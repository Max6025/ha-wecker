package de.starnberg.hawecker

import android.annotation.SuppressLint
import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import org.json.JSONObject

/**
 * Vollbild-Weckruf (assets/ui/ring.html): atmender Lichtkegel in der
 * Kategoriefarbe, Schieberegler zum Stoppen, Schlummern. Ton und Vibration
 * macht RingPlayer. Mit EXTRA_VORSCHAU zeigt die Seite einen Entwurf aus der
 * Bearbeiten-Seite („Weckruf testen") und beendet nur sich selbst.
 */
class RingActivity : Activity() {

    companion object {
        const val ACTION_CLOSE = "de.starnberg.hawecker.CLOSE_RING"
        const val EXTRA_VORSCHAU = "vorschau"
    }

    private lateinit var web: WebView
    private var alarmId = -1
    private var alarm: Alarm? = null
    private var kategorie: Category? = null
    private var vorschau = false
    private var insetsJs = ""

    private val closeReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            finishAndRemoveTask()
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            (getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager)
                .requestDismissKeyguard(this, null)
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            )
        }
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        if (Build.VERSION.SDK_INT >= 28) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT

        // Welcher Wecker? Entwurf aus der Bearbeiten-Seite oder echter Weckruf.
        val entwurf = intent.getStringExtra(EXTRA_VORSCHAU)
        if (entwurf != null) {
            vorschau = true
            runCatching { JSONObject(entwurf) }.getOrNull()?.let { j ->
                val k = j.optJSONObject("kat")
                kategorie = if (k != null) Category.fromJson(k) else CategoryStore.get(this, j.optString("cat"))
                alarm = Alarm(
                    id = AlarmReceiver.TEST_ID,
                    label = j.optString("label", ""),
                    hour = j.optInt("h", 6),
                    minute = j.optInt("m", 30),
                    catId = kategorie?.id ?: "k1",
                    tone = j.optString("tone", Prefs.defTone(this)),
                    vibe = j.optString("vibe", "Herzschlag"),
                    snoozeMinutes = j.optInt("snooze", 9)
                )
            }
            alarm?.let { RingPlayer.start(this, it) }
        } else {
            alarmId = intent.getIntExtra(AlarmReceiver.EXTRA_ID, RingState.ringingId)
            alarm = AlarmReceiver.resolveAlarm(this, alarmId)
            alarm?.let {
                RingState.ringingId = it.id
                kategorie = CategoryStore.get(this, it.catId)
                if (!RingPlayer.isPlaying()) RingPlayer.start(this, it)
            }
        }

        web = WebView(this)
        web.setBackgroundColor(Color.parseColor("#05070F"))
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.isVerticalScrollBarEnabled = false
        with(web.settings) {
            javaScriptEnabled = true
            allowFileAccess = true
            textZoom = 100
        }
        web.isLongClickable = false
        web.setOnLongClickListener { true }
        web.addJavascriptInterface(RingBridge(), "Android")
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                if (insetsJs.isNotEmpty()) js(insetsJs)
            }
        }
        setContentView(web)

        val ctrl = WindowInsetsControllerCompat(window, web)
        ctrl.hide(WindowInsetsCompat.Type.systemBars())
        ctrl.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        ViewCompat.setOnApplyWindowInsetsListener(web) { _, ins ->
            val bars = ins.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            val d = resources.displayMetrics.density
            fun px(p: Int) = (p / d).toInt()
            insetsJs = "window.setInsets&&window.setInsets(${px(bars.top)},${px(bars.right)},${px(bars.bottom)},${px(bars.left)})"
            js(insetsJs)
            WindowInsetsCompat.CONSUMED
        }
        web.loadUrl("file:///android_asset/ui/ring.html")

        val filter = IntentFilter(ACTION_CLOSE)
        if (Build.VERSION.SDK_INT >= 33) {
            registerReceiver(closeReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
        } else {
            @Suppress("UnspecifiedRegisterReceiverFlag")
            registerReceiver(closeReceiver, filter)
        }
    }

    private fun js(code: String) {
        runOnUiThread { runCatching { web.evaluateJavascript(code, null) } }
    }

    /** Daten fuer die Seite: Uhrzeit, Bezeichnung, Kategorie, Schlummerdauer. */
    private fun weckrufJson(): String {
        val a = alarm
        val k = kategorie
        val o = JSONObject()
        o.put("h", a?.hour ?: 0)
        o.put("m", a?.minute ?: 0)
        o.put("label", a?.label ?: "Wecker")
        o.put("snooze", a?.snoozeMinutes ?: 0)
        o.put("vorschau", vorschau)
        val kat = JSONObject()
        kat.put("n", k?.name ?: "")
        kat.put("bild", k?.bild ?: "wecker")
        kat.put("c", k?.farbe ?: "#FF9A4D")
        o.put("cat", kat)
        return o.toString()
    }

    private fun schlummern() {
        if (vorschau) {
            RingPlayer.stop()
            finishAndRemoveTask()
        } else {
            act(AlarmReceiver.ACTION_SNOOZE)
        }
    }

    private fun stoppen() {
        if (vorschau) {
            RingPlayer.stop()
            finishAndRemoveTask()
        } else {
            act(AlarmReceiver.ACTION_DISMISS)
        }
    }

    private fun act(action: String) {
        sendBroadcast(
            Intent(this, AlarmReceiver::class.java)
                .setAction(action)
                .putExtra(AlarmReceiver.EXTRA_ID, alarmId)
        )
        RingPlayer.stop()
        finishAndRemoveTask()
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        // Lautstaerketasten schlummern, Zurueck macht nichts
        return when (keyCode) {
            KeyEvent.KEYCODE_VOLUME_UP, KeyEvent.KEYCODE_VOLUME_DOWN -> {
                if ((alarm?.snoozeMinutes ?: 0) > 0) schlummern() else stoppen(); true
            }
            KeyEvent.KEYCODE_BACK -> true
            else -> super.onKeyDown(keyCode, event)
        }
    }

    @Deprecated("Zurueck-Taste bewusst blockiert")
    override fun onBackPressed() {
        if (vorschau) stoppen()
    }

    override fun onDestroy() {
        super.onDestroy()
        if (vorschau) RingPlayer.stop()
        runCatching { unregisterReceiver(closeReceiver) }
        runCatching { web.destroy() }
    }

    inner class RingBridge {
        @JavascriptInterface
        fun weckruf(): String = weckrufJson()

        @JavascriptInterface
        fun schlummern() = runOnUiThread { this@RingActivity.schlummern() }

        @JavascriptInterface
        fun stoppen() = runOnUiThread { this@RingActivity.stoppen() }
    }
}

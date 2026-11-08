package de.starnberg.hawecker

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.core.graphics.Insets
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

/**
 * Traegt die Oberflaeche (assets/ui/app.html) in einer WebView und reicht
 * Systemdinge durch: Rand der Systemleisten, Zurueck-Taste, Freigaben.
 * Alles Fachliche steckt in UiBridge/UiState.
 */
class MainActivity : Activity() {

    private lateinit var web: WebView
    private var lastResumePush = 0L
    private var insetsJs = ""
    private val storeListener: () -> Unit = { js("window.aktualisieren&&window.aktualisieren()") }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notifications.ensureChannels(this)

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 11)
        }

        // Seite laeuft bis unter die Systemleisten; die Raender bekommt sie als CSS-Variablen
        WindowCompat.setDecorFitsSystemWindows(window, false)
        if (Build.VERSION.SDK_INT >= 28) {
            window.attributes.layoutInDisplayCutoutMode =
                WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
        }
        window.statusBarColor = Color.TRANSPARENT
        window.navigationBarColor = Color.TRANSPARENT

        web = WebView(this)
        web.setBackgroundColor(Color.TRANSPARENT)
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.isVerticalScrollBarEnabled = false
        web.isHorizontalScrollBarEnabled = false
        with(web.settings) {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            mediaPlaybackRequiresUserGesture = false
            // Masse sind in CSS-px festgelegt; Systemschriftgroesse soll nichts verschieben
            textZoom = 100
        }
        web.addJavascriptInterface(UiBridge(this), "Android")
        // langes Druecken gehoert der Seite (Bearbeiten), nicht der Textauswahl
        web.isLongClickable = false
        web.setOnLongClickListener { true }
        web.isHapticFeedbackEnabled = false
        web.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(m: ConsoleMessage): Boolean {
                Log.i("HaWeckerWeb", "${m.message()} (${m.sourceId()}:${m.lineNumber()})")
                return true
            }
        }
        web.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                if (insetsJs.isNotEmpty()) js(insetsJs)
            }
        }
        setContentView(web)

        val ctrl = WindowInsetsControllerCompat(window, web)
        ctrl.isAppearanceLightStatusBars = false
        ctrl.isAppearanceLightNavigationBars = false

        ViewCompat.setOnApplyWindowInsetsListener(web) { v, ins ->
            val bars: Insets = ins.getInsets(
                WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout()
            )
            val ime = ins.getInsets(WindowInsetsCompat.Type.ime()).bottom
            // Tastatur: WebView von unten verkuerzen, sonst Rand als Variable
            v.setPadding(0, 0, 0, if (ime > bars.bottom) ime else 0)
            val d = resources.displayMetrics.density
            fun px(p: Int) = (p / d).toInt()
            insetsJs = "window.setInsets&&window.setInsets(${px(bars.top)},${px(bars.right)}," +
                "${if (ime > bars.bottom) 0 else px(bars.bottom)},${px(bars.left)})"
            js(insetsJs)
            WindowInsetsCompat.CONSUMED
        }

        web.loadUrl("file:///android_asset/ui/app.html")

        AlarmScheduler.scheduleAll(this)
        AlarmStore.addListener(storeListener)
    }

    override fun onResume() {
        super.onResume()
        js("window.aktualisieren&&window.aktualisieren()")
        // Beim Oeffnen der App den Stand an Home Assistant melden, damit die
        // Entitaeten sofort gefuellt sind. Gedrosselt, weil nach dem Speichern
        // eines Weckers ohnehin schon gesendet wurde.
        val now = System.currentTimeMillis()
        if (now - lastResumePush > 60_000L && HaPush.configured(this)) {
            lastResumePush = now
            HaPush.pushAsync(this)
        }
    }

    override fun onPause() {
        super.onPause()
        RingPlayer.stopPreview(this)
    }

    override fun onDestroy() {
        super.onDestroy()
        AlarmStore.removeListener(storeListener)
        runCatching { web.destroy() }
    }

    fun js(code: String) {
        runOnUiThread { runCatching { web.evaluateJavascript(code, null) } }
    }

    @Deprecated("Zurueck geht zuerst an die Seite (Systemseite schliessen), dann an Android")
    override fun onBackPressed() {
        web.evaluateJavascript("window.zurueck?window.zurueck():false") { result ->
            if (result != "true") finish()
        }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        js("window.aktualisieren&&window.aktualisieren()")
    }

    // ------------------------------------------------------------------
    //  Freigaben (aus der Seite angestossen)
    // ------------------------------------------------------------------

    fun berechtigung(name: String) {
        when (name) {
            "notify" -> {
                if (Build.VERSION.SDK_INT >= 33 &&
                    checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
                ) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 11)
                else openAppNotificationSettings()
            }
            "fullscreen" -> requestFullScreen()
            "exact" -> requestExactAlarm()
            "battery" -> requestBattery()
            "promote" -> openAppNotificationSettings()
            "overlay" -> requestOverlay()
        }
    }

    private fun requestFullScreen() {
        if (Build.VERSION.SDK_INT >= 34) {
            val ok = runCatching {
                startActivity(
                    Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT)
                        .setData(Uri.parse("package:$packageName"))
                )
            }.isSuccess
            if (!ok) openAppNotificationSettings()
        } else {
            openAppNotificationSettings()
        }
    }

    /** „Ueber anderen Apps anzeigen": Weckruf-Seite auch bei entsperrtem Handy. */
    private fun requestOverlay() {
        if (Settings.canDrawOverlays(this)) {
            Toast.makeText(this, "Bereits erlaubt", Toast.LENGTH_SHORT).show()
            return
        }
        val ok = runCatching {
            startActivity(
                Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)
                    .setData(Uri.parse("package:$packageName"))
            )
        }.isSuccess
        if (!ok) runCatching { startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION)) }
    }

    private fun openAppNotificationSettings() {
        runCatching {
            startActivity(
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
            )
        }
    }

    private fun requestBattery() {
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (pm.isIgnoringBatteryOptimizations(packageName)) {
            Toast.makeText(this, "Bereits ausgenommen", Toast.LENGTH_SHORT).show()
            return
        }
        runCatching {
            @Suppress("BatteryLife")
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                    .setData(Uri.parse("package:$packageName"))
            )
        }
    }

    private fun requestExactAlarm() {
        if (Build.VERSION.SDK_INT >= 31) {
            runCatching {
                startActivity(
                    Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM)
                        .setData(Uri.parse("package:$packageName"))
                )
            }
        } else {
            Toast.makeText(this, "Nicht noetig auf dieser Android-Version", Toast.LENGTH_SHORT).show()
        }
    }
}

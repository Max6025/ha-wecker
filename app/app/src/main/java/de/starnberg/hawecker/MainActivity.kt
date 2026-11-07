package de.starnberg.hawecker

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.CompoundButton
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

class MainActivity : Activity() {

    private val handler = Handler(Looper.getMainLooper())
    private var ticker: Runnable? = null
    private val storeListener: () -> Unit = { runOnUiThread { render() } }
    /** Letzter Push beim Oeffnen der App - hoechstens einmal pro Minute. */
    private var lastResumePush = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        Notifications.ensureChannels(this)

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 11)
        }

        findViewById<View>(R.id.btnAdd).setOnClickListener {
            startActivity(Intent(this, EditAlarmActivity::class.java))
        }
        findViewById<View>(R.id.btnSettings).setOnClickListener { showSettings() }
        findViewById<View>(R.id.pushStrip).setOnClickListener { showSettings() }

        AlarmScheduler.scheduleAll(this)
        AlarmStore.addListener(storeListener)
    }

    override fun onResume() {
        super.onResume()
        render()
        // Beim Oeffnen der App den Stand an Home Assistant melden, damit die
        // Entitaeten sofort gefuellt sind. Gedrosselt, weil nach dem Speichern
        // eines Weckers ohnehin schon gesendet wurde.
        val now = System.currentTimeMillis()
        if (now - lastResumePush > 60_000L && HaPush.configured(this)) {
            lastResumePush = now
            HaPush.pushAsync(this)
        }
        val r = object : Runnable {
            override fun run() {
                render()
                handler.postDelayed(this, 1000)
            }
        }
        ticker = r
        handler.postDelayed(r, 1000)
    }

    override fun onPause() {
        super.onPause()
        ticker?.let { handler.removeCallbacks(it) }
    }

    override fun onDestroy() {
        super.onDestroy()
        AlarmStore.removeListener(storeListener)
    }

    private fun render() {
        val alarms = AlarmStore.all(this)
        val next = AlarmScheduler.nextAlarm(this)
        val now = System.currentTimeMillis()

        findViewById<TextView>(R.id.nextTime).text = next?.first?.timeString() ?: "--:--"
        findViewById<TextView>(R.id.nextMeta).text = if (next == null) {
            "kein aktiver Wecker"
        } else {
            val name = if (next.first.label.isBlank()) next.first.daysLabel() else
                "${next.first.label} - ${next.first.daysLabel()}"
            "in ${ApiPayload.humanIn(next.second - now)}   -   $name"
        }

        findViewById<TextView>(R.id.listHeader).text =
            "Wecker  -  ${alarms.count { it.enabled }} von ${alarms.size} aktiv"

        val pushOn = HaPush.configured(this)
        findViewById<View>(R.id.pushDot).setBackgroundColor(
            getColor(if (pushOn) R.color.ok else R.color.text_off)
        )
        findViewById<TextView>(R.id.pushText).text =
            if (pushOn) "Home Assistant - ${Prefs.lastPushResult(this)}"
            else "Keine Anbindung an Home Assistant - hier einrichten"

        val warn = findViewById<TextView>(R.id.warnLine)
        val issue = firstIssue()
        if (issue == null) {
            warn.visibility = View.GONE
        } else {
            warn.visibility = View.VISIBLE
            warn.text = issue.first
            warn.setOnClickListener { issue.second() }
        }

        val list = findViewById<LinearLayout>(R.id.alarmList)
        list.removeAllViews()
        val inflater = LayoutInflater.from(this)
        if (alarms.isEmpty()) {
            val tv = TextView(this)
            tv.text = "Noch kein Wecker angelegt."
            tv.setTextColor(getColor(R.color.text_off))
            tv.textSize = 14f
            tv.setPadding(0, 24, 0, 0)
            list.addView(tv)
            return
        }
        for (a in alarms) {
            val row = inflater.inflate(R.layout.item_alarm, list as ViewGroup, false)
            val time = row.findViewById<TextView>(R.id.rowTime)
            val meta = row.findViewById<TextView>(R.id.rowMeta)
            val bar = row.findViewById<View>(R.id.rowBar)
            val sw = row.findViewById<Switch>(R.id.rowSwitch)
            row.findViewById<TextView>(R.id.rowId).text = "#${a.id}"

            time.text = a.timeString()
            time.setTextColor(getColor(if (a.enabled) R.color.text else R.color.text_off))
            bar.setBackgroundColor(getColor(if (a.enabled) R.color.accent else R.color.line))

            val parts = ArrayList<String>()
            parts.add(a.daysLabel())
            if (a.label.isNotBlank()) parts.add(a.label)
            if (a.skipNext && a.enabled) parts.add("naechster uebersprungen")
            if (a.snoozedUntil > now) parts.add("schlummert")
            if (a.enabled) {
                val nt = a.nextTriggerAt(now)
                if (nt > 0) parts.add("in ${ApiPayload.humanIn(nt - now)}")
            }
            meta.text = parts.joinToString("  -  ")
            meta.setTextColor(getColor(if (a.enabled) R.color.text_dim else R.color.text_off))

            sw.setOnCheckedChangeListener(null)
            sw.isChecked = a.enabled
            sw.setOnCheckedChangeListener { _: CompoundButton, checked: Boolean ->
                a.enabled = checked
                if (!checked) a.snoozedUntil = 0L
                AlarmStore.save(this, a)
                HaPush.pushAsync(this)
            }

            row.setOnClickListener {
                startActivity(
                    Intent(this, EditAlarmActivity::class.java)
                        .putExtra(EditAlarmActivity.EXTRA_ID, a.id)
                )
            }
            list.addView(row)
        }
    }

    private fun showSettings() {
        val view = layoutInflater.inflate(R.layout.dialog_settings, null)
        val info = view.findViewById<TextView>(R.id.cfgInfo)

        val prewarn = view.findViewById<EditText>(R.id.cfgPrewarn)
        val haUrl = view.findViewById<EditText>(R.id.cfgHaUrl)
        val pushEnabled = view.findViewById<Switch>(R.id.cfgPushEnabled)
        val pushStatus = view.findViewById<TextView>(R.id.cfgPushStatus)

        prewarn.setText(Prefs.prewarnMinutes(this).toString())
        haUrl.setText(Prefs.webhookUrl(this))
        pushEnabled.isChecked = Prefs.pushEnabled(this)
        pushStatus.text = "Letzter Push: ${Prefs.lastPushResult(this)}"
        info.text = "Vollbild: ${if (Notifications.canUseFullScreenIntent(this)) "erlaubt" else "GESPERRT"}\n" +
            "Exakte Alarme: ${if (AlarmScheduler.canScheduleExact(this)) "erlaubt" else "GESPERRT"}"

        view.findViewById<View>(R.id.cfgPushNow).setOnClickListener {
            // Eingaben zuerst sichern, sonst testet man die alten Werte
            Prefs.setWebhookUrl(this, haUrl.text.toString())
            Prefs.setPushEnabled(this, pushEnabled.isChecked)
            if (!HaPush.configured(this)) {
                Toast.makeText(this, "Webhook-Adresse und Schalter pruefen", Toast.LENGTH_LONG).show()
            } else {
                HaPush.pushAsync(this)
                Toast.makeText(this, "Wird gesendet...", Toast.LENGTH_SHORT).show()
                handler.postDelayed({
                    pushStatus.text = "Letzter Push: ${Prefs.lastPushResult(this)}"
                }, 2500)
            }
        }
        view.findViewById<View>(R.id.cfgFullscreen).setOnClickListener { requestFullScreen() }
        view.findViewById<View>(R.id.cfgBattery).setOnClickListener { requestBattery() }
        view.findViewById<View>(R.id.cfgExact).setOnClickListener { requestExactAlarm() }
        view.findViewById<View>(R.id.cfgTest).setOnClickListener {
            AlarmScheduler.scheduleTest(this, 15)
            Toast.makeText(this, "Testweckruf in 15 Sekunden - Bildschirm ausschalten", Toast.LENGTH_LONG).show()
        }

        AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog)
            .setView(view)
            .setPositiveButton("Speichern") { _, _ ->
                Prefs.setPrewarnMinutes(
                    this, prewarn.text.toString().toIntOrNull()?.coerceIn(0, 240) ?: 0
                )
                Prefs.setWebhookUrl(this, haUrl.text.toString())
                Prefs.setPushEnabled(this, pushEnabled.isChecked)
                AlarmScheduler.scheduleAll(this)
                HaPush.pushAsync(this)
                handler.postDelayed({ render() }, 600)
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    /** Wichtigste fehlende Freigabe, Text plus Aktion beim Antippen. */
    private fun firstIssue(): Pair<String, () -> Unit>? {
        if (!Notifications.canUseFullScreenIntent(this)) {
            return "Vollbild-Weckruf ist gesperrt. Ohne diese Freigabe kommt bei ausgeschaltetem Bildschirm nur eine Benachrichtigung. Hier tippen und erlauben." to { requestFullScreen() }
        }
        if (!AlarmScheduler.canScheduleExact(this)) {
            return "Exakte Alarme sind nicht erlaubt, der Wecker klingelt sonst ungenau. Hier tippen und erlauben." to { requestExactAlarm() }
        }
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            return "Akku-Optimierung ist aktiv. Android kann den Weckruf dann verzoegern. Hier tippen und ausnehmen." to { requestBattery() }
        }
        return null
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

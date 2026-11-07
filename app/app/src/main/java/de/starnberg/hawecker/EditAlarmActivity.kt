package de.starnberg.hawecker

import android.app.Activity
import android.content.Intent
import android.media.RingtoneManager
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import android.widget.TimePicker
import android.widget.Toast

class EditAlarmActivity : Activity() {

    companion object {
        const val EXTRA_ID = "edit_alarm_id"
        private const val REQ_SOUND = 77
    }

    private lateinit var alarm: Alarm
    private var isNew = false
    private val dayViews = ArrayList<TextView>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_edit)

        val id = intent.getIntExtra(EXTRA_ID, -1)
        val existing = if (id >= 0) AlarmStore.get(this, id) else null
        isNew = existing == null
        alarm = existing ?: Alarm(id = AlarmStore.nextId(this), days = Alarm.WORKDAYS)

        findViewById<TextView>(R.id.editTitle).text =
            if (isNew) "NEUER WECKER" else "WECKER #${alarm.id}"

        val picker = findViewById<TimePicker>(R.id.timePicker)
        picker.setIs24HourView(true)
        picker.hour = alarm.hour
        picker.minute = alarm.minute

        buildDayChips()

        findViewById<View>(R.id.presetWork).setOnClickListener { setDays(Alarm.WORKDAYS) }
        findViewById<View>(R.id.presetAll).setOnClickListener { setDays(Alarm.ALL_DAYS) }
        findViewById<View>(R.id.presetOnce).setOnClickListener { setDays(0) }

        findViewById<EditText>(R.id.labelInput).setText(alarm.label)
        findViewById<EditText>(R.id.snoozeInput).setText(alarm.snoozeMinutes.toString())
        findViewById<Switch>(R.id.vibrateSwitch).isChecked = alarm.vibrate
        findViewById<Switch>(R.id.skipSwitch).isChecked = alarm.skipNext

        updateSoundRow()
        findViewById<View>(R.id.soundRow).setOnClickListener { pickSound() }

        val del = findViewById<TextView>(R.id.btnDelete)
        del.visibility = if (isNew) View.GONE else View.VISIBLE
        del.setOnClickListener {
            AlarmStore.delete(this, alarm.id)
            HaPush.pushAsync(this)
            Toast.makeText(this, "Wecker geloescht", Toast.LENGTH_SHORT).show()
            finish()
        }

        findViewById<View>(R.id.btnCancel).setOnClickListener { finish() }
        findViewById<View>(R.id.btnSave).setOnClickListener { save(picker) }
    }

    private fun buildDayChips() {
        val row = findViewById<LinearLayout>(R.id.dayRow)
        row.removeAllViews()
        dayViews.clear()
        for (i in 0..6) {
            val tv = TextView(this)
            tv.text = Alarm.DAY_SHORT[i]
            tv.gravity = Gravity.CENTER
            tv.textSize = 12f
            tv.setBackgroundResource(R.drawable.chip_day)
            val lp = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            if (i < 6) lp.marginEnd = dp(6)
            tv.layoutParams = lp
            tv.setPadding(0, dp(12), 0, dp(12))
            tv.setOnClickListener {
                alarm.days = alarm.days xor (1 shl i)
                refreshChips()
            }
            dayViews.add(tv)
            row.addView(tv)
        }
        refreshChips()
    }

    private fun setDays(mask: Int) {
        alarm.days = mask
        refreshChips()
    }

    private fun refreshChips() {
        for (i in 0..6) {
            val on = ((alarm.days shr i) and 1) == 1
            dayViews[i].isSelected = on
            dayViews[i].setTextColor(getColor(if (on) R.color.bg else R.color.text_dim))
        }
    }

    private fun dp(v: Int): Int = (v * resources.displayMetrics.density).toInt()

    private fun updateSoundRow() {
        val row = findViewById<TextView>(R.id.soundRow)
        val uriStr = alarm.soundUri
        row.text = if (uriStr == null) {
            "Standard-Alarmton"
        } else {
            val title = runCatching {
                RingtoneManager.getRingtone(this, Uri.parse(uriStr))?.getTitle(this)
            }.getOrNull()
            title ?: "Eigener Ton"
        }
    }

    private fun pickSound() {
        val i = Intent(RingtoneManager.ACTION_RINGTONE_PICKER).apply {
            putExtra(RingtoneManager.EXTRA_RINGTONE_TYPE, RingtoneManager.TYPE_ALARM)
            putExtra(RingtoneManager.EXTRA_RINGTONE_TITLE, "Weckton waehlen")
            putExtra(RingtoneManager.EXTRA_RINGTONE_SHOW_DEFAULT, true)
            putExtra(RingtoneManager.EXTRA_RINGTONE_SHOW_SILENT, false)
            putExtra(
                RingtoneManager.EXTRA_RINGTONE_EXISTING_URI,
                alarm.soundUri?.let { Uri.parse(it) }
            )
        }
        runCatching { startActivityForResult(i, REQ_SOUND) }
    }

    @Suppress("DEPRECATION")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_SOUND && resultCode == RESULT_OK) {
            val uri: Uri? = data?.getParcelableExtra(RingtoneManager.EXTRA_RINGTONE_PICKED_URI)
            alarm.soundUri = uri?.toString()
            updateSoundRow()
        }
    }

    private fun save(picker: TimePicker) {
        alarm.hour = picker.hour
        alarm.minute = picker.minute
        alarm.label = findViewById<EditText>(R.id.labelInput).text.toString().trim()
        alarm.snoozeMinutes = findViewById<EditText>(R.id.snoozeInput).text.toString()
            .toIntOrNull()?.coerceIn(1, 120) ?: 9
        alarm.vibrate = findViewById<Switch>(R.id.vibrateSwitch).isChecked
        alarm.skipNext = findViewById<Switch>(R.id.skipSwitch).isChecked
        if (isNew) alarm.enabled = true
        alarm.snoozedUntil = 0L

        AlarmStore.save(this, alarm)
        HaPush.pushAsync(this)

        val next = alarm.nextTriggerAt()
        if (next > 0) {
            Toast.makeText(
                this,
                "Weckt in ${ApiPayload.humanIn(next - System.currentTimeMillis())}",
                Toast.LENGTH_SHORT
            ).show()
        }
        finish()
    }
}

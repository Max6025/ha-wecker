package de.starnberg.hawecker

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle

/**
 * Kleiner Dialog, der beim Antippen der Vorwarnung erscheint - auch ueber dem
 * Sperrbildschirm: Wecker fuer heute aussetzen, ganz ausschalten oder lassen.
 */
class PrewarnActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setShowWhenLocked(true)
        setTurnScreenOn(true)

        val id = intent.getIntExtra(AlarmReceiver.EXTRA_ID, -1)
        val alarm = if (id >= 0) AlarmStore.get(this, id) else null
        if (alarm == null) {
            finish()
            return
        }

        val title = if (alarm.label.isBlank()) "Wecker ${alarm.timeString()}"
        else "${alarm.label} - ${alarm.timeString()}"
        val items = if (alarm.isRepeating())
            arrayOf("Nur heute aus", "Wecker ausschalten", "Klingeln lassen")
        else
            arrayOf("Wecker ausschalten", "Klingeln lassen")

        AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle(title)
            .setMessage("Klingelt in ${ApiPayload.humanIn(alarm.nextTriggerAt() - System.currentTimeMillis())}")
            .setItems(items) { _, which ->
                val action = when {
                    alarm.isRepeating() && which == 0 -> AlarmReceiver.ACTION_SKIP_TODAY
                    (alarm.isRepeating() && which == 1) || (!alarm.isRepeating() && which == 0) ->
                        AlarmReceiver.ACTION_DISABLE
                    else -> null
                }
                if (action != null) {
                    sendBroadcast(
                        Intent(this, AlarmReceiver::class.java)
                            .setAction(action)
                            .putExtra(AlarmReceiver.EXTRA_ID, alarm.id)
                    )
                }
                finish()
            }
            .setOnCancelListener { finish() }
            .show()
    }
}

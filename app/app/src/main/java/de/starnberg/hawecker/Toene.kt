package de.starnberg.hawecker

import android.content.Context
import android.media.RingtoneManager
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject

/**
 * Wecktoene aus dem Handy: erst die Alarmtoene, dann die Klingeltoene des
 * Systems. Gespeichert wird die URI; leer heisst „Standard-Alarmton des Handys".
 * Die Liste zeigt unsere eigene Auswahlseite, nicht der Systemdialog.
 */
object Toene {

    const val STANDARD = ""

    data class Ton(val name: String, val uri: String)

    @Volatile
    private var cache: List<Ton>? = null

    fun liste(ctx: Context): List<Ton> {
        cache?.let { return it }
        val out = ArrayList<Ton>()
        val gesehen = HashSet<String>()
        for (typ in intArrayOf(RingtoneManager.TYPE_ALARM, RingtoneManager.TYPE_RINGTONE)) {
            runCatching {
                val rm = RingtoneManager(ctx.applicationContext)
                rm.setType(typ)
                val c = rm.cursor
                while (c.moveToNext()) {
                    val uri = rm.getRingtoneUri(c.position)?.toString() ?: continue
                    val name = c.getString(RingtoneManager.TITLE_COLUMN_INDEX) ?: continue
                    if (gesehen.add(uri)) out.add(Ton(name, uri))
                }
            }
        }
        cache = out
        return out
    }

    /** Anzeigename zu einer gespeicherten URI; alte Namen (bis 2.0) und leer = Standard. */
    fun name(ctx: Context, uri: String): String {
        if (uri.isEmpty() || !uri.contains("://")) return "Standard"
        liste(ctx).firstOrNull { it.uri == uri }?.let { return it.name }
        return runCatching {
            RingtoneManager.getRingtone(ctx, Uri.parse(uri))?.getTitle(ctx)
        }.getOrNull() ?: "Eigener Ton"
    }

    /** Abspielbare URI: gespeicherte, sonst Standard-Alarmton, sonst Klingelton. */
    fun uri(ctx: Context, gespeichert: String): Uri? {
        if (gespeichert.isNotEmpty() && gespeichert.contains("://")) {
            runCatching { Uri.parse(gespeichert) }.getOrNull()?.let { return it }
        }
        return RingtoneManager.getActualDefaultRingtoneUri(ctx, RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM)
            ?: RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
    }

    /** Fuer die Oberflaeche: [{n, v}], Standard zuerst. */
    fun json(ctx: Context): String {
        val arr = JSONArray()
        arr.put(JSONObject().put("n", "Standard (Alarmton des Handys)").put("v", STANDARD))
        liste(ctx).forEach { arr.put(JSONObject().put("n", it.name).put("v", it.uri)) }
        return arr.toString()
    }
}

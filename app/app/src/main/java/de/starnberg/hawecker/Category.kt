package de.starnberg.hawecker

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Kategorie eines Weckers: Name, Bild aus der Bildbibliothek (assets/ui/bilder.js)
 * und die zum Bild gehoerende Farbe. Die Farbe ist nicht frei waehlbar, sie
 * kommt immer vom Bild; die Oberflaeche setzt sie, hier wird sie nur gespeichert.
 */
data class Category(
    var id: String,
    var name: String,
    var bild: String,
    var farbe: String
) {
    fun toJson(): JSONObject = JSONObject()
        .put("id", id).put("n", name).put("bild", bild).put("c", farbe)

    companion object {
        fun fromJson(o: JSONObject): Category = Category(
            id = o.optString("id", ""),
            name = o.optString("n", "").ifEmpty { "Kategorie" },
            bild = o.optString("bild", "sonne").ifEmpty { "sonne" },
            farbe = o.optString("c", "#74B4FF").ifEmpty { "#74B4FF" }
        )
    }
}

/** Persistenz der Kategorien (JSON in SharedPreferences, gleiche Datei wie die Wecker). */
object CategoryStore {

    private const val PREFS = "hawecker"
    private const val KEY_CATS = "cats"
    private const val KEY_SEQ = "cat_seq"

    /** Vorgaben einer frischen Installation; Farben sind die Bildfarben. */
    val DEFAULTS: List<Category> = listOf(
        Category("k1", "Aufstehen", "sonne", "#FFB457"),
        Category("k2", "Arbeit", "werkzeug", "#B8C4D6"),
        Category("k3", "Baustelle", "kegel", "#F2C94C"),
        Category("k4", "Training", "hantel", "#45D6B4"),
        Category("k5", "Abfahrt", "transporter", "#FF8FA3"),
        Category("k6", "Pause", "tasse", "#A98BFF"),
        Category("k7", "Erinnerung", "klemmbrett", "#7FE0A0")
    )

    private val lock = Any()

    private fun prefs(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun all(ctx: Context): List<Category> = synchronized(lock) {
        val raw = prefs(ctx).getString(KEY_CATS, null)
        val list = ArrayList<Category>()
        if (raw != null) {
            runCatching {
                val arr = JSONArray(raw)
                for (i in 0 until arr.length()) {
                    val c = Category.fromJson(arr.getJSONObject(i))
                    if (c.id.isNotEmpty()) list.add(c)
                }
            }
        }
        if (list.isEmpty()) {
            list.addAll(DEFAULTS.map { it.copy() })
            persist(ctx, list)
            prefs(ctx).edit().putInt(KEY_SEQ, DEFAULTS.size + 1).apply()
        }
        list
    }

    fun get(ctx: Context, id: String): Category {
        val list = all(ctx)
        return list.firstOrNull { it.id == id } ?: list.first()
    }

    fun saveAll(ctx: Context, list: List<Category>) = synchronized(lock) {
        persist(ctx, if (list.isEmpty()) DEFAULTS.map { it.copy() } else list)
    }

    fun nextId(ctx: Context): String = synchronized(lock) {
        val p = prefs(ctx)
        var seq = p.getInt(KEY_SEQ, DEFAULTS.size + 1)
        val used = all(ctx).map { it.id }.toSet()
        while (used.contains("k$seq")) seq++
        p.edit().putInt(KEY_SEQ, seq + 1).apply()
        "k$seq"
    }

    private fun persist(ctx: Context, list: List<Category>) {
        val arr = JSONArray()
        list.forEach { arr.put(it.toJson()) }
        prefs(ctx).edit().putString(KEY_CATS, arr.toString()).apply()
    }
}

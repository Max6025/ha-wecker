package de.starnberg.hawecker

import android.content.Context
import org.json.JSONArray

/** Persistenz aller Wecker in SharedPreferences (JSON). Thread-sicher. */
object AlarmStore {

    private const val PREFS = "hawecker"
    private const val KEY_ALARMS = "alarms"
    private const val KEY_NEXT_ID = "next_id"

    private val lock = Any()
    private var cache: MutableList<Alarm>? = null
    private val listeners = ArrayList<() -> Unit>()

    private fun prefs(ctx: Context) =
        ctx.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun all(ctx: Context): List<Alarm> = synchronized(lock) {
        cache?.let { return ArrayList(it) }
        val list = ArrayList<Alarm>()
        val raw = prefs(ctx).getString(KEY_ALARMS, "[]") ?: "[]"
        try {
            val arr = JSONArray(raw)
            for (i in 0 until arr.length()) list.add(Alarm.fromJson(arr.getJSONObject(i)))
        } catch (_: Exception) {
        }
        list.sortWith(compareBy({ it.hour }, { it.minute }, { it.id }))
        cache = list
        return ArrayList(list)
    }

    fun get(ctx: Context, id: Int): Alarm? = all(ctx).firstOrNull { it.id == id }

    fun save(ctx: Context, alarm: Alarm) {
        synchronized(lock) {
            val list = ArrayList(all(ctx))
            val idx = list.indexOfFirst { it.id == alarm.id }
            if (idx >= 0) list[idx] = alarm else list.add(alarm)
            persist(ctx, list)
        }
        notifyChanged(ctx)
    }

    fun delete(ctx: Context, id: Int) {
        synchronized(lock) {
            val list = ArrayList(all(ctx)).filter { it.id != id }.toMutableList()
            persist(ctx, list)
        }
        AlarmScheduler.cancel(ctx, id)
        notifyChanged(ctx)
    }

    fun nextId(ctx: Context): Int = synchronized(lock) {
        val p = prefs(ctx)
        val id = p.getInt(KEY_NEXT_ID, 1)
        p.edit().putInt(KEY_NEXT_ID, id + 1).apply()
        id
    }

    private fun persist(ctx: Context, list: MutableList<Alarm>) {
        list.sortWith(compareBy({ it.hour }, { it.minute }, { it.id }))
        val arr = JSONArray()
        list.forEach { arr.put(it.toJson()) }
        prefs(ctx).edit().putString(KEY_ALARMS, arr.toString()).apply()
        cache = list
    }

    /** Nach jeder Aenderung: neu planen, UI informieren. */
    fun notifyChanged(ctx: Context) {
        AlarmScheduler.scheduleAll(ctx)
        val copy = synchronized(lock) { ArrayList(listeners) }
        copy.forEach { runCatching { it() } }
    }

    fun addListener(l: () -> Unit) = synchronized(lock) { listeners.add(l) }
    fun removeListener(l: () -> Unit) = synchronized(lock) { listeners.remove(l) }
}

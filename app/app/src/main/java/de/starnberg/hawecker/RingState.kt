package de.starnberg.hawecker

/** Laufzeit-Zustand: welcher Wecker klingelt gerade. */
object RingState {
    @Volatile
    var ringingId: Int = -1

    @Volatile
    var ringingSince: Long = 0L

    /** Die Weckruf-Seite (RingActivity) ist gerade zu sehen. */
    @Volatile
    var seiteOffen: Boolean = false

    fun isRinging() = ringingId >= 0
}

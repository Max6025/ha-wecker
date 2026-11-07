package de.starnberg.hawecker

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val ctx = context.applicationContext
        val pending = goAsync()
        AlarmScheduler.scheduleAll(ctx)
        HaPush.pushAsync(ctx, pending)
    }
}

package com.callnotifier.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.util.UUID
import org.json.JSONObject

object Alerts {
    fun send(context: Context, test: Boolean) {
        val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
        try {
            val host = prefs.getString("host", "") ?: ""
            val token = prefs.getString("token", "") ?: ""
            require(host.isNotBlank() && token.isNotBlank()) { "Save the laptop address and token first." }
            val data = JSONObject()
                .put("token", token)
                .put("id", UUID.randomUUID().toString())
                .put("time", System.currentTimeMillis() / 1000)
                .put("type", if (test) "test" else "ringing")
                .toString().toByteArray(Charsets.UTF_8)
            DatagramSocket().use { socket ->
                val packet = DatagramPacket(data, data.size, InetAddress.getByName(host), 45832)
                // Repeat the same event. The laptop ignores duplicates.
                repeat(3) { socket.send(packet) }
            }
            prefs.edit().putString("delivery", "Signal sent. Check the laptop for the alert.").apply()
        } catch (error: Exception) {
            prefs.edit().putString("delivery", "Send failed: ${error.message}").apply()
        }
    }
}

class CallReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return
        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
        val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
        val previous = prefs.getString("state", "")
        val edit = prefs.edit().putString("state", state)
        if (state == TelephonyManager.EXTRA_STATE_RINGING) {
            edit.putLong("lastRing", System.currentTimeMillis())
        }
        edit.apply()
        if (state != TelephonyManager.EXTRA_STATE_RINGING || previous == state) return
        val pending = goAsync()
        Thread {
            try { Alerts.send(context.applicationContext, false) }
            finally { pending.finish() }
        }.start()
    }
}

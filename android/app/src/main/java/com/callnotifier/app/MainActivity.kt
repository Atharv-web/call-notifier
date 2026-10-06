package com.callnotifier.app

import android.app.Activity
import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.JavascriptInterface
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebResourceRequest
import org.json.JSONObject

class MainActivity : Activity() {
    private lateinit var page: WebView
    private val handler = Handler(Looper.getMainLooper())
    private val refresh = object : Runnable {
        override fun run() {
            val prefs = getSharedPreferences("settings", MODE_PRIVATE)
            val data = JSONObject()
                .put("permission", checkSelfPermission(Manifest.permission.READ_PHONE_STATE) == PackageManager.PERMISSION_GRANTED)
                .put("state", prefs.getString("state", "Waiting for a call"))
                .put("lastRing", prefs.getLong("lastRing", 0))
                .put("delivery", prefs.getString("delivery", "No signal sent yet."))
            page.evaluateJavascript("window.updateStatus($data)", null)
            handler.postDelayed(this, 1000)
        }
    }

    inner class PhoneBridge {
        @JavascriptInterface fun permission() {
            runOnUiThread { requestPermissions(arrayOf(Manifest.permission.READ_PHONE_STATE), 1) }
        }
        @JavascriptInterface fun save(host: String, token: String): Boolean {
            if (!Regex("[0-9]{1,3}(\\.[0-9]{1,3}){3}").matches(host) ||
                host.split('.').any { it.toInt() !in 0..255 } || token.length !in 16..128) return false
            getSharedPreferences("settings", MODE_PRIVATE).edit()
                .putString("host", host).putString("token", token).apply()
            return true
        }
        @JavascriptInterface fun config(): String {
            val prefs = getSharedPreferences("settings", MODE_PRIVATE)
            return JSONObject().put("host", prefs.getString("host", ""))
                .put("token", prefs.getString("token", "")).toString()
        }
        @JavascriptInterface fun test() {
            Thread { Alerts.send(applicationContext, true) }.start()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        page = WebView(this).apply {
            // Only the bundled start screen uses JavaScript.
            settings.javaScriptEnabled = true
            settings.allowContentAccess = false
            settings.allowFileAccess = false
            settings.blockNetworkLoads = true
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = true
            }
            addJavascriptInterface(PhoneBridge(), "Phone")
            val html = assets.open("index.html").bufferedReader().use { it.readText() }
            loadDataWithBaseURL("https://app.callnotifier.invalid/", html, "text/html", "UTF-8", null)
        }
        setContentView(page)
    }

    override fun onResume() {
        super.onResume()
        handler.post(refresh)
    }

    override fun onPause() {
        handler.removeCallbacks(refresh)
        super.onPause()
    }

    override fun onDestroy() {
        page.destroy()
        super.onDestroy()
    }
}

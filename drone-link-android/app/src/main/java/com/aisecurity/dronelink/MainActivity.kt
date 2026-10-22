package com.aisecurity.dronelink

import android.Manifest
import android.content.Context
import android.os.Bundle
import android.view.WindowManager
import android.widget.Button
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {
    private var link: LinkClient? = null
    private var pcText = "PC: not paired — tap “Scan pairing code”"
    private var pcOk = false
    private val logLines = ArrayDeque<String>()

    private val scanner = registerForActivityResult(ScanContract()) { result ->
        val text = result.contents ?: return@registerForActivityResult
        try {
            val p = JSONObject(text)
            require(p.optString("app") == "ai-drone-link")
            prefs().edit().putString("host", p.getString("host")).putInt("port", p.getInt("port"))
                .putString("token", p.getString("token")).apply()
            log("Paired with ${p.getString("host")}")
            connect()
        } catch (e: Exception) {
            log("That is not an AI Security pairing code.")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.CAMERA), 1)

        findViewById<Button>(R.id.scanButton).setOnClickListener {
            scanner.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                .setPrompt("Scan the pairing code on the PC: Drone Control page").setBeepEnabled(false))
        }
        findViewById<Button>(R.id.stopButton).setOnClickListener {
            DroneController.centreSticks()
            DroneController.releaseControl("STOP pressed on the phone")
            link?.sendEvent("Pilot pressed STOP on the phone")
            log("STOP: control returned to the remote controller")
        }
        DroneController.listener = { render() }
        DroneController.eventSink = { msg -> log(msg); link?.sendEvent(msg) }
        connect()
        render()
    }

    override fun onDestroy() {
        DroneController.listener = null
        DroneController.eventSink = null
        link?.stop()
        super.onDestroy()
    }

    private fun prefs() = getSharedPreferences("pairing", Context.MODE_PRIVATE)

    private fun connect() {
        val p = prefs()
        val host = p.getString("host", null) ?: return
        link?.stop()
        link = LinkClient(host, p.getInt("port", 8765), p.getString("token", "") ?: "",
            onStatus = { text, ok -> runOnUiThread { pcText = "PC: $text"; pcOk = ok; render() } },
            onEvent = { msg -> runOnUiThread { log(msg) } }).also { it.start() }
    }

    private fun render() {
        fun line(id: Int, text: String, ok: Boolean) = findViewById<TextView>(id).apply {
            this.text = (if (ok) "●  " else "○  ") + text
            setTextColor(getColor(if (ok) R.color.good else R.color.text))
        }
        val dc = DroneController
        line(R.id.sdkStatus, if (dc.registered) "DJI SDK: registered" else "DJI SDK: " + (dc.registerError.ifEmpty { "registering… (needs internet the first time)" }), dc.registered)
        line(R.id.droneStatus, if (dc.productConnected) "Drone: connected" else "Drone: plug in the controller and turn the drone on", dc.productConnected)
        line(R.id.pcStatus, pcText, pcOk)
        val streaming = try { dji.v5.manager.datacenter.MediaDataCenter.getInstance().liveStreamManager.isStreaming } catch (_: Exception) { false }
        line(R.id.videoStatus, if (streaming) "Video: streaming to the PC" else "Video: not streaming", streaming)
        line(R.id.controlStatus, if (dc.controlByPc) "Control: PC is flying (pilot can take over any time)" else "Control: pilot (remote controller)", dc.controlByPc)
    }

    private fun log(msg: String) {
        val time = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        logLines.addFirst("$time  $msg")
        while (logLines.size > 40) logLines.removeLast()
        findViewById<TextView>(R.id.log).text = logLines.joinToString("\n")
        render()
    }
}

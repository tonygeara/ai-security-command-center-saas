package com.aisecurity.dronelink

import android.os.Build
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Keeps a connection to the AI Security PC (the "drone link" port): proves it knows the pairing
 * code, sends telemetry 5x per second and carries out the PC's commands. Reconnects by itself.
 */
class LinkClient(
    private val host: String,
    private val port: Int,
    private val token: String,
    private val onStatus: (String, Boolean) -> Unit,
    private val onEvent: (String) -> Unit,
) {
    companion object {
        private const val HEARTBEAT_TIMEOUT_MS = 1500L  // PC silent this long -> give control back to the pilot
    }

    @Volatile private var running = true
    @Volatile private var socket: Socket? = null
    @Volatile private var lastFromPc = 0L
    private val writeLock = Any()

    fun start() = Thread(::loop, "drone-link").apply { isDaemon = true }.start()

    fun stop() {
        running = false
        try { socket?.close() } catch (_: Exception) {}
    }

    private fun loop() {
        while (running) {
            try {
                session()
            } catch (e: Exception) {
                onStatus("PC not reachable (${e.message ?: e.javaClass.simpleName})", false)
            }
            DroneController.releaseControl("PC link lost")
            if (running) Thread.sleep(3000)
        }
    }

    private fun session() {
        onStatus("Connecting to $host:$port…", false)
        val s = Socket()
        s.tcpNoDelay = true
        s.connect(InetSocketAddress(host, port), 5000)
        s.soTimeout = 5000
        socket = s
        val reader = BufferedReader(InputStreamReader(s.getInputStream(), Charsets.UTF_8))
        val out = s.getOutputStream()

        val challenge = JSONObject(reader.readLine() ?: throw IllegalStateException("PC closed the connection"))
        val nonce = challenge.getString("nonce")
        send(out, JSONObject().put("t", "hello").put("mac", hmac(token, nonce))
            .put("device", "${Build.MANUFACTURER} ${Build.MODEL}").put("app", "1.0"))
        val welcome = JSONObject(reader.readLine() ?: throw IllegalStateException("PC closed the connection"))
        if (welcome.optString("t") != "welcome") {
            running = false  // wrong pairing code or no license: don't keep retrying
            throw IllegalStateException(welcome.optString("error", "Refused by the PC"))
        }
        welcome.optJSONObject("limits")?.let {
            DroneController.maxAltitude = it.optDouble("max_altitude_m", 120.0)
            DroneController.maxDistance = it.optDouble("max_distance_m", 500.0)
            DroneController.maxSpeedLevel = it.optDouble("max_speed_level", 0.5)
        }
        DroneController.setStreamUrl(welcome.optString("rtmp"))
        onStatus("Connected to the PC ($host)", true)
        lastFromPc = System.currentTimeMillis()

        // Telemetry + heartbeat watchdog.
        val sender = Thread({
            try {
                while (running && socket === s) {
                    send(out, DroneController.telemetry())
                    if (DroneController.controlByPc && System.currentTimeMillis() - lastFromPc > HEARTBEAT_TIMEOUT_MS) {
                        DroneController.releaseControl("no heartbeat from the PC")
                    }
                    Thread.sleep(200)
                }
            } catch (_: Exception) {
                try { s.close() } catch (_: Exception) {}
            }
        }, "drone-link-tel").apply { isDaemon = true }
        sender.start()

        try {
            while (running) {
                val line = reader.readLine() ?: break
                lastFromPc = System.currentTimeMillis()
                val msg = try { JSONObject(line) } catch (_: Exception) { continue }
                when (msg.optString("t")) {
                    "stick" -> DroneController.setSticks(msg.optDouble("x"), msg.optDouble("y"), msg.optDouble("z"), msg.optDouble("r"))
                    "cmd" -> {
                        val id = msg.optInt("id")
                        val cmd = msg.optString("cmd")
                        onEvent("Command: $cmd")
                        DroneController.execute(cmd, msg.optJSONObject("args") ?: JSONObject()) { ok, err ->
                            try { send(out, JSONObject().put("t", "ack").put("id", id).put("ok", ok).put("error", err)) } catch (_: Exception) {}
                            if (!ok) onEvent("$cmd failed: $err")
                        }
                    }
                }
            }
        } finally {
            socket = null
            try { s.close() } catch (_: Exception) {}
        }
        throw IllegalStateException("connection closed")
    }

    fun sendEvent(text: String) {
        val s = socket ?: return
        try { send(s.getOutputStream(), JSONObject().put("t", "event").put("msg", text)) } catch (_: Exception) {}
    }

    // DJI reports results on the main thread, where Android forbids network writes, so every
    // message goes out through one background sender (which also keeps them in order).
    private val sender = java.util.concurrent.Executors.newSingleThreadExecutor { r ->
        Thread(r, "drone-link-send").apply { isDaemon = true }
    }

    private fun send(out: OutputStream, msg: JSONObject) {
        val bytes = (msg.toString() + "\n").toByteArray(Charsets.UTF_8)
        sender.execute {
            try { synchronized(writeLock) { out.write(bytes); out.flush() } }
            catch (_: Exception) { try { socket?.close() } catch (_: Exception) {} }
        }
    }

    private fun hmac(key: String, data: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(key.toByteArray(), "HmacSHA256"))
        return mac.doFinal(data.toByteArray()).joinToString("") { "%02x".format(it) }
    }
}

package com.aisecurity.dronelink

import android.os.Build
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.io.OutputStream
import java.net.ConnectException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.NoRouteToHostException
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Keeps a connection to the AI Security PC (the "drone link" port): proves it knows the pairing
 * code, sends telemetry 5x per second and carries out the PC's commands. Reconnects by itself.
 *
 * If the PC can't be reached at its saved address (new Wi-Fi or router, new DHCP address), the app asks the
 * local network where the PC is (UDP broadcast to port 8766). Only the PC holding this phone's pairing code
 * answers, and it signs the answer with that code, so no other device can redirect the drone. The new address
 * is saved (onHostChanged): no new QR scan is needed.
 */
class LinkClient(
    @Volatile private var host: String,
    @Volatile private var port: Int,
    private val token: String,
    private val onStatus: (String, Boolean) -> Unit,
    private val onEvent: (String) -> Unit,
    private val onHostChanged: (String, Int) -> Unit = { _, _ -> },
) {
    companion object {
        private const val HEARTBEAT_TIMEOUT_MS = 1500L  // PC silent this long -> give control back to the pilot
        private const val DISCOVERY_PORT = 8766
        private const val FIND_AFTER_FAILURES = 2  // connection attempts at the saved address before asking the network
    }

    /** Could not open the connection at all (as opposed to a connection that dropped later). */
    private class Unreachable(cause: Exception) : Exception(cause.message ?: cause.javaClass.simpleName, cause)

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
        var failures = 0
        while (running) {
            try {
                session()
            } catch (e: Unreachable) {
                failures++
                onStatus("PC not reachable at $host (${e.message})", false)
            } catch (e: Exception) {
                failures = 0
                onStatus("PC not reachable (${e.message ?: e.javaClass.simpleName})", false)
            }
            DroneController.linkLost("PC link lost")
            if (running && failures >= FIND_AFTER_FAILURES) {
                onStatus("Looking for the PC on this Wi-Fi…", false)
                val found = try { findPc() } catch (_: Exception) { null }
                if (found != null) {
                    failures = 0
                    if (found.first != host || found.second != port) {
                        host = found.first; port = found.second
                        onEvent("Found the PC at its new address ${found.first}")
                        onHostChanged(found.first, found.second)
                        continue  // connect straight away
                    }
                }
            }
            if (running) Thread.sleep(3000)
        }
    }

    /** Ask the local network for the PC that holds this pairing code. Returns (address, port) or null. */
    private fun findPc(): Pair<String, Int>? {
        val id = sha256(token).take(16)
        val nonce = ByteArray(12).also { SecureRandom().nextBytes(it) }.joinToString("") { "%02x".format(it) }
        val req = JSONObject().put("t", "where").put("id", id).put("nonce", nonce).toString().toByteArray(Charsets.UTF_8)
        val targets = mutableSetOf<InetAddress>(InetAddress.getByName("255.255.255.255"))
        try {
            NetworkInterface.getNetworkInterfaces()?.toList()?.forEach { ni ->
                if (ni.isUp && !ni.isLoopback) ni.interfaceAddresses.forEach { a -> a.broadcast?.let { targets.add(it) } }
            }
        } catch (_: Exception) {}
        DatagramSocket().use { ds ->
            ds.broadcast = true
            ds.soTimeout = 700
            repeat(3) {
                for (t in targets) try { ds.send(DatagramPacket(req, req.size, t, DISCOVERY_PORT)) } catch (_: Exception) {}
                val until = System.currentTimeMillis() + 1500
                val buf = ByteArray(1024)
                while (System.currentTimeMillis() < until) {
                    val pkt = DatagramPacket(buf, buf.size)
                    try { ds.receive(pkt) } catch (_: SocketTimeoutException) { continue }
                    val msg = try { JSONObject(String(pkt.data, 0, pkt.length, Charsets.UTF_8)) } catch (_: Exception) { continue }
                    if (msg.optString("t") != "here" || msg.optString("id") != id) continue
                    val h = msg.optString("host"); val p = msg.optInt("port", 0)
                    // Only the PC that knows the pairing code can sign this; anything else is ignored.
                    if (h.isEmpty() || p !in 1..65535 || msg.optString("sig") != hmac(token, "here|$nonce|$h|$p")) continue
                    return h to p
                }
            }
        }
        return null
    }

    private fun sha256(s: String): String =
        MessageDigest.getInstance("SHA-256").digest(s.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

    private fun session() {
        onStatus("Connecting to $host:$port…", false)
        val s = Socket()
        s.tcpNoDelay = true
        try {
            s.connect(InetSocketAddress(host, port), 5000)
        } catch (e: Exception) {
            try { s.close() } catch (_: Exception) {}
            if (e is ConnectException || e is SocketTimeoutException || e is NoRouteToHostException ||
                e is java.net.UnknownHostException || e is java.net.SocketException) throw Unreachable(e)
            throw e
        }
        s.soTimeout = 5000
        socket = s
        val reader = BufferedReader(InputStreamReader(s.getInputStream(), Charsets.UTF_8))
        val out = s.getOutputStream()

        val challenge = JSONObject(reader.readLine() ?: throw IllegalStateException("PC closed the connection"))
        val nonce = challenge.getString("nonce")
        send(out, JSONObject().put("t", "hello").put("mac", hmac(token, nonce))
            .put("device", "${Build.MANUFACTURER} ${Build.MODEL}").put("app", "1.1"))
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
                    if ((DroneController.controlByPc || DroneController.missionActive) && System.currentTimeMillis() - lastFromPc > HEARTBEAT_TIMEOUT_MS) {
                        DroneController.linkLost("no heartbeat from the PC")
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

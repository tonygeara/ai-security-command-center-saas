package com.aisecurity.dronelink

import android.content.Context
import android.os.Handler
import android.os.Looper
import dji.sdk.keyvalue.key.AirLinkKey
import dji.sdk.keyvalue.key.BatteryKey
import dji.sdk.keyvalue.key.CameraKey
import dji.sdk.keyvalue.key.DJIActionKeyInfo
import dji.sdk.keyvalue.key.DJIKey
import dji.sdk.keyvalue.key.DJIKeyInfo
import dji.sdk.keyvalue.key.FlightControllerKey
import dji.sdk.keyvalue.key.GimbalKey
import dji.sdk.keyvalue.key.KeyTools
import dji.sdk.keyvalue.value.camera.CameraMode
import dji.sdk.keyvalue.value.common.ComponentIndexType
import dji.sdk.keyvalue.value.common.EmptyMsg
import dji.sdk.keyvalue.value.common.LocationCoordinate2D
import dji.sdk.keyvalue.value.flightcontroller.FlightControlAuthorityChangeReason
import dji.sdk.keyvalue.value.gimbal.GimbalAngleRotation
import dji.sdk.keyvalue.value.gimbal.GimbalAngleRotationMode
import dji.v5.common.callback.CommonCallbacks
import dji.v5.common.error.IDJIError
import dji.v5.common.register.DJISDKInitEvent
import dji.v5.manager.KeyManager
import dji.v5.manager.SDKManager
import dji.v5.manager.aircraft.simulator.InitializationSettings
import dji.v5.manager.aircraft.simulator.SimulatorManager
import dji.v5.manager.aircraft.virtualstick.VirtualStickManager
import dji.v5.manager.aircraft.virtualstick.VirtualStickState
import dji.v5.manager.aircraft.virtualstick.VirtualStickStateListener
import dji.v5.manager.datacenter.MediaDataCenter
import dji.v5.manager.datacenter.livestream.LiveStreamSettings
import dji.v5.manager.datacenter.livestream.LiveStreamType
import dji.v5.manager.datacenter.livestream.StreamQuality
import dji.v5.manager.datacenter.livestream.settings.RtmpSettings
import dji.v5.manager.interfaces.SDKManagerCallback
import dji.v5.network.DJINetworkManager
import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt

/** Everything that talks to the DJI SDK: status, telemetry, commands and the virtual sticks. */
object DroneController {
    private const val STICK_MAX = 660          // DJI stick range is -660..660
    private const val STICK_TIMEOUT_MS = 500L  // no stick update from the PC -> centre sticks (hover)

    @Volatile var registered = false; private set
    @Volatile var registerError = ""; private set
    @Volatile var productConnected = false; private set
    @Volatile var controlByPc = false; private set
    @Volatile var lastControlChange = ""; private set
    @Volatile var streamUrl = ""; private set

    // Limits sent by the PC in the welcome message.
    @Volatile var maxAltitude = 120.0
    @Volatile var maxDistance = 500.0
    @Volatile var maxSpeedLevel = 0.5

    var listener: (() -> Unit)? = null
    var eventSink: ((String) -> Unit)? = null

    private val main = Handler(Looper.getMainLooper())
    @Volatile private var lastStickAt = 0L
    private val stickWatchdog = object : Runnable {
        override fun run() {
            if (controlByPc && System.currentTimeMillis() - lastStickAt > STICK_TIMEOUT_MS) centreSticks()
            main.postDelayed(this, 100)
        }
    }

    fun init(context: Context) {
        SDKManager.getInstance().init(context, object : SDKManagerCallback {
            override fun onRegisterSuccess() { registered = true; registerError = ""; changed() }
            override fun onRegisterFailure(error: IDJIError) { registered = false; registerError = error.description() ?: error.errorCode(); changed() }
            override fun onProductDisconnect(productId: Int) { productConnected = false; controlByPc = false; changed() }
            override fun onProductConnect(productId: Int) { productConnected = true; changed(); if (streamUrl.isNotEmpty()) startStream(streamUrl) }
            override fun onProductChanged(productId: Int) { changed() }
            override fun onInitProcess(event: DJISDKInitEvent, totalProcess: Int) {
                if (event == DJISDKInitEvent.INITIALIZE_COMPLETE) {
                    SDKManager.getInstance().registerApp()
                    watchVirtualStick()
                }
            }
            override fun onDatabaseDownloadProgress(current: Long, total: Long) {}
        })
        // Registration needs internet once; retry when the network comes back.
        DJINetworkManager.getInstance().addNetworkStatusListener { available ->
            if (available && !SDKManager.getInstance().isRegistered) SDKManager.getInstance().registerApp()
        }
        main.post(stickWatchdog)
    }

    private fun changed() = main.post { listener?.invoke() }
    private fun event(msg: String) = main.post { eventSink?.invoke(msg) }

    private fun watchVirtualStick() {
        VirtualStickManager.getInstance().setVirtualStickStateListener(object : VirtualStickStateListener {
            override fun onVirtualStickStateUpdate(stickState: VirtualStickState) {
                val wasPc = controlByPc
                controlByPc = stickState.isVirtualStickEnable
                if (wasPc && !controlByPc) event("PC control ended")
                changed()
            }
            override fun onChangeReasonUpdate(reason: FlightControlAuthorityChangeReason) {
                lastControlChange = reason.name
                if (reason != FlightControlAuthorityChangeReason.UNKNOWN) event("Control changed: ${reason.name}")
                changed()
            }
        })
    }

    // ---------- telemetry ----------

    private fun <T> read(key: DJIKey<T>): T? = try { KeyManager.getInstance().getValue(key) } catch (e: Exception) { null }

    fun telemetry(): JSONObject {
        val t = JSONObject()
        t.put("t", "tel")
        t.put("sdk_registered", registered)
        t.put("drone_connected", read(KeyTools.createKey(FlightControllerKey.KeyConnection)) == true)
        t.put("control", if (controlByPc) "PC" else "PILOT")
        t.put("simulator", SimulatorManager.getInstance().isSimulatorEnabled)
        t.put("streaming", MediaDataCenter.getInstance().liveStreamManager.isStreaming)
        read(KeyTools.createKey(FlightControllerKey.KeyAircraftLocation3D))?.let {
            if (it.latitude != 0.0 || it.longitude != 0.0) { t.put("lat", it.latitude); t.put("lon", it.longitude) }
        }
        read(KeyTools.createKey(FlightControllerKey.KeyAltitude))?.let { t.put("altitude", it) }
        read(KeyTools.createKey(FlightControllerKey.KeyCompassHeading))?.let { t.put("heading", it) }
        read(KeyTools.createKey(FlightControllerKey.KeyAircraftVelocity))?.let {
            t.put("speed", sqrt(it.x * it.x + it.y * it.y)); t.put("vertical_speed", -it.z)
        }
        read(KeyTools.createKey(BatteryKey.KeyChargeRemainingInPercent))?.let { t.put("battery", it) }
        read(KeyTools.createKey(FlightControllerKey.KeyGPSSatelliteCount))?.let { t.put("gps_satellites", it) }
        read(KeyTools.createKey(FlightControllerKey.KeyIsFlying))?.let { t.put("flying", it) }
        read(KeyTools.createKey(FlightControllerKey.KeyAreMotorsOn))?.let { t.put("motors_on", it) }
        read(KeyTools.createKey(FlightControllerKey.KeyFCFlightMode))?.let { t.put("flight_mode", it.name) }
        read(KeyTools.createKey(AirLinkKey.KeyDownLinkQuality))?.let { t.put("signal", it) }
        read(KeyTools.createKey(GimbalKey.KeyGimbalAttitude))?.let { t.put("gimbal_pitch", it.pitch) }
        read(KeyTools.createKey(FlightControllerKey.KeyHomeLocation))?.let {
            if (it.latitude != 0.0 || it.longitude != 0.0) {
                t.put("home_lat", it.latitude); t.put("home_lon", it.longitude)
                if (t.has("lat")) t.put("distance_home", distanceM(it.latitude, it.longitude, t.getDouble("lat"), t.getDouble("lon")))
            }
        }
        return t
    }

    // ---------- commands ----------

    fun execute(cmd: String, args: JSONObject, done: (Boolean, String) -> Unit) {
        val fail: (IDJIError) -> Unit = { e -> done(false, e.description() ?: e.errorCode()) }
        when (cmd) {
            "takeoff" -> action(FlightControllerKey.KeyStartTakeoff, done, fail)
            "land" -> action(FlightControllerKey.KeyStartAutoLanding, done, fail)
            "cancel_land" -> action(FlightControllerKey.KeyStopAutoLanding, done, fail)
            "go_home" -> { centreSticks(); action(FlightControllerKey.KeyStartGoHome, done, fail) }
            "cancel_go_home" -> action(FlightControllerKey.KeyStopGoHome, done, fail)
            "hover" -> { centreSticks(); done(true, "") }
            "control_on" -> enableControl(args.optDouble("speed", 0.3), done)
            "control_off" -> { releaseControl("PC turned keyboard control off"); done(true, "") }
            "gimbal" -> gimbal(args.optDouble("pitch", 0.0), done, fail)
            "photo" -> setThen(CameraKey.KeyCameraMode, CameraMode.PHOTO_NORMAL) { action(CameraKey.KeyStartShootPhoto, done, fail) }
            "record_start" -> setThen(CameraKey.KeyCameraMode, CameraMode.VIDEO_NORMAL) { action(CameraKey.KeyStartRecord, done, fail) }
            "record_stop" -> action(CameraKey.KeyStopRecord, done, fail)
            "sim_on" -> SimulatorManager.getInstance().enableSimulator(
                InitializationSettings.createInstance(LocationCoordinate2D(args.optDouble("lat"), args.optDouble("lon")), 15),
                completion(done))
            "sim_off" -> SimulatorManager.getInstance().disableSimulator(completion(done))
            "stream_on" -> if (streamUrl.isEmpty()) done(false, "No video address from the PC yet") else { startStream(streamUrl); done(true, "") }
            "stream_off" -> MediaDataCenter.getInstance().liveStreamManager.stopStream(completion(done))
            else -> done(false, "Unknown command $cmd")
        }
    }

    private fun completion(done: (Boolean, String) -> Unit) = object : CommonCallbacks.CompletionCallback {
        override fun onSuccess() = done(true, "")
        override fun onFailure(error: IDJIError) = done(false, error.description() ?: error.errorCode())
    }

    private fun action(key: DJIActionKeyInfo<EmptyMsg, EmptyMsg>, done: (Boolean, String) -> Unit, fail: (IDJIError) -> Unit) {
        KeyManager.getInstance().performAction(KeyTools.createKey(key), object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
            override fun onSuccess(t: EmptyMsg?) = done(true, "")
            override fun onFailure(error: IDJIError) = fail(error)
        })
    }

    private fun <T> setThen(key: DJIKeyInfo<T>, value: T, next: () -> Unit) {
        // Switching camera mode can fail when it is already in that mode; carry on either way.
        KeyManager.getInstance().setValue(KeyTools.createKey(key), value, object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() = next()
            override fun onFailure(error: IDJIError) = next()
        })
    }

    private fun gimbal(pitch: Double, done: (Boolean, String) -> Unit, fail: (IDJIError) -> Unit) {
        val rotation = GimbalAngleRotation().apply {
            mode = GimbalAngleRotationMode.ABSOLUTE_ANGLE
            this.pitch = max(-90.0, min(30.0, pitch))
            yawIgnored = true
            rollIgnored = true
            duration = 1.0
        }
        KeyManager.getInstance().performAction(KeyTools.createKey(GimbalKey.KeyRotateByAngle), rotation,
            object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                override fun onSuccess(t: EmptyMsg?) = done(true, "")
                override fun onFailure(error: IDJIError) = fail(error)
            })
    }

    // ---------- video ----------

    fun setStreamUrl(url: String) {
        streamUrl = url
        if (productConnected) startStream(url)
    }

    private fun startStream(url: String) {
        val manager = MediaDataCenter.getInstance().liveStreamManager
        if (manager.isStreaming) return
        manager.liveStreamSettings = LiveStreamSettings.Builder()
            .setLiveStreamType(LiveStreamType.RTMP)
            .setRtmpSettings(RtmpSettings.Builder().setUrl(url).build())
            .build()
        manager.cameraIndex = ComponentIndexType.LEFT_OR_MAIN
        manager.liveStreamQuality = StreamQuality.HD
        manager.startStream(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() { event("Video stream started"); changed() }
            override fun onFailure(error: IDJIError) { event("Video stream failed: ${error.description() ?: error.errorCode()}"); changed() }
        })
    }

    // ---------- virtual sticks ----------

    private fun enableControl(speed: Double, done: (Boolean, String) -> Unit) {
        val vs = VirtualStickManager.getInstance()
        vs.enableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                vs.setVirtualStickAdvancedModeEnabled(false)  // plain stick mode: behaves exactly like the RC sticks
                vs.speedLevel = max(0.1, min(maxSpeedLevel, speed))
                centreSticks()
                controlByPc = true
                lastStickAt = System.currentTimeMillis()
                changed()
                done(true, "")
            }
            override fun onFailure(error: IDJIError) = done(false, error.description() ?: error.errorCode())
        })
    }

    /** Hand control back to the pilot's sticks. Safe to call any time. */
    fun releaseControl(why: String) {
        if (!controlByPc) return
        centreSticks()
        VirtualStickManager.getInstance().disableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() { controlByPc = false; event("Control returned to the pilot ($why)"); changed() }
            override fun onFailure(error: IDJIError) { event("Could not release control: ${error.description()}") }
        })
    }

    fun centreSticks() {
        val vs = VirtualStickManager.getInstance()
        vs.leftStick.horizontalPosition = 0; vs.leftStick.verticalPosition = 0
        vs.rightStick.horizontalPosition = 0; vs.rightStick.verticalPosition = 0
    }

    /**
     * Sticks from the PC, each -1..1: x = left/right, y = forward/back, z = up/down, r = turn.
     * Enforces the altitude and distance limits before passing them on (Mode 2 layout).
     */
    fun setSticks(x0: Double, y0: Double, z0: Double, r0: Double) {
        if (!controlByPc) return
        lastStickAt = System.currentTimeMillis()
        var x = clamp(x0); var y = clamp(y0); var z = clamp(z0); val r = clamp(r0)
        val t = telemetry()
        if (t.optDouble("altitude", 0.0) >= maxAltitude && z > 0) z = 0.0
        val dist = t.optDouble("distance_home", 0.0)
        if (dist >= maxDistance && t.has("lat") && t.has("home_lat") && (x != 0.0 || y != 0.0)) {
            // Only allow horizontal movement that brings the drone back towards home.
            val hdg = Math.toRadians(t.optDouble("heading", 0.0))
            val north = y * cos(hdg) - x * sin(hdg)
            val east = y * sin(hdg) + x * cos(hdg)
            val awayN = t.getDouble("lat") - t.getDouble("home_lat")
            val awayE = (t.getDouble("lon") - t.getDouble("home_lon")) * cos(Math.toRadians(t.getDouble("lat")))
            if (north * awayN + east * awayE > 0) { x = 0.0; y = 0.0 }
        }
        val vs = VirtualStickManager.getInstance()
        vs.leftStick.verticalPosition = (z * STICK_MAX).toInt()
        vs.leftStick.horizontalPosition = (r * STICK_MAX).toInt()
        vs.rightStick.verticalPosition = (y * STICK_MAX).toInt()
        vs.rightStick.horizontalPosition = (x * STICK_MAX).toInt()
    }

    private fun clamp(v: Double) = if (v.isNaN()) 0.0 else max(-1.0, min(1.0, v)).let { if (abs(it) < 0.02) 0.0 else it }

    private fun distanceM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6371000.0
        val dLat = Math.toRadians(lat2 - lat1); val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2) * sin(dLat / 2) + cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * r * atan2(sqrt(a), sqrt(1 - a))
    }
}

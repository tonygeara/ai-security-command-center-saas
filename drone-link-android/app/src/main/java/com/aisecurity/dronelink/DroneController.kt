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
import dji.sdk.keyvalue.value.flightcontroller.FlightCoordinateSystem
import dji.sdk.keyvalue.value.flightcontroller.RollPitchControlMode
import dji.sdk.keyvalue.value.flightcontroller.VerticalControlMode
import dji.sdk.keyvalue.value.flightcontroller.VirtualStickFlightControlParam
import dji.sdk.keyvalue.value.flightcontroller.YawControlMode
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
    private const val STICK_TIMEOUT_MS = 500L  // no stick update from the PC -> centre sticks (hover)

    @Volatile private var sdkInitialized = false
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
            override fun onRegisterSuccess() {
                registered = true; registerError = ""; changed()
                // As DJI's sample: watch the flight controller link once registered.
                KeyManager.getInstance().listen(KeyTools.createKey(FlightControllerKey.KeyConnection), this@DroneController) { _, now ->
                    if (now == true && !productConnected) { productConnected = true; watchVirtualStick(); changed() }
                    if (now == false && productConnected) { productConnected = false; controlByPc = false; changed() }
                }
            }
            override fun onRegisterFailure(error: IDJIError) { registered = false; registerError = error.description() ?: error.errorCode(); changed() }
            override fun onProductDisconnect(productId: Int) { productConnected = false; controlByPc = false; changed() }
            override fun onProductConnect(productId: Int) {
                productConnected = true
                watchVirtualStick()  // touch flight managers only once a drone is connected (as DJI's sample does)
                changed()
                if (streamUrl.isNotEmpty()) startStream(streamUrl)
            }
            override fun onProductChanged(productId: Int) { changed() }
            override fun onInitProcess(event: DJISDKInitEvent, totalProcess: Int) {
                if (event == DJISDKInitEvent.INITIALIZE_COMPLETE) {
                    sdkInitialized = true
                    // Same order as DJI's sample: touch the core managers, then register.
                    KeyManager.getInstance()
                    SDKManager.getInstance().registerApp()
                }
            }
            override fun onDatabaseDownloadProgress(current: Long, total: Long) {}
        })
        // Registration needs internet once; retry when the network comes back — but never
        // before the SDK has finished initialising (registering too early breaks the USB link).
        DJINetworkManager.getInstance().addNetworkStatusListener { available ->
            if (sdkInitialized && available && !SDKManager.getInstance().isRegistered) SDKManager.getInstance().registerApp()
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
        t.put("drone_connected", productConnected)
        t.put("control", if (controlByPc) "PC" else "PILOT")
        mission?.let { m -> t.put("mission", JSONObject().put("state", m.state).put("lat", m.lat).put("lon", m.lon)
            .put("alt", m.alt).put("speed", m.speed).put("arrive", m.arrive).put("distance", m.distance)) }
        if (!productConnected) return t
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
        read(KeyTools.createKey(FlightControllerKey.KeyIsLandingConfirmationNeeded))?.let { t.put("landing_confirm_needed", it) }
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
            "land" -> { abortMission("land pressed"); afterHandOver { action(FlightControllerKey.KeyStartAutoLanding, done, fail) } }
            "cancel_land" -> action(FlightControllerKey.KeyStopAutoLanding, done, fail)
            "confirm_land" -> action(FlightControllerKey.KeyConfirmLanding, done, fail)
            "go_home" -> { abortMission("return home pressed"); centreSticks(); afterHandOver { action(FlightControllerKey.KeyStartGoHome, done, fail) } }
            "cancel_go_home" -> action(FlightControllerKey.KeyStopGoHome, done, fail)
            "hover" -> { abortMission("STOP pressed"); centreSticks(); done(true, "") }
            "goto" -> startMission(args, done)
            "goto_cancel" -> { abortMission("cancelled from the PC"); done(true, "") }
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
    // Advanced (velocity) mode: this phone sends a velocity command 10x per second from its own
    // timer. The target comes from the PC's sticks; if no stick update arrives for 0.5 s the target
    // is zero, so the drone hovers. Nothing is "held" inside the SDK between messages.

    // DJI body frame: "roll" velocity = forward (x axis), "pitch" velocity = right (y axis).
    // Verified in the simulator before use; flip here if a test shows otherwise.
    private const val FORWARD_IS_ROLL = true

    @Volatile private var targetX = 0.0  // right   -1..1
    @Volatile private var targetY = 0.0  // forward -1..1
    @Volatile private var targetZ = 0.0  // up      -1..1
    @Volatile private var targetR = 0.0  // turn    -1..1
    @Volatile private var speedLevel = 0.3
    private val controlLoop = java.util.concurrent.Executors.newSingleThreadScheduledExecutor { r ->
        Thread(r, "drone-control").apply { isDaemon = true }
    }
    private var loopStarted = false

    private fun enableControl(speed: Double, done: (Boolean, String) -> Unit) {
        val vs = VirtualStickManager.getInstance()
        vs.enableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                vs.setVirtualStickAdvancedModeEnabled(true)
                speedLevel = max(0.1, min(maxSpeedLevel, speed))
                centreSticks()
                controlByPc = true
                lastStickAt = System.currentTimeMillis()
                startControlLoop()
                changed()
                done(true, "")
            }
            override fun onFailure(error: IDJIError) = done(false, error.description() ?: error.errorCode())
        })
    }

    private fun startControlLoop() {
        if (loopStarted) return
        loopStarted = true
        controlLoop.scheduleWithFixedDelay({
            try { tick() } catch (e: Exception) { event("Control loop error: ${e.message}") }
        }, 0, 100, java.util.concurrent.TimeUnit.MILLISECONDS)
    }

    private fun tick() {
        if (!productConnected) return
        val m = mission
        if (m != null) missionTick(m) else sendVelocity()
    }

    private fun sendVelocity() {
        if (!controlByPc || !productConnected) return
        if (System.currentTimeMillis() - lastStickAt > STICK_TIMEOUT_MS) centreSticks()
        var x = targetX; var y = targetY; var z = targetZ; val r = targetR
        val t = telemetry()
        if (t.optDouble("altitude", 0.0) >= maxAltitude && z > 0) z = 0.0
        if (t.optDouble("distance_home", 0.0) >= maxDistance && t.has("lat") && t.has("home_lat") && (x != 0.0 || y != 0.0)) {
            // Only allow horizontal movement that brings the drone back towards home.
            val hdg = Math.toRadians(t.optDouble("heading", 0.0))
            val north = y * cos(hdg) - x * sin(hdg)
            val east = y * sin(hdg) + x * cos(hdg)
            val awayN = t.getDouble("lat") - t.getDouble("home_lat")
            val awayE = (t.getDouble("lon") - t.getDouble("home_lon")) * cos(Math.toRadians(t.getDouble("lat")))
            if (north * awayN + east * awayE > 0) { x = 0.0; y = 0.0 }
        }
        val horizontal = speedLevel * 10.0          // m/s at full stick (0.3 -> 3 m/s, max 5 m/s)
        val vertical = min(3.0, speedLevel * 6.0)   // m/s
        val yawRate = 60.0 * speedLevel / 0.5       // deg/s
        sendBody(y * horizontal, x * horizontal, z * vertical, r * yawRate)
    }

    /** One velocity command in the drone's body frame: m/s forward/right/up, deg/s turn. */
    private fun sendBody(forward: Double, right: Double, up: Double, yawRate: Double) {
        val param = VirtualStickFlightControlParam().apply {
            rollPitchCoordinateSystem = FlightCoordinateSystem.BODY
            rollPitchControlMode = RollPitchControlMode.VELOCITY
            verticalControlMode = VerticalControlMode.VELOCITY
            yawControlMode = YawControlMode.ANGULAR_VELOCITY
            if (FORWARD_IS_ROLL) { roll = forward; pitch = right } else { pitch = forward; roll = right }
            verticalThrottle = up
            yaw = yawRate
        }
        VirtualStickManager.getInstance().sendVirtualStickAdvancedParam(param)
    }

    // ---------- auto-fly to a point ----------
    // Take off if needed, climb to the set height, turn towards the target, fly there (slowing
    // down near the end), then hover / land / return home. Cancelled by any manual input, STOP,
    // the pilot's controller, or the PC link going quiet.

    private class Mission(val lat: Double, val lon: Double, val alt: Double, val speed: Double, val arrive: String) {
        @Volatile var state = "TAKING_OFF"   // TAKING_OFF, ENABLING, CLIMB, CRUISE, ARRIVED
        @Volatile var distance = -1.0
        var enabling = false
        var arrivedAt = 0L
    }

    @Volatile private var mission: Mission? = null
    val missionActive get() = mission != null

    private fun startMission(args: JSONObject, done: (Boolean, String) -> Unit) {
        if (!productConnected) { done(false, "Drone not connected"); return }
        val t = telemetry()
        if (!t.has("lat")) { done(false, "No GPS position yet"); return }
        val lat = args.optDouble("lat"); val lon = args.optDouble("lon")
        if (lat.isNaN() || lon.isNaN()) { done(false, "No target"); return }
        val homeLat = t.optDouble("home_lat", t.getDouble("lat")); val homeLon = t.optDouble("home_lon", t.getDouble("lon"))
        val fromHome = distanceM(homeLat, homeLon, lat, lon)
        if (fromHome > maxDistance) { done(false, "Target is ${fromHome.toInt()} m from home; the limit is ${maxDistance.toInt()} m"); return }
        val m = Mission(lat, lon, max(5.0, min(maxAltitude, args.optDouble("alt", 30.0))),
            max(1.0, min(8.0, args.optDouble("speed", 5.0))), args.optString("arrive", "hover"))
        val flying = t.optBoolean("flying", false)
        m.state = if (flying) "ENABLING" else "TAKING_OFF"
        mission = m
        startControlLoop()
        if (!flying) {
            KeyManager.getInstance().performAction(KeyTools.createKey(FlightControllerKey.KeyStartTakeoff),
                object : CommonCallbacks.CompletionCallbackWithParam<EmptyMsg> {
                    override fun onSuccess(e: EmptyMsg?) {}
                    override fun onFailure(error: IDJIError) { abortMission("take-off refused: ${error.description() ?: error.errorCode()}") }
                })
        }
        event("Auto-fly started: ${distanceM(t.getDouble("lat"), t.getDouble("lon"), lat, lon).toInt()} m to go at ${m.alt.toInt()} m height")
        done(true, "")
    }

    fun abortMission(why: String) {
        if (mission == null) return
        mission = null
        centreSticks()
        event("Auto-fly stopped: $why")
        changed()
    }

    private fun missionTick(m: Mission) {
        val t = telemetry()
        when (m.state) {
            "TAKING_OFF" -> if (t.optBoolean("flying") && t.optString("flight_mode") != "AUTO_TAKE_OFF") m.state = "ENABLING"
            "ENABLING" -> if (controlByPc) m.state = "CLIMB" else if (!m.enabling) {
                m.enabling = true
                val vs = VirtualStickManager.getInstance()
                vs.enableVirtualStick(object : CommonCallbacks.CompletionCallback {
                    override fun onSuccess() { vs.setVirtualStickAdvancedModeEnabled(true); controlByPc = true; lastStickAt = System.currentTimeMillis(); m.state = "CLIMB"; changed() }
                    override fun onFailure(error: IDJIError) { abortMission("could not take control: ${error.description() ?: error.errorCode()}") }
                })
            }
            "CLIMB", "CRUISE" -> {
                if (!controlByPc) { abortMission("the pilot took control"); return }
                if (!t.has("lat")) { sendBody(0.0, 0.0, 0.0, 0.0); return }
                val lat = t.getDouble("lat"); val lon = t.getDouble("lon")
                val dist = distanceM(lat, lon, m.lat, m.lon); m.distance = dist
                val bearing = bearingDeg(lat, lon, m.lat, m.lon)
                val hdgErr = wrap180(bearing - t.optDouble("heading", 0.0))
                val altErr = m.alt - t.optDouble("altitude", 0.0)
                val up = max(-2.0, min(2.0, 0.8 * altErr))
                val yawRate = if (dist > 3) max(-60.0, min(60.0, 2.0 * hdgErr)) else 0.0
                var forward = 0.0
                if (m.state == "CLIMB" && abs(altErr) < 2.0) m.state = "CRUISE"
                if (m.state == "CRUISE") {
                    if (dist < 2.0) { m.state = "ARRIVED"; m.arrivedAt = System.currentTimeMillis(); event("Auto-fly: arrived") }
                    else if (abs(hdgErr) < 30) forward = min(m.speed, max(0.5, 0.4 * dist)) * cos(Math.toRadians(hdgErr))
                }
                sendBody(forward, 0.0, if (m.state == "ARRIVED") 0.0 else up, yawRate)
            }
            "ARRIVED" -> {
                sendBody(0.0, 0.0, 0.0, 0.0)
                if (System.currentTimeMillis() - m.arrivedAt < 2000 && t.optDouble("speed", 0.0) > 0.3) return
                mission = null
                when (m.arrive) {
                    "land" -> handOverThen(FlightControllerKey.KeyStartAutoLanding, "landing at the target")
                    "home" -> handOverThen(FlightControllerKey.KeyStartGoHome, "returning home")
                    else -> event("Auto-fly: hovering over the target")
                }
                changed()
            }
        }
    }

    /** Run [next] once the flight controller has control again (DJI's own landing/RTH need it). */
    private fun afterHandOver(next: () -> Unit) {
        if (!controlByPc) { next(); return }
        VirtualStickManager.getInstance().disableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() { controlByPc = false; changed(); next() }
            override fun onFailure(error: IDJIError) { next() }
        })
    }

    /** Give control back to the flight controller, then start a DJI automatic action. */
    private fun handOverThen(key: DJIActionKeyInfo<EmptyMsg, EmptyMsg>, what: String) {
        VirtualStickManager.getInstance().disableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() {
                controlByPc = false
                action(key, { ok, err -> event(if (ok) "Auto-fly: $what" else "Auto-fly: $what failed: $err") },
                    { e -> event("Auto-fly: $what failed: ${e.description()}") })
            }
            override fun onFailure(error: IDJIError) { event("Auto-fly: could not hand over: ${error.description()}") }
        })
    }

    private fun bearingDeg(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val p1 = Math.toRadians(lat1); val p2 = Math.toRadians(lat2); val dl = Math.toRadians(lon2 - lon1)
        return Math.toDegrees(atan2(sin(dl) * cos(p2), cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)))
    }

    private fun wrap180(a: Double): Double { var x = (a + 540.0) % 360.0 - 180.0; if (x < -180) x += 360.0; return x }

    /** Hand control back to the pilot's sticks. Safe to call any time. */
    fun releaseControl(why: String) {
        abortMission(why)
        if (!controlByPc) return
        centreSticks()
        VirtualStickManager.getInstance().disableVirtualStick(object : CommonCallbacks.CompletionCallback {
            override fun onSuccess() { controlByPc = false; event("Control returned to the pilot ($why)"); changed() }
            override fun onFailure(error: IDJIError) { event("Could not release control: ${error.description()}") }
        })
    }

    fun centreSticks() {
        targetX = 0.0; targetY = 0.0; targetZ = 0.0; targetR = 0.0
    }

    /** Sticks from the PC, each -1..1: x = right, y = forward, z = up, r = turn right. */
    fun setSticks(x0: Double, y0: Double, z0: Double, r0: Double) {
        if (mission != null && (abs(x0) > 0.05 || abs(y0) > 0.05 || abs(z0) > 0.05 || abs(r0) > 0.05)) abortMission("manual control")
        if (!controlByPc) return
        targetX = clamp(x0); targetY = clamp(y0); targetZ = clamp(z0); targetR = clamp(r0)
        lastStickAt = System.currentTimeMillis()
    }

    private fun clamp(v: Double) = if (v.isNaN()) 0.0 else max(-1.0, min(1.0, v)).let { if (abs(it) < 0.02) 0.0 else it }

    private fun distanceM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val r = 6371000.0
        val dLat = Math.toRadians(lat2 - lat1); val dLon = Math.toRadians(lon2 - lon1)
        val a = sin(dLat / 2) * sin(dLat / 2) + cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) * sin(dLon / 2) * sin(dLon / 2)
        return 2 * r * atan2(sqrt(a), sqrt(1 - a))
    }
}

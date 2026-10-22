package com.aisecurity.dronelink

import android.app.Application
import android.content.Context

class DroneLinkApp : Application() {

    override fun attachBaseContext(base: Context) {
        super.attachBaseContext(base)
        // Required by DJI MSDK v5 before anything else touches the SDK.
        com.cySdkyc.clx.Helper.install(this)
    }

    override fun onCreate() {
        super.onCreate()
        DroneController.init(this)
    }
}

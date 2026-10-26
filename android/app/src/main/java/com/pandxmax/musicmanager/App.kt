package com.pandxmax.musicmanager

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        Store.init(this)
        Tags.setup()
    }
}

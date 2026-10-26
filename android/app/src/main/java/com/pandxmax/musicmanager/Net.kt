package com.pandxmax.musicmanager

import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL

object Net {
    private const val UA = "MusicManagerAndroid/1.0 ( https://github.com/PandxMax/MusicManager )"

    private fun open(url: String, method: String, headers: Map<String, String>, timeout: Int): HttpURLConnection {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = timeout
        c.readTimeout = timeout
        c.instanceFollowRedirects = true
        c.setRequestProperty("User-Agent", UA)
        for ((k, v) in headers) c.setRequestProperty(k, v)
        return c
    }

    private fun readAll(c: HttpURLConnection): ByteArray {
        val code = c.responseCode
        val stream = if (code in 200..299) c.inputStream else (c.errorStream ?: c.inputStream)
        val out = ByteArrayOutputStream()
        stream.use { it.copyTo(out) }
        if (code !in 200..299) throw RuntimeException("Error HTTP $code: " + out.toString("UTF-8").take(300))
        return out.toByteArray()
    }

    fun get(url: String, headers: Map<String, String> = emptyMap(), timeout: Int = 20000): String {
        val c = open(url, "GET", headers, timeout)
        return String(readAll(c), Charsets.UTF_8)
    }

    fun getBytes(url: String, timeout: Int = 30000): ByteArray {
        val c = open(url, "GET", emptyMap(), timeout)
        return readAll(c)
    }

    fun postJson(url: String, body: String, headers: Map<String, String>, timeout: Int = 90000): String {
        val c = open(url, "POST", headers + ("Content-Type" to "application/json"), timeout)
        c.doOutput = true
        c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        return String(readAll(c), Charsets.UTF_8)
    }
}

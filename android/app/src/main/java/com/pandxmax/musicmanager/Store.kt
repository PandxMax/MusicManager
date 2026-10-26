package com.pandxmax.musicmanager

import android.content.Context
import android.content.SharedPreferences
import android.os.Environment
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** Estado global de la app (ajustes, portapapeles de archivos, listas de reproducción). */
object Store {
    lateinit var app: Context
    lateinit var prefs: SharedPreferences

    var dark by mutableStateOf(true)
    var accent by mutableStateOf(0xFF7C5CFF.toInt())
    var coverTint by mutableStateOf(true)
    var dynamicAccent by mutableStateOf<Int?>(null)
    var provider by mutableStateOf("Claude")
    var discogsToken by mutableStateOf("")
    var lastDir by mutableStateOf("")
    var gridView by mutableStateOf(true)
    var coverMax by mutableStateOf(1200)

    var coverVersion by mutableIntStateOf(0)
    var libVersion by mutableIntStateOf(0)

    var clipPaths by mutableStateOf<List<String>>(emptyList())
    var clipCut by mutableStateOf(false)

    fun init(ctx: Context) {
        app = ctx.applicationContext
        prefs = app.getSharedPreferences("mm", Context.MODE_PRIVATE)
        dark = prefs.getBoolean("dark", true)
        accent = prefs.getInt("accent", 0xFF7C5CFF.toInt())
        coverTint = prefs.getBoolean("coverTint", true)
        provider = prefs.getString("provider", "Claude") ?: "Claude"
        discogsToken = prefs.getString("discogs", "") ?: ""
        lastDir = prefs.getString("lastDir", "") ?: ""
        gridView = prefs.getBoolean("gridView", true)
        coverMax = prefs.getInt("coverMax", 1200)
    }

    fun save() {
        prefs.edit()
            .putBoolean("dark", dark).putInt("accent", accent).putBoolean("coverTint", coverTint)
            .putString("provider", provider).putString("discogs", discogsToken)
            .putString("lastDir", lastDir).putBoolean("gridView", gridView).putInt("coverMax", coverMax)
            .apply()
    }

    fun key(p: String): String = prefs.getString("key_$p", "") ?: ""
    fun setKey(p: String, v: String) { prefs.edit().putString("key_$p", v).apply() }

    fun model(p: String): String = prefs.getString("model_$p", defaultModels(p).first()) ?: defaultModels(p).first()
    fun setModel(p: String, v: String) { prefs.edit().putString("model_$p", v).apply() }

    fun defaultModels(p: String): List<String> = when (p) {
        "Claude" -> listOf("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5")
        "ChatGPT" -> listOf("gpt-4o-mini", "gpt-4o")
        else -> listOf("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite")
    }

    fun musicRoot(): File {
        val m = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_MUSIC)
        return if (m.exists()) m else Environment.getExternalStorageDirectory()
    }

    fun storageRoot(): File = Environment.getExternalStorageDirectory()

    // ---- listas de reproducción guardadas
    fun lists(): Map<String, List<String>> {
        val out = LinkedHashMap<String, List<String>>()
        try {
            val o = JSONObject(prefs.getString("lists", "{}") ?: "{}")
            for (k in o.keys()) {
                val a = o.getJSONArray(k)
                out[k] = List(a.length()) { a.getString(it) }
            }
        } catch (_: Exception) {
        }
        return out
    }

    fun saveList(name: String, paths: List<String>) {
        val all = LinkedHashMap(lists())
        all[name] = paths
        writeLists(all)
    }

    fun deleteList(name: String) {
        val all = LinkedHashMap(lists())
        all.remove(name)
        writeLists(all)
    }

    private fun writeLists(all: Map<String, List<String>>) {
        val o = JSONObject()
        for ((k, v) in all) o.put(k, JSONArray(v))
        prefs.edit().putString("lists", o.toString()).apply()
    }
}

package com.pandxmax.musicmanager

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.MediaMetadataRetriever
import android.util.LruCache
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.URLEncoder

data class CoverCandidate(val label: String, val url: String, val thumb: String)

object Covers {
    private val cache = LruCache<String, Bitmap>(120)
    private val missing = HashSet<String>()

    fun embedded(path: String): ByteArray? {
        val r = MediaMetadataRetriever()
        return try {
            r.setDataSource(path)
            r.embeddedPicture
        } catch (_: Throwable) {
            null
        } finally {
            try { r.release() } catch (_: Throwable) {}
        }
    }

    fun folderImage(dir: File): File? {
        for (n in listOf("cover", "folder", "front", "album", "artwork")) {
            for (e in listOf("jpg", "jpeg", "png")) {
                val f = File(dir, "$n.$e")
                if (f.isFile) return f
            }
        }
        return null
    }

    fun decode(bytes: ByteArray, maxSide: Int): Bitmap? {
        val o = BitmapFactory.Options()
        o.inJustDecodeBounds = true
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o)
        var s = 1
        while (o.outWidth / (s * 2) >= maxSide && o.outHeight / (s * 2) >= maxSide) s *= 2
        val o2 = BitmapFactory.Options()
        o2.inSampleSize = s
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, o2)
    }

    /** Miniatura de la portada de un archivo (incrustada o cover.jpg de su carpeta). Se llama fuera del hilo principal. */
    fun thumb(path: String, size: Int = 200): Bitmap? {
        val key = "$path|$size|${File(path).lastModified()}"
        cache.get(key)?.let { return it }
        if (missing.contains(key)) return null
        var bytes = embedded(path)
        if (bytes == null) {
            val fi = File(path).parentFile?.let { folderImage(it) }
            if (fi != null) bytes = try { fi.readBytes() } catch (_: Throwable) { null }
        }
        val bmp = if (bytes != null) try { decode(bytes, size) } catch (_: Throwable) { null } else null
        if (bmp != null) cache.put(key, bmp) else missing.add(key)
        return bmp
    }

    fun forget(path: String) {
        cache.evictAll()
        missing.clear()
    }

    /** Reduce la imagen al lado máximo indicado y la deja en JPEG. */
    fun prepare(bytes: ByteArray, maxSide: Int): ByteArray? {
        val bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
        val big = maxOf(bmp.width, bmp.height)
        val out = if (big > maxSide) {
            val k = maxSide.toFloat() / big
            Bitmap.createScaledBitmap(bmp, (bmp.width * k).toInt().coerceAtLeast(1), (bmp.height * k).toInt().coerceAtLeast(1), true)
        } else bmp
        val bo = ByteArrayOutputStream()
        out.compress(Bitmap.CompressFormat.JPEG, 92, bo)
        return bo.toByteArray()
    }

    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    /** Varias portadas candidatas (iTunes + Deezer) en buena calidad. */
    fun search(artist: String, title: String): List<CoverCandidate> {
        val q = enc("$artist $title".trim())
        val out = ArrayList<CoverCandidate>()
        try {
            val j = JSONObject(Net.get("https://itunes.apple.com/search?term=$q&entity=song&limit=8"))
            val a = j.getJSONArray("results")
            for (i in 0 until a.length()) {
                val r = a.getJSONObject(i)
                val u = r.optString("artworkUrl100")
                if (u.isNotEmpty()) {
                    out.add(CoverCandidate(
                        r.optString("trackName") + " — " + r.optString("collectionName") + " (iTunes)",
                        u.replace("100x100bb", "1200x1200bb"), u.replace("100x100bb", "300x300bb")))
                }
            }
        } catch (_: Throwable) {
        }
        try {
            val j = JSONObject(Net.get("https://api.deezer.com/search?q=$q&limit=8"))
            val a = j.getJSONArray("data")
            for (i in 0 until a.length()) {
                val r = a.getJSONObject(i)
                val al = r.optJSONObject("album") ?: continue
                val u = al.optString("cover_xl")
                if (u.isNotEmpty()) {
                    out.add(CoverCandidate(
                        r.optString("title") + " — " + al.optString("title") + " (Deezer)", u, al.optString("cover_medium", u)))
                }
            }
        } catch (_: Throwable) {
        }
        return out.distinctBy { it.url }
    }
}

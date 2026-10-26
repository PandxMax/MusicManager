package com.pandxmax.musicmanager

import org.json.JSONObject
import java.net.URLEncoder

data class MetaCandidate(val source: String, val values: Map<String, String>) {
    val label: String
        get() = (values["artist"] ?: "") + " — " + (values["title"] ?: values["album"] ?: "") +
            (values["album"]?.let { if (values["title"] != null) "  [$it]" else "" } ?: "") +
            (values["date"]?.let { "  ($it)" } ?: "") + "  · $source"
}

object Sources {
    private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

    fun lrclib(artist: String, title: String, album: String = "", seconds: Int = 0): String? {
        try {
            var u = "https://lrclib.net/api/get?artist_name=${enc(artist)}&track_name=${enc(title)}"
            if (album.isNotBlank()) u += "&album_name=${enc(album)}"
            if (seconds > 0) u += "&duration=$seconds"
            val o = JSONObject(Net.get(u))
            val s = o.optString("syncedLyrics", "")
            if (s.isNotBlank() && s != "null") return s
            val p = o.optString("plainLyrics", "")
            if (p.isNotBlank() && p != "null") return p
        } catch (_: Throwable) {
        }
        try {
            val a = org.json.JSONArray(Net.get("https://lrclib.net/api/search?q=${enc("$artist $title")}"))
            for (i in 0 until a.length()) {
                val o = a.getJSONObject(i)
                val s = o.optString("syncedLyrics", "")
                if (s.isNotBlank() && s != "null") return s
            }
            for (i in 0 until a.length()) {
                val p = a.getJSONObject(i).optString("plainLyrics", "")
                if (p.isNotBlank() && p != "null") return p
            }
        } catch (_: Throwable) {
        }
        return null
    }

    fun musicBrainz(artist: String, title: String): List<MetaCandidate> {
        val q = "recording:\"$title\"" + if (artist.isNotBlank()) " AND artist:\"$artist\"" else ""
        val o = JSONObject(Net.get("https://musicbrainz.org/ws/2/recording/?query=${enc(q)}&fmt=json&limit=10"))
        val arr = o.optJSONArray("recordings") ?: return emptyList()
        val out = ArrayList<MetaCandidate>()
        for (i in 0 until arr.length()) {
            val r = arr.getJSONObject(i)
            val v = LinkedHashMap<String, String>()
            v["title"] = r.optString("title")
            val ac = r.optJSONArray("artist-credit")
            if (ac != null && ac.length() > 0) v["artist"] = ac.getJSONObject(0).optString("name")
            val rels = r.optJSONArray("releases")
            if (rels != null && rels.length() > 0) {
                val rel = rels.getJSONObject(0)
                v["album"] = rel.optString("title")
                val d = rel.optString("date")
                if (d.length >= 4) v["date"] = d.substring(0, 4)
                val media = rel.optJSONArray("media")
                if (media != null && media.length() > 0) {
                    val tr = media.getJSONObject(0).optJSONArray("track")
                    if (tr != null && tr.length() > 0) v["track"] = tr.getJSONObject(0).optString("number")
                }
            }
            if (!v.containsKey("date")) {
                val d = r.optString("first-release-date")
                if (d.length >= 4) v["date"] = d.substring(0, 4)
            }
            v.entries.removeAll { it.value.isBlank() }
            out.add(MetaCandidate("MusicBrainz", v))
        }
        return out
    }

    fun discogs(artist: String, title: String): List<MetaCandidate> {
        val tok = Store.discogsToken
        if (tok.isBlank()) throw RuntimeException("Falta el token de Discogs (Ajustes).")
        val q = "$artist $title".trim()
        val o = JSONObject(Net.get("https://api.discogs.com/database/search?q=${enc(q)}&type=release&per_page=10&token=$tok"))
        val arr = o.optJSONArray("results") ?: return emptyList()
        val out = ArrayList<MetaCandidate>()
        for (i in 0 until arr.length()) {
            val r = arr.getJSONObject(i)
            val v = LinkedHashMap<String, String>()
            val full = r.optString("title")
            val parts = full.split(" - ", limit = 2)
            if (parts.size == 2) { v["artist"] = parts[0]; v["album"] = parts[1] } else v["album"] = full
            v["date"] = r.optString("year")
            val g = r.optJSONArray("genre")
            val st = r.optJSONArray("style")
            val gl = ArrayList<String>()
            if (st != null && st.length() > 0) gl.add(st.getString(0))
            if (g != null && g.length() > 0) gl.add(g.getString(0))
            if (gl.isNotEmpty()) v["genre"] = gl.joinToString(" / ")
            v.entries.removeAll { it.value.isBlank() }
            out.add(MetaCandidate("Discogs", v))
        }
        return out
    }
}

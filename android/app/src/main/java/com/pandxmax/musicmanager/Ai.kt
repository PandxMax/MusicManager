package com.pandxmax.musicmanager

import org.json.JSONArray
import org.json.JSONObject

object Ai {
    fun chat(provider: String, model: String, key: String, system: String, prompt: String): String {
        when (provider) {
            "Claude" -> {
                val body = JSONObject()
                    .put("model", model).put("max_tokens", 2000)
                    .put("messages", JSONArray().put(JSONObject().put("role", "user").put("content", prompt)))
                if (system.isNotEmpty()) body.put("system", system)
                val r = JSONObject(Net.postJson("https://api.anthropic.com/v1/messages", body.toString(),
                    mapOf("x-api-key" to key, "anthropic-version" to "2023-06-01")))
                val c = r.getJSONArray("content")
                val sb = StringBuilder()
                for (i in 0 until c.length()) sb.append(c.getJSONObject(i).optString("text"))
                return sb.toString()
            }
            "Gemini" -> {
                val body = JSONObject()
                    .put("contents", JSONArray().put(JSONObject().put("role", "user")
                        .put("parts", JSONArray().put(JSONObject().put("text", prompt)))))
                if (system.isNotEmpty()) {
                    body.put("systemInstruction", JSONObject().put("parts", JSONArray().put(JSONObject().put("text", system))))
                }
                val r = JSONObject(Net.postJson(
                    "https://generativelanguage.googleapis.com/v1beta/models/$model:generateContent", body.toString(),
                    mapOf("x-goog-api-key" to key)))
                val parts = r.getJSONArray("candidates").getJSONObject(0).getJSONObject("content").getJSONArray("parts")
                val sb = StringBuilder()
                for (i in 0 until parts.length()) sb.append(parts.getJSONObject(i).optString("text"))
                return sb.toString()
            }
            else -> {
                val msgs = JSONArray()
                if (system.isNotEmpty()) msgs.put(JSONObject().put("role", "system").put("content", system))
                msgs.put(JSONObject().put("role", "user").put("content", prompt))
                val body = JSONObject().put("model", model).put("messages", msgs)
                val r = JSONObject(Net.postJson("https://api.openai.com/v1/chat/completions", body.toString(),
                    mapOf("Authorization" to "Bearer $key")))
                return r.getJSONArray("choices").getJSONObject(0).getJSONObject("message").getString("content")
            }
        }
    }

    fun ask(system: String, prompt: String): String {
        val p = Store.provider
        val key = Store.key(p)
        if (key.isBlank()) throw RuntimeException("Falta la API key de $p (Ajustes → IA).")
        return chat(p, Store.model(p), key, system, prompt)
    }

    private fun jsonOf(txt: String): String {
        val a = txt.indexOf('{')
        val b = txt.lastIndexOf('}')
        return if (a >= 0 && b > a) txt.substring(a, b + 1) else "{}"
    }

    /** Rellena metadatos a partir del título y el artista. Devuelve solo los campos que la IA conoce. */
    fun fillMetadata(title: String, artist: String): Map<String, String> {
        val system = "Eres un asistente experto en metadatos musicales. Respondes SOLO con un objeto JSON válido, sin texto " +
            "extra ni bloques de código. Si no estás seguro de un dato, déjalo como cadena vacía: nunca inventes."
        val prompt = "Canción: «$title». Artista: «$artist».\n" +
            "Devuelve el JSON con estas claves exactas: title (título oficial), artist, album (álbum del lanzamiento " +
            "original), albumartist, composer, genre (género y subgénero principal, ej. «Rock alternativo»), " +
            "date (año de lanzamiento, 4 dígitos), track (número de pista en el álbum), disc. Todos los valores son texto."
        val o = JSONObject(jsonOf(ask(system, prompt)))
        val out = LinkedHashMap<String, String>()
        for ((id, _) in FIELDS) {
            val v = o.optString(id, "").trim()
            if (v.isNotEmpty() && v != "null") out[id] = v
        }
        return out
    }

    /** Sugiere géneros y subgéneros para la canción. */
    fun suggestGenres(title: String, artist: String, album: String): List<String> {
        val system = "Eres un experto en géneros musicales. Respondes SOLO con JSON válido, sin texto extra."
        val prompt = "Canción: «$title». Artista: «$artist». Álbum: «$album».\n" +
            "Devuelve {\"generos\": [..]} con 5 opciones ordenadas de más a menos probable, cada una en el formato " +
            "«Género – Subgénero» (si no hay subgénero, solo el género)."
        val o = JSONObject(jsonOf(ask(system, prompt)))
        val a = o.optJSONArray("generos") ?: JSONArray()
        return List(a.length()) { a.getString(it) }
    }
}

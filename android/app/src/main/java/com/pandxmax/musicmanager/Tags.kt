package com.pandxmax.musicmanager

import org.jaudiotagger.audio.AudioFileIO
import org.jaudiotagger.audio.mp3.MP3File
import org.jaudiotagger.tag.FieldKey
import org.jaudiotagger.tag.Tag
import org.jaudiotagger.tag.TagOptionSingleton
import org.jaudiotagger.tag.id3.ID3v23Tag
import org.jaudiotagger.tag.images.Artwork
import java.io.File
import java.util.logging.Level
import java.util.logging.Logger

val FIELDS = listOf(
    "title" to "Título", "artist" to "Intérprete", "album" to "Álbum", "albumartist" to "Intérprete del álbum",
    "composer" to "Compositor", "genre" to "Género", "date" to "Año", "track" to "Pista",
    "disc" to "Número de disco", "comment" to "Comentario"
)

val AUDIO_EXT = setOf("mp3", "flac", "ogg", "oga", "opus", "m4a", "mp4", "aac", "wav")

data class Tech(
    val codec: String = "—", val enc: String = "—", val tag: String = "—", val bitrate: String = "—",
    val freq: String = "—", val dur: String = "—", val mode: String = "—", val size: String = "—"
)

object Tags {
    private val KEYS = mapOf(
        "title" to FieldKey.TITLE, "artist" to FieldKey.ARTIST, "album" to FieldKey.ALBUM,
        "albumartist" to FieldKey.ALBUM_ARTIST, "composer" to FieldKey.COMPOSER, "genre" to FieldKey.GENRE,
        "date" to FieldKey.YEAR, "track" to FieldKey.TRACK, "disc" to FieldKey.DISC_NO, "comment" to FieldKey.COMMENT
    )

    fun setup() {
        try {
            Logger.getLogger("org.jaudiotagger").level = Level.OFF
        } catch (_: Throwable) {
        }
        try {
            val o = TagOptionSingleton.getInstance()
            o.javaClass.getMethod("setAndroid", java.lang.Boolean.TYPE).invoke(o, true)
        } catch (_: Throwable) {
        }
    }

    fun read(f: File): Map<String, String> {
        val out = FIELDS.associate { it.first to "" }.toMutableMap()
        try {
            val af = AudioFileIO.read(f)
            val tag = af.tag
            if (tag != null) {
                for ((id, key) in KEYS) {
                    out[id] = try { tag.getFirst(key) ?: "" } catch (_: Exception) { "" }
                }
            }
        } catch (_: Throwable) {
        }
        return out
    }

    fun lyrics(f: File): String {
        return try {
            AudioFileIO.read(f).tag?.getFirst(FieldKey.LYRICS) ?: ""
        } catch (_: Throwable) {
            ""
        }
    }

    fun tech(f: File): Tech {
        var codec = "—"; var enc = "—"; var tagName = "—"; var br = "—"; var freq = "—"; var dur = "—"; var mode = "—"
        val size = "%.2f MB".format(f.length() / 1048576.0)
        try {
            val af = AudioFileIO.read(f)
            val h = af.audioHeader
            codec = when (f.extension.lowercase()) {
                "mp3" -> "MP3"; "flac" -> "FLAC"; "m4a", "mp4" -> "AAC"; "ogg", "oga" -> "Vorbis"
                "opus" -> "Opus"; else -> f.extension.uppercase()
            }
            enc = h.format ?: "—"
            val b = h.bitRate?.toIntOrNull() ?: 0
            if (b > 0) br = "$b kbps"
            val sr = h.sampleRate?.toIntOrNull() ?: 0
            if (sr > 0) freq = (if (sr % 1000 == 0) "${sr / 1000}" else "%.1f".format(sr / 1000.0)) + " kHz"
            val secs = h.trackLength
            dur = "${secs / 60}:${(secs % 60).toString().padStart(2, '0')}"
            mode = if (h.isLossless) "Sin pérdida" else if (h.isVariableBitRate) "VBR" else "CBR"
            val tn = af.tag?.javaClass?.simpleName ?: ""
            tagName = when {
                tn.contains("ID3v24") -> "ID3v2.4"
                tn.contains("ID3v23") -> "ID3v2.3"
                tn.contains("ID3v22") -> "ID3v2.2"
                tn.contains("ID3v1") -> "ID3v1"
                tn.contains("Vorbis") || tn.contains("Flac") -> "Vorbis Comment"
                tn.contains("Mp4") -> "MP4 (iTunes)"
                tn.isEmpty() -> "Sin etiquetas"
                else -> tn
            }
        } catch (_: Throwable) {
        }
        return Tech(codec, enc, tagName, br, freq, dur, mode, size)
    }

    /** Escribe los campos indicados. coverBytes = portada nueva; removeCover = quitar la portada. lyrics = null: no tocar. */
    fun write(f: File, vals: Map<String, String>, coverBytes: ByteArray?, removeCover: Boolean, lyrics: String?) {
        val af = AudioFileIO.read(f)
        val tag: Tag
        if (af is MP3File) {
            // Windows entiende ID3v2.3: se guarda siempre en esa versión
            val old = if (af.hasID3v2Tag()) af.getID3v2Tag() else null
            val t23: ID3v23Tag = when (old) {
                null -> ID3v23Tag()
                is ID3v23Tag -> old
                else -> ID3v23Tag(old)
            }
            af.setID3v2Tag(t23)
            tag = t23
        } else {
            tag = af.tagOrCreateAndSetDefault
        }
        for ((id, v) in vals) {
            val key = KEYS[id] ?: continue
            try {
                if (v.isBlank()) tag.deleteField(key) else tag.setField(key, v)
            } catch (_: Exception) {
            }
        }
        if (lyrics != null) {
            try {
                if (lyrics.isBlank()) tag.deleteField(FieldKey.LYRICS) else tag.setField(FieldKey.LYRICS, lyrics)
            } catch (_: Exception) {
            }
        }
        if (removeCover || coverBytes != null) {
            try {
                tag.deleteArtworkField()
            } catch (_: Exception) {
            }
        }
        if (coverBytes != null) {
            val art: Artwork = try {
                Class.forName("org.jaudiotagger.tag.images.AndroidArtwork").getDeclaredConstructor().newInstance() as Artwork
            } catch (_: Throwable) {
                Class.forName("org.jaudiotagger.tag.images.ArtworkFactory").getMethod("getNew").invoke(null) as Artwork
            }
            art.binaryData = coverBytes
            art.mimeType = if (coverBytes.size > 4 && coverBytes[1] == 'P'.code.toByte()) "image/png" else "image/jpeg"
            art.pictureType = 3
            tag.setField(art)
        }
        af.commit()
    }
}

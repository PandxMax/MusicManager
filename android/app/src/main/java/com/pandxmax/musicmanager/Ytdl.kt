package com.pandxmax.musicmanager

import android.content.Context
import com.yausername.ffmpeg.FFmpeg
import com.yausername.youtubedl_android.YoutubeDL
import com.yausername.youtubedl_android.YoutubeDLRequest
import java.io.File

object Ytdl {
    private var ready = false

    @Synchronized
    private fun init(ctx: Context) {
        if (ready) return
        YoutubeDL.getInstance().init(ctx)
        FFmpeg.getInstance().init(ctx)
        ready = true
    }

    /** Descarga el audio de un enlace de YouTube como MP3 en la carpeta indicada y devuelve los archivos nuevos. */
    fun download(ctx: Context, url: String, dir: File, kbps: Int, onProgress: (Float, String) -> Unit): List<File> {
        init(ctx)
        val before = dir.list()?.toSet() ?: emptySet()
        val req = YoutubeDLRequest(url)
        req.addOption("-x")
        req.addOption("--audio-format", "mp3")
        req.addOption("--audio-quality", "${kbps}K")
        req.addOption("--no-playlist")
        req.addOption("--embed-metadata")
        req.addOption("-o", dir.absolutePath + "/%(title)s.%(ext)s")
        YoutubeDL.getInstance().execute(req) { progress, _, line -> onProgress(progress, line) }
        val after = dir.list()?.toSet() ?: emptySet()
        return (after - before).filter { it.lowercase().endsWith(".mp3") }.map { File(dir, it) }
    }
}

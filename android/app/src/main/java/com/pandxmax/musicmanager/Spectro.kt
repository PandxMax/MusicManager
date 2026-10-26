package com.pandxmax.musicmanager

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.sqrt

class SpectroResult(
    val name: String, val bmp: Bitmap, val sampleRate: Int, val cutoffHz: Int, val nyquist: Int,
    val verdict: String, val level: Int, val peakDb: Float, val rmsDb: Float, val curve: FloatArray, val seconds: Int
)

object Spectro {
    private const val N = 2048

    private fun fft(re: FloatArray, im: FloatArray) {
        val n = re.size
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while ((j and bit) != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j xor bit
            if (i < j) {
                val tr = re[i]; re[i] = re[j]; re[j] = tr
                val ti = im[i]; im[i] = im[j]; im[j] = ti
            }
        }
        var len = 2
        while (len <= n) {
            val ang = -2.0 * PI / len
            val wr = cos(ang).toFloat()
            val wi = sin(ang).toFloat()
            var i = 0
            val half = len / 2
            while (i < n) {
                var cr = 1f
                var ci = 0f
                for (k in 0 until half) {
                    val a = i + k
                    val b = a + half
                    val vr = re[b] * cr - im[b] * ci
                    val vi = re[b] * ci + im[b] * cr
                    re[b] = re[a] - vr
                    im[b] = im[a] - vi
                    re[a] = re[a] + vr
                    im[a] = im[a] + vi
                    val ncr = cr * wr - ci * wi
                    ci = cr * wi + ci * wr
                    cr = ncr
                }
                i += len
            }
            len = len shl 1
        }
    }

    private fun color(db: Float): Int {
        val t = ((db + 110f) / 90f).coerceIn(0f, 1f)
        // negro → violeta → naranja → amarillo claro
        val stops = arrayOf(
            floatArrayOf(0f, 0f, 0f, 8f), floatArrayOf(0.30f, 70f, 20f, 120f), floatArrayOf(0.60f, 200f, 60f, 90f),
            floatArrayOf(0.85f, 250f, 160f, 30f), floatArrayOf(1f, 255f, 245f, 190f)
        )
        for (i in 1 until stops.size) {
            if (t <= stops[i][0]) {
                val a = stops[i - 1]
                val b = stops[i]
                val k = (t - a[0]) / (b[0] - a[0])
                return Color.rgb((a[1] + (b[1] - a[1]) * k).toInt(), (a[2] + (b[2] - a[2]) * k).toInt(), (a[3] + (b[3] - a[3]) * k).toInt())
            }
        }
        return Color.WHITE
    }

    fun analyze(ctx: Context, uri: Uri, name: String, lossless: Boolean, maxSeconds: Int = 150): SpectroResult {
        val ex = MediaExtractor()
        ex.setDataSource(ctx, uri, null)
        var track = -1
        var fmt: MediaFormat? = null
        for (i in 0 until ex.trackCount) {
            val f = ex.getTrackFormat(i)
            if ((f.getString(MediaFormat.KEY_MIME) ?: "").startsWith("audio/")) { track = i; fmt = f; break }
        }
        if (track < 0 || fmt == null) { ex.release(); throw RuntimeException("El archivo no tiene audio") }
        ex.selectTrack(track)
        var sr = fmt.getInteger(MediaFormat.KEY_SAMPLE_RATE)
        var ch = fmt.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
        val codec = MediaCodec.createDecoderByType(fmt.getString(MediaFormat.KEY_MIME)!!)
        codec.configure(fmt, null, null, 0)
        codec.start()
        val maxSamples = sr * maxSeconds
        val pcm = FloatArray(maxSamples)
        var n = 0
        val info = MediaCodec.BufferInfo()
        var inDone = false
        var outDone = false
        try {
            while (!outDone && n < maxSamples) {
                if (!inDone) {
                    val ii = codec.dequeueInputBuffer(10000)
                    if (ii >= 0) {
                        val buf = codec.getInputBuffer(ii)!!
                        val sz = ex.readSampleData(buf, 0)
                        if (sz < 0) {
                            codec.queueInputBuffer(ii, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inDone = true
                        } else {
                            codec.queueInputBuffer(ii, 0, sz, ex.sampleTime, 0)
                            ex.advance()
                        }
                    }
                }
                val oi = codec.dequeueOutputBuffer(info, 10000)
                if (oi >= 0) {
                    val ob = codec.getOutputBuffer(oi)!!
                    ob.position(info.offset)
                    ob.limit(info.offset + info.size)
                    val sb = ob.order(ByteOrder.nativeOrder()).asShortBuffer()
                    val total = sb.remaining()
                    var k = 0
                    while (k + ch <= total && n < maxSamples) {
                        var s = 0f
                        for (c in 0 until ch) s += sb.get(k + c)
                        pcm[n++] = s / ch / 32768f
                        k += ch
                    }
                    codec.releaseOutputBuffer(oi, false)
                    if ((info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) outDone = true
                } else if (oi == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    val nf = codec.outputFormat
                    sr = nf.getInteger(MediaFormat.KEY_SAMPLE_RATE)
                    ch = nf.getInteger(MediaFormat.KEY_CHANNEL_COUNT)
                }
            }
        } finally {
            try { codec.stop() } catch (_: Throwable) {}
            codec.release()
            ex.release()
        }
        if (n < N * 4) throw RuntimeException("Audio demasiado corto para analizar")

        var peak = 0f
        var sum = 0.0
        for (i in 0 until n) {
            val a = abs(pcm[i])
            if (a > peak) peak = a
            sum += pcm[i] * pcm[i]
        }
        val peakDb = 20f * log10(max(peak, 1e-6f))
        val rmsDb = 20f * log10(max(sqrt(sum / n).toFloat(), 1e-6f))

        val bins = N / 2
        val cols = 800
        val hop = max(N / 2, (n - N) / cols)
        val frames = ((n - N) / hop).coerceAtMost(cols - 1) + 1
        val win = FloatArray(N) { (0.5 - 0.5 * cos(2.0 * PI * it / (N - 1))).toFloat() }
        val re = FloatArray(N)
        val im = FloatArray(N)
        val H = 512
        val bmp = Bitmap.createBitmap(frames, H, Bitmap.Config.ARGB_8888)
        val avg = FloatArray(bins)
        val col = FloatArray(bins)
        for (f in 0 until frames) {
            val off = f * hop
            for (i in 0 until N) { re[i] = pcm[off + i] * win[i]; im[i] = 0f }
            fft(re, im)
            for (b in 0 until bins) {
                val mag = sqrt(re[b] * re[b] + im[b] * im[b]) / (N / 4f)
                val db = 20f * log10(max(mag, 1e-7f))
                col[b] = db
                avg[b] += db / frames
            }
            for (y in 0 until H) {
                val b0 = y * bins / H
                val b1 = max(b0 + 1, (y + 1) * bins / H)
                var m = -200f
                for (b in b0 until b1) if (col[b] > m) m = col[b]
                bmp.setPixel(f, H - 1 - y, color(m))
            }
        }

        // frecuencia de corte: la más alta con energía por encima del suelo de ruido
        val hzPerBin = sr / 2f / bins
        var refSum = 0f
        var refCnt = 0
        for (b in (200f / hzPerBin).toInt()..(3000f / hzPerBin).toInt().coerceAtMost(bins - 1)) { refSum += avg[b]; refCnt++ }
        val ref = if (refCnt > 0) refSum / refCnt else -40f
        val thr = max(-95f, ref - 62f)
        var cutBin = 0
        for (b in bins - 1 downTo 1) {
            var s = 0f
            val lo = max(0, b - 2)
            for (k in lo..b) s += avg[k]
            if (s / (b - lo + 1) > thr) { cutBin = b; break }
        }
        val cutoff = (cutBin * hzPerBin).toInt()
        val nyq = sr / 2

        val kHz = "%.1f".format(cutoff / 1000f)
        val (verdict, level) = when {
            lossless && cutoff < 20500 && sr >= 44100 ->
                "Dice ser sin pérdida pero se corta en ≈ $kHz kHz: parece convertido desde un MP3/AAC" to 2
            cutoff < 16500 -> "Corte en ≈ $kHz kHz: calidad baja (MP3/AAC de poco bitrate)" to 2
            cutoff < 19000 -> "Corte en ≈ $kHz kHz: típico de MP3/AAC de 128–192 kbps" to 1
            cutoff < 20500 && !lossless -> "Corte en ≈ $kHz kHz: calidad correcta (MP3 de 256–320 kbps)" to 0
            else -> "Aprovecha casi toda la banda (≈ $kHz kHz): buena calidad" to 0
        }
        return SpectroResult(name, bmp, sr, cutoff, nyq, verdict, level, peakDb, rmsDb, avg, n / sr)
    }
}

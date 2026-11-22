"""
Espectrograma y análisis de calidad (al estilo de Spek) para Music Manager.
Núcleo de cálculo (numpy + ffmpeg) y ventana de interfaz (PyQt6).
"""
import os, re, sys, subprocess, math
import numpy as np
import mutagen

FFT = 4096
DB_MIN = -120.0
# El MP3 más alto (LAME a 320 kbps) corta en unos 20.5 kHz. Un muro por encima de esto es el filtro que se aplica
# en el estudio al pasar de 48/96 kHz a 44.1 kHz, no una compresión con pérdida.
LOSSY_MAX = 20600.0
# Por debajo de esto un muro recto ya no lo deja ningún filtro de estudio: solo un MP3/AAC (de 256 kbps o menos).
SURE_MAX = 19500.0
LOSSLESS_EXT = {".flac", ".wav", ".aiff", ".aif", ".ape", ".wv"}


# ----------------------------------------------------------------- ffmpeg
def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        return shutil.which("ffmpeg")


def _run(cmd, **kw):
    flags = 0x08000000 if sys.platform == "win32" else 0  # sin ventana de consola
    return subprocess.run(cmd, creationflags=flags, **kw)


def file_info(path):
    """Datos técnicos del archivo (mutagen)."""
    ext = os.path.splitext(path)[1].lower()
    info = {"ext": ext, "sr": 0, "bits": 0, "channels": 0, "bitrate": 0, "length": 0.0,
            "codec": ext.lstrip(".").upper(), "size": os.path.getsize(path)}
    try:
        f = mutagen.File(path)
        i = f.info if f is not None else None
        if i is not None:
            info["sr"] = int(getattr(i, "sample_rate", 0) or 0)
            info["bits"] = int(getattr(i, "bits_per_sample", 0) or 0)
            info["channels"] = int(getattr(i, "channels", 0) or 0)
            info["bitrate"] = int(getattr(i, "bitrate", 0) or 0)
            info["length"] = float(getattr(i, "length", 0) or 0)
            kind = type(i).__name__
            if kind == "MP4Info":
                c = str(getattr(i, "codec", "") or "").lower()
                info["codec"] = "ALAC" if "alac" in c else "AAC"
            elif kind == "MPEGInfo":
                info["codec"] = "MP3"
            elif kind == "FLACInfo":
                info["codec"] = "FLAC"
            elif kind == "OggOpusInfo":
                info["codec"] = "Opus"
            elif kind == "OggVorbisInfo":
                info["codec"] = "Vorbis"
    except Exception:
        pass
    return info


def decode_mono(path, rate):
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("No se encontró ffmpeg. Instala el paquete «imageio-ffmpeg» (pip install imageio-ffmpeg).")
    p = _run([exe, "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(rate),
              "-rematrix_maxval", "1.0", "-f", "f32le", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("No se pudo decodificar el audio: " + p.stderr.decode("utf-8", "ignore")[-200:])
    return np.frombuffer(p.stdout, dtype=np.float32)


def decode_channels(path, rate, ch):
    """Audio con sus canales originales, sin mezclar: matriz (muestras, canales)."""
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("No se encontró ffmpeg. Instala el paquete «imageio-ffmpeg» (pip install imageio-ffmpeg).")
    p = _run([exe, "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", str(ch), "-ar", str(rate),
              "-rematrix_maxval", "1.0", "-f", "f32le", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("No se pudo decodificar el audio: " + p.stderr.decode("utf-8", "ignore")[-200:])
    a = np.frombuffer(p.stdout, dtype=np.float32)
    return a[:len(a) // ch * ch].reshape(-1, ch)


def probe_channels(path):
    exe = ffmpeg_exe()
    try:
        p = _run([exe, "-nostdin", "-i", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        m = re.search(r"\d{4,6} Hz, ([^,\n]+)", p.stderr.decode("utf-8", "ignore"))
        if m:
            w = m.group(1).strip().lower()
            return {"mono": 1, "stereo": 2}.get(w, 0)
    except Exception:
        pass
    return 0


def probe_rate(path):
    exe = ffmpeg_exe()
    try:
        p = _run([exe, "-nostdin", "-i", path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        m = re.search(r"(\d{4,6}) Hz", p.stderr.decode("utf-8", "ignore"))
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 44100


# ---------------------------------------------------------------- análisis
def analyze(path, max_frames=1100):
    info = file_info(path)
    sr = info["sr"] or probe_rate(path)
    # Los niveles (pico, RMS, recortes) se miden en cada canal tal como está en el archivo;
    # la mezcla mono (promedio) solo se usa para dibujar el espectrograma.
    ch = info["channels"] or probe_channels(path)
    if ch in (1, 2):
        raw = decode_channels(path, sr, ch)
        lo, hi = float(raw.min()), float(raw.max())
        peak_lin = max(abs(lo), abs(hi))
        sq, clip_n = 0.0, 0
        for i in range(0, len(raw), 1 << 20):   # por trozos, para no duplicar la memoria
            blk = raw[i:i + (1 << 20)]
            sq += float(np.sum(blk.astype(np.float64) ** 2))
            clip_n += int(np.count_nonzero(np.abs(blk) >= 0.999))
        rms_lin = math.sqrt(sq / max(1, raw.size))
        clipped = 100.0 * clip_n / max(1, raw.size)
        x = raw[:, 0] if ch == 1 else raw.mean(axis=1, dtype=np.float32)
        del raw
    else:   # más de dos canales (o no se sabe): mezcla normalizada de ffmpeg
        x = decode_mono(path, sr)
        peak_lin = float(np.max(np.abs(x))) if len(x) else 0.0
        rms_lin = float(np.sqrt(np.mean(x.astype(np.float64) ** 2))) if len(x) else 0.0
        clipped = float(np.mean(np.abs(x) >= 0.999)) * 100 if len(x) else 0.0
    if len(x) < FFT:
        x = np.pad(x, (0, FFT - len(x)))
    n = len(x)
    duration = n / sr

    win = np.hanning(FFT).astype(np.float32)
    norm = win.sum() / 2.0
    nframes = int(min(max_frames, max(1, (n - FFT) // 512 + 1)))
    starts = np.linspace(0, n - FFT, nframes).astype(np.int64)
    S = np.empty((FFT // 2 + 1, nframes), dtype=np.float32)
    for k, s in enumerate(starts):
        mag = np.abs(np.fft.rfft(x[s:s + FFT] * win)) / norm
        S[:, k] = 20.0 * np.log10(np.maximum(mag, 1e-9))
    np.clip(S, DB_MIN, 0, out=S)

    freqs = np.fft.rfftfreq(FFT, 1.0 / sr)
    nyq = sr / 2.0
    hz_per_bin = sr / FFT

    # Curvas: nivel alto (p90 en el tiempo) y medio
    p90 = np.percentile(S, 90, axis=1)
    mean = 10 * np.log10(np.maximum(np.mean(10 ** (S / 10.0), axis=1), 1e-12))
    mean = np.clip(mean, DB_MIN, 0)
    k = max(1, int(200 / hz_per_bin))
    pad = np.pad(p90, (k // 2, k - k // 2 - 1), mode="edge")
    sm = np.convolve(pad, np.ones(k) / k, mode="valid")

    wall = find_wall(S, freqs, hz_per_bin, nyq)
    if wall >= min(LOSSY_MAX, nyq * 0.95):   # el filtro del estudio al pasar a 44.1/48 kHz, no un MP3
        wall_hi = wall
        wall = 0.0
    else:
        wall_hi = 0.0
    if wall:   # corte de compresión con pérdida: un muro recto con silencio digital encima
        cutoff, steep = wall, True
    else:      # sin muro: hasta dónde llega el contenido (aunque sea débil)
        idx = np.where(sm > -100.0)[0]
        cutoff = float(freqs[idx[-1]]) if len(idx) else 0.0
        if cutoff > nyq * 0.985:
            cutoff = nyq
        steep = False

    # Niveles
    peak = float(20 * np.log10(max(peak_lin, 1e-9)))
    rms = float(20 * np.log10(max(rms_lin, 1e-9)))
    w = int(sr * 0.4)
    blocks = max(1, n // w)
    br = np.sqrt(np.mean(x[:blocks * w].reshape(blocks, w).astype(np.float64) ** 2, axis=1))
    bdb = 20 * np.log10(np.maximum(br, 1e-9))
    bdb = bdb[bdb > -70]
    dyn = float(np.percentile(bdb, 95) - np.percentile(bdb, 10)) if len(bdb) > 3 else 0.0

    res = {"path": path, "name": os.path.basename(path), "info": info, "sr": sr, "nyq": nyq,
           "duration": duration, "S": compact(S), "freqs": freqs, "mean": mean, "p90": p90,
           "cutoff": cutoff, "steep": steep, "wall_hi": wall_hi, "peak": peak, "rms": rms, "clipped": clipped, "dyn": dyn}
    res.update(verdict(res))
    return res


def compact(S, group=4):
    """Lo que se guarda para dibujar: el espectrograma completo ocupa ~9 MB por canción (con 500 canciones, varios GB
    y la computadora entera se ponía lenta). Para la pantalla basta con juntar las frecuencias de 4 en 4 (quedándose
    con la más fuerte) y guardarlo en 1 byte por punto: ~0.5 MB."""
    n = (S.shape[0] - 1) // group * group
    m = S[:n].reshape(n // group, group, S.shape[1]).max(axis=1)
    return np.round((np.clip(m, DB_MIN, 0) - DB_MIN) / (-DB_MIN) * 255).astype(np.uint8)


def _smooth(curve, k):
    pad = np.pad(curve, (k // 2, k - k // 2 - 1), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def find_wall(S, freqs, hz_per_bin, nyq):
    """Busca el muro de un MP3/AAC: el sonido cae de golpe y encima queda silencio digital casi total.
    Se usa la mediana en el tiempo, así los chispazos sueltos (golpes de percusión, recortes) no lo mueven.
    Un CD real que se apaga poco a poco, o que tiene agudos débiles pero continuos, no tiene muro.
    Si la música es tan oscura que la mediana ya está en silencio antes del muro, se mira el nivel de los
    momentos fuertes (percentil 90): ahí el muro sigue viéndose y los chispazos no llegan a contar.
    Devuelve la frecuencia del muro en Hz, o 0 si no lo hay."""
    k = max(1, int(200 / hz_per_bin))
    for q in (50, 90):
        f = _wall_on(_smooth(np.percentile(S, q, axis=1), k), freqs, hz_per_bin, nyq)
        if f:
            return f
    return _wall_frames(S, freqs, hz_per_bin, nyq)


def _wall_frames(S, freqs, hz_per_bin, nyq):
    """Muro visto momento a momento (para canciones bajitas u oscuras, donde las curvas de todo el tema no lo ven):
    en cada instante con sonido justo debajo del corte, se compara con lo que hay justo encima. En un CD real los
    agudos se apagan poco a poco dentro de cada instante; en un MP3 pasan de golpe al silencio en casi todos.
    Los chispazos sueltos son pocos instantes y no cambian la mediana."""
    n, nf = S.shape
    if nf < 20:
        return 0.0
    C = np.vstack([np.zeros((1, nf), dtype=np.float64), np.cumsum(S, axis=0, dtype=np.float64)])

    def band(a, b):   # nivel medio (dB) de las filas a..b-1, para cada instante
        return (C[b] - C[a]) / max(1, b - a)
    gap, wb, wa = max(1, int(250 / hz_per_bin)), max(2, int(1250 / hz_per_bin)), max(2, int(2000 / hz_per_bin))
    top = int(min(n, nyq * 0.995 / hz_per_bin))
    step = max(1, int(100 / hz_per_bin))
    best, bi = 0.0, -1
    for i in range(int(11000 / hz_per_bin), top - gap - wa, step):
        B = band(i - gap - wb, i - gap)
        A = band(i + gap, min(top, i + gap + wa))
        sel = B > -95.0
        if sel.sum() < max(10, nf * 0.05):
            continue
        d = float(np.median(B[sel] - A[sel]))
        a_lvl = float(np.median(A[sel]))
        if d >= 25.0 and a_lvl <= -105.0 and d > best:
            best, bi = d, i
    if bi < 0:
        return 0.0
    return float(freqs[bi])


def _wall_on(med, freqs, hz_per_bin, nyq):
    n = len(med)
    top = int(min(n, nyq * 0.995 / hz_per_bin))
    lo = int(10000 / hz_per_bin)
    if top - lo < 10:
        return 0.0
    gap, wb = max(1, int(250 / hz_per_bin)), max(2, int(1250 / hz_per_bin))
    # lo más fuerte que hay por encima de cada punto (hasta el final del espectro)
    above = np.maximum.accumulate(med[:top][::-1])[::-1]
    best, bi = 0.0, -1
    for i in range(lo, top - gap - 1):
        if i + gap >= top or i - gap - wb < 0:
            continue
        below = float(np.mean(med[i - gap - wb:i - gap]))
        ab = float(above[i + gap])
        drop = below - ab
        if ab <= -105.0 and below >= -100.0 and drop >= 20.0 and drop > best:
            best, bi = drop, i
    if bi < 0:
        return 0.0
    # el muro está donde la curva cruza la mitad entre el nivel de abajo y el de arriba
    below = float(np.mean(med[bi - gap - wb:bi - gap]))
    mid = (below + float(above[bi + gap])) / 2
    j = bi - gap - 1
    while j < top - 1 and med[j] >= mid:
        j += 1
    return float(freqs[j])


def mp3_kbps_for(cutoff):
    """Calidad de MP3 suficiente para un FLAC que viene de un MP3 con ese corte (un poco por encima del original,
    para que la segunda compresión no se note)."""
    if cutoff < 16800:
        return 192    # origen ~128 kbps
    if cutoff < 19500:
        return 256    # origen ~160–192 kbps
    return 320        # origen ~256–320 kbps


def fake_lossless_tip(r):
    """Solo para FLAC «sospechosos» (vienen de un MP3/AAC): recomendar MP3 320 y cuánto se ahorra."""
    if not str(r.get("verdict", "")).startswith("Falso"):
        return ""
    p = r.get("path")
    try:
        size = os.path.getsize(p) / 1048576 if p else 0
    except OSError:
        size = 0
    kb = mp3_kbps_for(r.get("cutoff", 0))
    r["mp3_kbps"] = kb
    mp3 = r.get("duration", 0) * kb / 8 / 1024
    save = size - mp3
    txt = T(f"Recomendado: guardarla como MP3 {kb} kbps. Este FLAC parece venir de un MP3 (corte en "
            f"{r.get('cutoff', 0)/1000:.1f} kHz), así que como MP3 de {kb} kbps suena igual")
    if size and save > 0.5:
        f = (lambda x: f"{x:.1f}" if x < 10 else f"{x:.0f}")
        txt += T(f" y ocupa unos {f(mp3)} MB en vez de {f(size)} MB (ahorras {f(save)} MB).")
    else:
        txt += "."
    return txt


def verdict(r):
    """Clasifica: Alta fidelidad / Normal / Calidad baja + motivos."""
    info, cutoff, nyq, sr = r["info"], r["cutoff"], r["nyq"], r["sr"]
    codec = info["codec"]
    lossless = codec in ("FLAC", "ALAC") or info["ext"] in LOSSLESS_EXT
    br = info["bitrate"] / 1000.0
    why = []
    # Los formatos con pérdida cortan por debajo de ~21 kHz. Un archivo Hi-Res (más de 48 kHz) con
    # contenido por encima de eso no puede venir de un MP3/AAC aunque no llegue al tope de su formato.
    full = not r["steep"] or (sr > 48000 and cutoff >= 21000)
    if lossless:
        bits = info["bits"] or 16
        if full and not r["steep"] and cutoff < 15000:
            level, tag = "normal", "Sin pérdida, pero con muy pocos agudos"
            why.append(f"Casi no hay sonido por encima de {cutoff/1000:.1f} kHz, así que no se puede comprobar si viene "
                       "de un MP3. Puede ser una grabación antigua o muy oscura.")
        elif full:
            hires = sr > 48000 or bits > 16
            if sr > 48000 and cutoff <= 28000:
                level, tag = "alta", "Alta fidelidad (sin pérdida)"
                why.append(f"Es {sr/1000:g} kHz / {bits} bits, pero el contenido llega a {cutoff/1000:.1f} kHz: "
                           "probablemente sea calidad CD dentro de un contenedor Hi-Res.")
            elif hires and cutoff > 22500:
                level, tag = "hires", "Alta fidelidad · Hi-Res real"
                why.append(f"Formato sin pérdida a {sr/1000:g} kHz / {bits} bits y con contenido hasta {cutoff/1000:.1f} kHz.")
            elif hires:
                level, tag = "alta", "Alta fidelidad (sin pérdida)"
                why.append(f"Es {sr/1000:g} kHz / {bits} bits, pero el contenido llega a {cutoff/1000:.1f} kHz: "
                           "probablemente sea calidad CD dentro de un contenedor Hi-Res.")
            else:
                level, tag = "alta", "Alta fidelidad (calidad CD sin pérdida)"
                why.append(f"Sin pérdida y con contenido hasta {cutoff/1000:.1f} kHz (cerca del límite de {nyq/1000:.1f} kHz).")
            if r.get("wall_hi"):
                why.append(f"El corte en {r['wall_hi']/1000:.1f} kHz es el filtro que se usa al pasar la grabación del estudio "
                           "a 44.1/48 kHz; los MP3 cortan antes (como mucho en unos 20.5 kHz).")
        elif cutoff < SURE_MAX:
            # Muro recto, silencio encima y por debajo de 19.5 kHz: ningún filtro de estudio corta ahí.
            level, tag = "normal", "Falso sin pérdida: viene de un MP3"
            why.append(f"El archivo es {codec or 'sin pérdida'}, pero tiene un muro recto en {cutoff/1000:.1f} kHz con silencio "
                       "encima: es la huella de un MP3/AAC. Convertirlo a FLAC no le devolvió la calidad.")
        else:
            # Entre 19.5 y 20.6 kHz: puede ser un MP3 de 320 o el filtro de un estudio. Desde el espectro no se distingue.
            level, tag = "posible", "Posible MP3 de 320"
            why.append(f"Tiene un muro en {cutoff/1000:.1f} kHz. Así cortan los MP3 de 320 kbps, pero también algunos "
                       "estudios al preparar la grabación: con el espectro no se puede saber cuál de los dos es.")
            why.append("Si es un MP3 de 320, al oído es casi igual que el original; no hace falta hacer nada.")
    else:
        if br >= 256 and cutoff >= 19000:
            level, tag = "alta", "Buena calidad (con pérdida)"
            why.append(f"{codec} a {br:.0f} kbps con contenido hasta {cutoff/1000:.1f} kHz. Casi indistinguible del original al oído.")
        elif br >= 160 or cutoff >= 17000:
            level, tag = "normal", "Calidad normal"
            why.append(f"{codec} a {br:.0f} kbps; el audio llega hasta {cutoff/1000:.1f} kHz.")
        else:
            level, tag = "baja", "Calidad baja"
            why.append(f"{codec} a {br:.0f} kbps; el audio se corta en {cutoff/1000:.1f} kHz (se pierden agudos).")
        why.append("Formato con pérdida: no es alta fidelidad verdadera.")
    if r["clipped"] > 0.05:
        why.append(f"Hay recortes (clipping) en {r['clipped']:.2f} % de las muestras.")
    if r["peak"] > -0.1 and r["dyn"] and r["dyn"] < 6:
        why.append("Masterizado muy fuerte (poca dinámica).")
    return {"level": level, "verdict": tag, "why": why}


# ====================================================================== UI
from i18n import tr as T
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QFont, QLinearGradient, QBrush
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QLabel,
                             QScrollArea, QFrame, QComboBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QHeaderView, QProgressBar, QFileDialog, QTextBrowser,
                             QSizePolicy)

_STOPS = [(0.0, (0, 0, 0)), (0.15, (22, 0, 95)), (0.35, (125, 0, 145)), (0.55, (215, 25, 60)),
          (0.75, (255, 150, 0)), (0.90, (255, 240, 60)), (1.0, (255, 255, 255))]


def _lut():
    xs = [s[0] for s in _STOPS]
    t = np.linspace(0, 1, 256)
    return np.stack([np.interp(t, xs, [s[1][c] for s in _STOPS]) for c in range(3)], axis=1).astype(np.uint8)


LUT = _lut()
CURVE_COLORS = ["#7C5CFF", "#22D3EE", "#F59E0B", "#F43F5E", "#34D399", "#E879F9", "#A3E635", "#60A5FA"]
LEVEL_COLOR = {"hires": "#0EA5E9", "alta": "#22C55E", "posible": "#F5B841", "normal": "#F59E0B", "baja": "#EF4444"}


def spec_image(S, fmax_ratio):
    """S (bins × frames) en dB → QImage coloreada, con el eje de frecuencia hacia arriba."""
    rows = max(2, int(S.shape[0] * fmax_ratio))
    if S.dtype == np.uint8:   # versión compacta (ver compact())
        rgb = LUT[S[:rows]][::-1]
    else:
        v = np.clip((S[:rows] - DB_MIN) / (-DB_MIN), 0, 1)
        rgb = LUT[(v * 255).astype(np.uint8)][::-1]
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
    return img


def nice_step(span, target):
    raw = span / max(1, target)
    p = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * p:
            return m * p
    return 10 * p


_LIVE = []


class SpecView(QWidget):
    """Espectrograma con ejes de frecuencia (kHz), tiempo y barra de nivel (dB)."""
    L, R, T, B = 58, 74, 8, 30

    def __init__(self, res, parent=None):
        super().__init__(parent)
        self.res, self.fmax, self._img = res, None, None
        self.setMinimumHeight(250)
        self.set_fmax(None)

    def set_fmax(self, khz):
        r = self.res
        self.fmax = min(khz * 1000.0, r["nyq"]) if khz else r["nyq"]
        self._img = None   # se dibuja cuando se vea (con cientos de canciones no se crean todas las imágenes a la vez)
        self.update()

    def image(self):
        if self._img is None:
            self._img = spec_image(self.res["S"], self.fmax / self.res["nyq"])
            _LIVE.append(self)
            while len(_LIVE) > 40:   # solo las últimas 40 vistas guardan su imagen; las demás la rehacen al volver
                old = _LIVE.pop(0)
                if old is not self:
                    old._img = None
        return self._img

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pal = self.palette()
        fg = pal.windowText().color()
        W, H = self.width(), self.height()
        plot = QRectF(self.L, self.T, W - self.L - self.R, H - self.T - self.B)
        p.fillRect(self.rect(), pal.window())
        p.drawImage(plot, self.image())
        p.setPen(QPen(fg, 1))
        small = QFont(self.font()); small.setPointSizeF(8.5); p.setFont(small)
        r = self.res
        # frecuencia
        step = nice_step(self.fmax / 1000.0, max(3, int(plot.height() / 34)))
        f = 0.0
        while f <= self.fmax / 1000.0 + 1e-6:
            y = plot.bottom() - plot.height() * (f * 1000.0 / self.fmax)
            p.setPen(QPen(QColor(255, 255, 255, 45), 1)); p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(fg)
            p.drawLine(QPointF(plot.left() - 4, y), QPointF(plot.left(), y))
            p.drawText(QRectF(0, y - 8, self.L - 7, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{f:g} kHz")
            f += step
        # línea de corte detectada
        if 0 < r["cutoff"] < self.fmax:
            y = plot.bottom() - plot.height() * (r["cutoff"] / self.fmax)
            p.setPen(QPen(QColor("#22D3EE"), 1, Qt.PenStyle.DashLine)); p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.drawText(QPointF(plot.left() + 6, y - 4), f"corte ≈ {r['cutoff']/1000:.1f} kHz")
        # tiempo
        dur = r["duration"]
        ts = nice_step(dur, max(3, int(plot.width() / 80)))
        t = 0.0
        while t <= dur + 1e-6:
            x = plot.left() + plot.width() * t / dur
            p.setPen(fg)
            p.drawLine(QPointF(x, plot.bottom()), QPointF(x, plot.bottom() + 4))
            lab = f"{int(t // 60)}:{int(t % 60):02d}"
            p.drawText(QRectF(x - 30, plot.bottom() + 5, 60, 16), Qt.AlignmentFlag.AlignCenter, lab)
            t += ts
        p.setPen(QPen(fg, 1)); p.drawRect(plot)
        # barra de dB
        bx = plot.right() + 14
        bar = QRectF(bx, plot.top(), 14, plot.height())
        g = QLinearGradient(bar.bottomLeft(), bar.topLeft())
        for pos, c in _STOPS:
            g.setColorAt(pos, QColor(*c))
        p.fillRect(bar, QBrush(g)); p.setPen(QPen(fg, 1)); p.drawRect(bar)
        for db in range(0, -121, -20):
            y = bar.top() + bar.height() * (-db / 120.0)
            p.drawLine(QPointF(bar.right(), y), QPointF(bar.right() + 4, y))
            p.drawText(QRectF(bar.right() + 5, y - 8, 40, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{db}")
        p.drawText(QRectF(bx - 6, plot.bottom() + 5, 70, 16), Qt.AlignmentFlag.AlignLeft, "dBFS")


class CurveView(QWidget):
    """Espectro medio de varias canciones superpuesto, para comparar."""
    L, R, T, B = 52, 14, 10, 28

    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.results = results
        self.fmax = max(r["nyq"] for r in results)
        self.setMinimumHeight(280)

    def set_fmax(self, khz):
        top = max(r["nyq"] for r in self.results)
        self.fmax = min(khz * 1000.0, top) if khz else top
        self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette(); fg = pal.windowText().color()
        W, H = self.width(), self.height()
        plot = QRectF(self.L, self.T, W - self.L - self.R, H - self.T - self.B)
        p.fillRect(self.rect(), pal.window())
        small = QFont(self.font()); small.setPointSizeF(8.5); p.setFont(small)
        for db in range(0, -121, -20):
            y = plot.top() + plot.height() * (-db / 120.0)
            p.setPen(QPen(QColor(128, 128, 128, 60), 1)); p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(fg); p.drawText(QRectF(0, y - 8, self.L - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{db} dB")
        step = nice_step(self.fmax / 1000.0, 10)
        f = 0.0
        while f <= self.fmax / 1000.0 + 1e-6:
            x = plot.left() + plot.width() * f * 1000.0 / self.fmax
            p.setPen(QPen(QColor(128, 128, 128, 60), 1)); p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(fg); p.drawText(QRectF(x - 25, plot.bottom() + 5, 50, 16), Qt.AlignmentFlag.AlignCenter, f"{f:g}k")
            f += step
        p.setPen(QPen(fg, 1)); p.drawRect(plot)
        p.setClipRect(plot)
        for i, r in enumerate(self.results):
            fr, y = r["freqs"], r["mean"]
            m = fr <= self.fmax
            fr, y = fr[m], y[m]
            if len(fr) > 1500:
                s = len(fr) // 1500 + 1
                fr, y = fr[::s], y[::s]
            pts = [QPointF(plot.left() + plot.width() * a / self.fmax, plot.top() + plot.height() * (-b / 120.0)) for a, b in zip(fr, y)]
            p.setPen(QPen(QColor(CURVE_COLORS[i % len(CURVE_COLORS)]), 1.6))
            for a, b in zip(pts, pts[1:]):
                p.drawLine(a, b)
        p.setClipping(False)


class Worker(QThread):
    done = pyqtSignal(int, object)
    fail = pyqtSignal(int, str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths
        self._stop = False

    def run(self):
        for i, pth in enumerate(self.paths):
            if self._stop:
                return
            try:
                self.done.emit(i, analyze(pth))
            except Exception as e:
                self.fail.emit(i, str(e))


def _badge(text, color, outline=False):
    l = QLabel(text)
    if outline:   # veredicto sin confirmar: solo el borde y el texto, para que no parezca una alarma
        l.setStyleSheet(f"background:transparent; color:{color}; border:1.5px solid {color}; border-radius:9px; "
                        "padding:2px 10px; font-weight:bold;")
    else:
        l.setStyleSheet(f"background:{color}; color:white; border-radius:9px; padding:3px 10px; font-weight:bold;")
    l.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return l


class SpectrumDialog(QWidget):
    def __init__(self, paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📊 Espectrograma y análisis de calidad")
        self.resize(1080, 760)
        self.paths, self.results, self.cards = paths, {}, []
        lay = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Frecuencia máxima:"))
        self.fmax = QComboBox()
        for lab, v in (("Completa", None), ("24 kHz", 24), ("22 kHz", 22), ("20 kHz", 20), ("16 kHz", 16), ("10 kHz", 10)):
            self.fmax.addItem(lab, v)
        self.fmax.currentIndexChanged.connect(self.apply_fmax)
        top.addWidget(self.fmax)
        top.addStretch(1)
        self.save_btn = QPushButton("💾 Guardar imagen…")
        self.save_btn.clicked.connect(self.save_image)
        top.addWidget(self.save_btn)
        lay.addLayout(top)

        self.bar = QProgressBar(); self.bar.setRange(0, len(paths)); self.bar.setValue(0)
        self.bar.setFormat("Analizando… %v / %m"); lay.addWidget(self.bar)

        self.tabs = QTabWidget(); lay.addWidget(self.tabs, 1)
        # pestaña 1: espectrogramas
        self.spec_host = QWidget(); self.spec_lay = QVBoxLayout(self.spec_host); self.spec_lay.setSpacing(14)
        self.spec_lay.addStretch(1)
        sc = QScrollArea(); sc.setWidgetResizable(True); sc.setFrameShape(QFrame.Shape.NoFrame); sc.setWidget(self.spec_host)
        self.tabs.addTab(sc, "Espectrogramas")
        # pestaña 2: comparación
        self.cmp_host = QWidget(); self.cmp_lay = QVBoxLayout(self.cmp_host)
        cmp_sc = QScrollArea(); cmp_sc.setWidgetResizable(True); cmp_sc.setFrameShape(QFrame.Shape.NoFrame); cmp_sc.setWidget(self.cmp_host)
        self.tabs.addTab(cmp_sc, "Comparación")
        self.cmp_hint = QLabel("Selecciona 2 o más canciones para compararlas." if len(paths) < 2 else "Esperando el análisis…")
        self.cmp_lay.addWidget(self.cmp_hint)
        self.curve = None
        # pestaña 3: análisis
        self.txt = QTextBrowser(); self.tabs.addTab(self.txt, "Análisis")

        self.setAcceptDrops(True)
        self.cmp_hint.setText(self.cmp_hint.text() + "\nPuedes arrastrar aquí canciones o carpetas de cualquier lugar para añadirlas.")
        self._workers, self._offset, self._total = [], 0, len(paths)
        self._finished = 0
        self._start_worker(paths, 0)

    def _start_worker(self, paths, offset):
        w = Worker(paths)
        w.done.connect(lambda i, r, o=offset: self.on_done(i + o, r))
        w.fail.connect(lambda i, m, o=offset: self.on_fail(i + o, m))
        self._workers.append(w)
        w.start()

    # ---- arrastrar canciones de otros lugares para compararlas
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        found = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isdir(p):
                for root, _d, files in os.walk(p):
                    found += [os.path.join(root, f) for f in sorted(files)]
            elif p:
                found.append(p)
        exts = (".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".wav", ".wma", ".aiff", ".aif", ".ape", ".alac")
        new = [p for p in found if p.lower().endswith(exts) and p not in self.paths][:12]
        e.acceptProposedAction()
        if not new:
            return
        self.add_paths(new)

    def add_paths(self, new):
        offset = len(self.paths)
        self.paths = self.paths + new
        self._total = len(self.paths)
        self.bar.setRange(0, self._total); self.bar.setValue(self._finished)
        self.bar.setFormat("Analizando… %v / %m"); self.bar.show()
        self.tabs.setCurrentIndex(1)
        self._start_worker(new, offset)

    # ---- resultados
    def on_done(self, i, r):
        self.results[i] = r
        self.add_card(i, r)
        self.step()

    def on_fail(self, i, msg):
        card = QLabel(f"⚠ {os.path.basename(self.paths[i])}: {msg}")
        card.setWordWrap(True)
        self.spec_lay.insertWidget(self.spec_lay.count() - 1, card)
        self.step()

    def step(self):
        self._finished += 1
        self.bar.setValue(self._finished)
        if self._finished >= len(self.paths):
            self.bar.hide()
            self.build_compare()
            self.build_text()

    def add_card(self, i, r):
        box = QFrame(); box.setFrameShape(QFrame.Shape.StyledPanel)
        v = QVBoxLayout(box)
        head = QHBoxLayout()
        sw = QLabel("■"); sw.setStyleSheet(f"color:{CURVE_COLORS[i % len(CURVE_COLORS)]}; font-size:16px;")
        head.addWidget(sw)
        t = QLabel(f"<b>{r['name']}</b>"); t.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        head.addWidget(t, 1)
        b = _badge(T(r["verdict"]), LEVEL_COLOR[r["level"]], outline=r["level"] == "posible")
        if r["level"] == "posible":
            b.setToolTip(T("Así cortan los MP3 de 320 kbps, pero también algunos estudios: no se puede asegurar."))
        head.addWidget(b)
        v.addLayout(head)
        inf = r["info"]
        bits = f" · {inf['bits']} bits" if inf["bits"] else ""
        br = f" · {inf['bitrate']/1000:.0f} kbps" if inf["bitrate"] else ""
        v.addWidget(QLabel(
            f"{inf['codec']} · {r['sr']/1000:g} kHz{bits}{br} · {r['duration']//60:.0f}:{r['duration']%60:02.0f}  |  "
            f"Corte ≈ <b>{r['cutoff']/1000:.1f} kHz</b> (máx. posible {r['nyq']/1000:.1f} kHz)  |  "
            f"Pico {r['peak']:.1f} dB · RMS {r['rms']:.1f} dB · Rango dinámico {r['dyn']:.1f} dB"))
        rec = fake_lossless_tip(r)
        if rec:   # FLAC que viene de un MP3: se recomienda convertirlo (mismo sonido, mucho menos espacio)
            row = QHBoxLayout()
            tip = QLabel("💡 " + rec)
            tip.setWordWrap(True)
            tip.setObjectName("hint")
            row.addWidget(tip, 1)
            b = QPushButton(T("Convertir a MP3…"))
            b.setObjectName("accent")
            b.clicked.connect(lambda _=False, p=r.get("path"), k=r.get("mp3_kbps", 320): self.convert_one(p, k))
            row.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
            v.addLayout(row)
        sv = SpecView(r); sv.set_fmax(self.fmax.currentData())
        r["_view"] = sv
        v.addWidget(sv)

        self.spec_lay.insertWidget(self.spec_lay.count() - 1, box)
        self.cards.append(box)

    def convert_one(self, path, kbps=320):
        w = self.window()
        if path and hasattr(w, "convert_paths"):
            w.convert_paths([path], "MP3", kbps)

    def ordered(self):
        return [self.results[k] for k in sorted(self.results)]

    def build_compare(self):
        rs = self.ordered()
        while self.cmp_lay.count() > 1:
            it = self.cmp_lay.takeAt(1)
            if it.widget():
                it.widget().deleteLater()
        self.curve = None
        self.cmp_hint.setVisible(False)
        if len(rs) < 2:
            self.cmp_hint.setText("Selecciona 2 o más canciones para compararlas."); self.cmp_hint.setVisible(True)
            return
        cols = ["Archivo", "Formato", "Muestreo", "Bits", "Bitrate", "Corte (kHz)", "Pico (dB)", "RMS (dB)", "Rango din. (dB)", "Veredicto"]
        tb = QTableWidget(len(rs), len(cols)); tb.setHorizontalHeaderLabels(cols)
        tb.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tb.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for i, r in enumerate(rs):
            inf = r["info"]
            vals = [r["name"], inf["codec"], f"{r['sr']/1000:g} kHz", str(inf["bits"] or "—"),
                    f"{inf['bitrate']/1000:.0f} kbps" if inf["bitrate"] else "—", f"{r['cutoff']/1000:.1f}",
                    f"{r['peak']:.1f}", f"{r['rms']:.1f}", f"{r['dyn']:.1f}", T(r["verdict"])]
            for j, s in enumerate(vals):
                it = QTableWidgetItem(s)
                if j == 0:
                    it.setForeground(QColor(CURVE_COLORS[i % len(CURVE_COLORS)]))
                if j == 9:
                    it.setForeground(QColor(LEVEL_COLOR[r["level"]]))
                tb.setItem(i, j, it)
        tb.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tb.horizontalHeader().setSectionResizeMode(9, QHeaderView.ResizeMode.ResizeToContents)
        for j in range(1, 9):
            tb.horizontalHeader().setSectionResizeMode(j, QHeaderView.ResizeMode.ResizeToContents)
        tb.setMaximumHeight(46 + 30 * len(rs))
        self.cmp_lay.addWidget(tb)
        self.cmp_lay.addWidget(QLabel("<b>Espectro medio superpuesto</b> (cada color es una canción; si una curva cae antes, tiene menos agudos)"))
        self.curve = CurveView(rs); self.curve.set_fmax(self.fmax.currentData())
        self.cmp_lay.addWidget(self.curve, 1)
        # veredicto de comparación
        best = max(rs, key=lambda r: (r["cutoff"], r["info"]["bitrate"]))
        self.cmp_lay.addWidget(QLabel(f"🏆 Más contenido de agudos: <b>{best['name']}</b> (hasta {best['cutoff']/1000:.1f} kHz)"))

    def build_text(self):
        out = []
        for r in self.ordered():
            c = LEVEL_COLOR[r["level"]]
            out.append(f"<h3>{r['name']}</h3><p style='color:{c}'><b>{T(r['verdict'])}</b></p><ul>" +
                       "".join(f"<li>{T(w)}</li>" for w in r["why"]) + "</ul>")
            rec = fake_lossless_tip(r)
            if rec:
                out.append(f"<p>💡 <b>{T('Recomendación')}:</b> {rec}</p>")
        out.append(T("<hr><p><small>Cómo leerlo: el eje vertical es la frecuencia (kHz) y el color es el volumen (dBFS). "
                     "Un corte horizontal brusco indica compresión con pérdida (MP3, AAC…) o un archivo convertido desde ella. "
                     "El espectrograma se dibuja sobre la mezcla mono; el pico y los recortes se miden en cada canal. Es una estimación, no una prueba definitiva.</small></p>"))
        self.txt.setHtml("".join(out))

    def apply_fmax(self):
        v = self.fmax.currentData()
        for r in self.results.values():
            r["_view"].set_fmax(v)
        if self.curve:
            self.curve.set_fmax(v)

    def save_image(self):
        w = self.spec_host if self.tabs.currentIndex() == 0 else self.cmp_host
        fn, _ = QFileDialog.getSaveFileName(self, "Guardar imagen", "espectrograma.png", "PNG (*.png)")
        if fn:
            w.grab().save(fn, "PNG")

    def shutdown(self):
        for w in self._workers:
            w._stop = True
        for w in self._workers:
            w.wait(3000)

    def closeEvent(self, e):
        self.shutdown()
        super().closeEvent(e)

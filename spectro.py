"""
Espectrograma y análisis de calidad (al estilo de Spek) para Music Manager.
Núcleo de cálculo (numpy + ffmpeg) y ventana de interfaz (PyQt6).
"""
import os, re, sys, subprocess, math
import numpy as np
import mutagen

FFT = 4096
DB_MIN = -120.0
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
              "-f", "f32le", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("No se pudo decodificar el audio: " + p.stderr.decode("utf-8", "ignore")[-200:])
    return np.frombuffer(p.stdout, dtype=np.float32)


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
    x = decode_mono(path, sr)
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

    # Frecuencia de corte: último punto con energía real por encima del "suelo"
    upper = sm[len(sm) // 2:]
    floor = float(np.percentile(upper, 5))
    thr = min(max(floor + 15.0, -100.0), -75.0)
    idx = np.where(sm > thr)[0]
    cutoff = float(freqs[idx[-1]]) if len(idx) else 0.0
    if cutoff > nyq * 0.985:
        cutoff = nyq
    ci = int(min(len(sm) - 1, cutoff / hz_per_bin))
    a = sm[max(0, ci - int(500 / hz_per_bin))]
    b = sm[min(len(sm) - 1, ci + int(500 / hz_per_bin))]
    steep = (a - b) >= 25.0 and cutoff < nyq * 0.97

    # Niveles
    peak = float(20 * np.log10(max(float(np.max(np.abs(x))), 1e-9)))
    rms = float(20 * np.log10(max(float(np.sqrt(np.mean(x.astype(np.float64) ** 2))), 1e-9)))
    clipped = float(np.mean(np.abs(x) >= 0.999)) * 100
    w = int(sr * 0.4)
    blocks = max(1, n // w)
    br = np.sqrt(np.mean(x[:blocks * w].reshape(blocks, w).astype(np.float64) ** 2, axis=1))
    bdb = 20 * np.log10(np.maximum(br, 1e-9))
    bdb = bdb[bdb > -70]
    dyn = float(np.percentile(bdb, 95) - np.percentile(bdb, 10)) if len(bdb) > 3 else 0.0

    res = {"path": path, "name": os.path.basename(path), "info": info, "sr": sr, "nyq": nyq,
           "duration": duration, "S": S, "freqs": freqs, "mean": mean, "p90": p90,
           "cutoff": cutoff, "steep": steep, "peak": peak, "rms": rms, "clipped": clipped, "dyn": dyn}
    res.update(verdict(res))
    return res


def verdict(r):
    """Clasifica: Alta fidelidad / Normal / Calidad baja + motivos."""
    info, cutoff, nyq, sr = r["info"], r["cutoff"], r["nyq"], r["sr"]
    codec = info["codec"]
    lossless = codec in ("FLAC", "ALAC") or info["ext"] in LOSSLESS_EXT
    br = info["bitrate"] / 1000.0
    why = []
    full = cutoff >= 0.9 * nyq
    if lossless:
        bits = info["bits"] or 16
        if full:
            hires = sr > 48000 or bits > 16
            if hires and cutoff > 22500:
                level, tag = "alta", "Alta fidelidad · Hi-Res real"
                why.append(f"Formato sin pérdida a {sr/1000:g} kHz / {bits} bits y con contenido hasta {cutoff/1000:.1f} kHz.")
            elif hires:
                level, tag = "alta", "Alta fidelidad (sin pérdida)"
                why.append(f"Es {sr/1000:g} kHz / {bits} bits, pero el contenido llega a {cutoff/1000:.1f} kHz: "
                           "probablemente sea calidad CD dentro de un contenedor Hi-Res.")
            else:
                level, tag = "alta", "Alta fidelidad (calidad CD sin pérdida)"
                why.append(f"Sin pérdida y con contenido hasta {cutoff/1000:.1f} kHz (cerca del límite de {nyq/1000:.1f} kHz).")
        else:
            level, tag = "normal", "Sospechoso: sin pérdida, pero con corte"
            why.append(f"El archivo es {codec or 'sin pérdida'}, pero el audio se corta en {cutoff/1000:.1f} kHz"
                       f"{' con un borde muy marcado' if r['steep'] else ''}. "
                       "Suele pasar al convertir un MP3/AAC a FLAC: no gana calidad real.")
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
LEVEL_COLOR = {"alta": "#22C55E", "normal": "#F59E0B", "baja": "#EF4444"}


def spec_image(S, fmax_ratio):
    """S (bins × frames) en dB → QImage coloreada, con el eje de frecuencia hacia arriba."""
    rows = max(2, int(S.shape[0] * fmax_ratio))
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
        self._img = spec_image(r["S"], self.fmax / r["nyq"])
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pal = self.palette()
        fg = pal.windowText().color()
        W, H = self.width(), self.height()
        plot = QRectF(self.L, self.T, W - self.L - self.R, H - self.T - self.B)
        p.fillRect(self.rect(), pal.window())
        p.drawImage(plot, self._img)
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


def _badge(text, color):
    l = QLabel(text)
    l.setStyleSheet(f"background:{color}; color:white; border-radius:9px; padding:3px 10px; font-weight:bold;")
    l.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return l


class SpectrumDialog(QDialog):
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
        self.tabs.addTab(self.cmp_host, "Comparación")
        self.cmp_hint = QLabel("Selecciona 2 o más canciones para compararlas." if len(paths) < 2 else "Esperando el análisis…")
        self.cmp_lay.addWidget(self.cmp_hint)
        self.curve = None
        # pestaña 3: análisis
        self.txt = QTextBrowser(); self.tabs.addTab(self.txt, "Análisis")

        self.worker = Worker(paths)
        self.worker.done.connect(self.on_done)
        self.worker.fail.connect(self.on_fail)
        self.worker.finished.connect(lambda: None)
        self.worker.start()
        self._finished = 0

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
        head.addWidget(_badge(r["verdict"], LEVEL_COLOR[r["level"]]))
        v.addLayout(head)
        inf = r["info"]
        bits = f" · {inf['bits']} bits" if inf["bits"] else ""
        br = f" · {inf['bitrate']/1000:.0f} kbps" if inf["bitrate"] else ""
        v.addWidget(QLabel(
            f"{inf['codec']} · {r['sr']/1000:g} kHz{bits}{br} · {r['duration']//60:.0f}:{r['duration']%60:02.0f}  |  "
            f"Corte ≈ <b>{r['cutoff']/1000:.1f} kHz</b> (máx. posible {r['nyq']/1000:.1f} kHz)  |  "
            f"Pico {r['peak']:.1f} dB · RMS {r['rms']:.1f} dB · Rango dinámico {r['dyn']:.1f} dB"))
        sv = SpecView(r); sv.set_fmax(self.fmax.currentData())
        r["_view"] = sv
        v.addWidget(sv)
        self.spec_lay.insertWidget(self.spec_lay.count() - 1, box)
        self.cards.append(box)

    def ordered(self):
        return [self.results[k] for k in sorted(self.results)]

    def build_compare(self):
        rs = self.ordered()
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
                    f"{r['peak']:.1f}", f"{r['rms']:.1f}", f"{r['dyn']:.1f}", r["verdict"]]
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
            out.append(f"<h3>{r['name']}</h3><p style='color:{c}'><b>{r['verdict']}</b></p><ul>" +
                       "".join(f"<li>{w}</li>" for w in r["why"]) + "</ul>")
        out.append("<hr><p><small>Cómo leerlo: el eje vertical es la frecuencia (kHz) y el color es el volumen (dBFS). "
                   "Un corte horizontal brusco indica compresión con pérdida (MP3, AAC…) o un archivo convertido desde ella. "
                   "El análisis se hace sobre la mezcla mono. Es una estimación, no una prueba definitiva.</small></p>")
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

    def closeEvent(self, e):
        self.worker._stop = True
        self.worker.wait(3000)
        super().closeEvent(e)

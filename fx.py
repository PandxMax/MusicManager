"""Ajustes de la canción: graves, medios, agudos, tempo, tono, velocidad, bucle, eco, etc.
Se aplican con ffmpeg; se puede escuchar una muestra y guardar como canción nueva o reemplazar la original."""
import os, re, sys, tempfile, subprocess
from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QSlider, QComboBox,
                             QTabWidget, QWidget, QCheckBox, QDoubleSpinBox, QSpinBox, QProgressBar, QMessageBox,
                             QScrollArea, QFrame)
from spectro import ffmpeg_exe, file_info

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_AUDIO = True
except Exception:   # pragma: no cover
    HAS_AUDIO = False

DEFAULTS = dict(bass=0, mid=0, treble=0, volume=0, normalize=False,
                tempo=1.0, pitch=0, rate=1.0,
                trim_start=0.0, trim_end=0.0, loops=1, reverse=False,
                echo=0, reverb=0, width=100, mono=False, karaoke=False, fade_in=0.0, fade_out=0.0)

PRESETS = [
    ("Sin cambios", {}),
    ("Bajos potentes", dict(bass=9, treble=1, volume=-3)),
    ("Voz clara", dict(bass=-4, mid=4, treble=3)),
    ("Agudos brillantes", dict(treble=8, bass=-2)),
    ("Nightcore (más rápida y aguda)", dict(rate=1.25)),
    ("Slowed + reverb", dict(rate=0.85, reverb=55, bass=3)),
    ("Más lenta (mismo tono)", dict(tempo=0.8)),
    ("Más rápida (mismo tono)", dict(tempo=1.2)),
    ("Karaoke (quitar la voz)", dict(karaoke=True)),
    ("Sonido de radio vieja", dict(bass=-12, treble=-6, mid=6, mono=True)),
]

# códec de salida según la extensión (se conserva el formato del archivo)
CODECS = {
    ".mp3": (["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3"], True),
    ".m4a": (["-c:a", "aac", "-b:a", "256k"], True),
    ".mp4": (["-c:a", "aac", "-b:a", "256k"], True),
    ".aac": (["-c:a", "aac", "-b:a", "256k"], False),
    ".flac": (["-c:a", "flac"], True),
    ".ogg": (["-c:a", "libvorbis", "-q:a", "8"], False),
    ".opus": (["-c:a", "libopus", "-b:a", "192k"], False),
    ".wav": (["-c:a", "pcm_s16le"], False),
    ".wma": (["-c:a", "wmav2", "-b:a", "192k"], False),
}


def atempo_chain(t):
    """atempo solo admite 0.5–2 por filtro: se encadenan los que hagan falta."""
    out = []
    while t > 2.0:
        out.append("atempo=2.0")
        t /= 2.0
    while t < 0.5:
        out.append("atempo=0.5")
        t /= 0.5
    if abs(t - 1.0) > 1e-4:
        out.append(f"atempo={t:.5f}")
    return out


def build_filters(p, sr=44100, dur=0.0):
    """Cadena de filtros de ffmpeg para los ajustes p. Devuelve (texto, duración_estimada_de_salida)."""
    q = dict(DEFAULTS)
    q.update(p)
    sr = int(sr or 44100)
    f = []
    seg = dur
    if q["trim_start"] > 0 or q["trim_end"] > 0:
        a, b = float(q["trim_start"]), float(q["trim_end"])
        arg = f"start={a:.3f}" + (f":end={b:.3f}" if b > a else "")
        f += [f"atrim={arg}", "asetpts=PTS-STARTPTS"]
        seg = (b if b > a else dur) - a
    n = int(q["loops"])
    if n > 1:
        f.append(f"aloop=loop={n - 1}:size=2000000000")
        seg *= n
    if q["reverse"]:
        f.append("areverse")
    # tono (semitonos), velocidad (tasa: cambia velocidad y tono) y tempo (cambia solo la velocidad)
    ratio = 2 ** (float(q["pitch"]) / 12.0)
    mult = ratio * float(q["rate"])
    tempo = float(q["tempo"]) / ratio
    if abs(mult - 1.0) > 1e-4:
        f += [f"asetrate={sr * mult:.2f}", f"aresample={sr}"]
    f += atempo_chain(tempo)
    speed = float(q["tempo"]) * float(q["rate"])
    out_dur = seg / speed if speed > 0 else seg
    if q["bass"]:
        f.append(f"bass=g={float(q['bass']):.1f}:f=110:w=0.8")
    if q["mid"]:
        f.append(f"equalizer=f=1000:t=q:w=0.7:g={float(q['mid']):.1f}")
    if q["treble"]:
        f.append(f"treble=g={float(q['treble']):.1f}:f=3500:w=0.8")
    if q["karaoke"]:
        f.append("pan=stereo|c0=c0-c1|c1=c1-c0")
    if int(q["width"]) != 100 and not q["mono"]:
        f.append(f"extrastereo=m={int(q['width']) / 100.0:.2f}")
    if q["mono"]:
        f.append("pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1")
    if q["echo"] > 0:
        e = int(q["echo"]) / 100.0
        f.append(f"aecho=0.8:{0.9 - 0.3 * e:.2f}:{int(250 + 350 * e)}:{0.25 + 0.4 * e:.2f}")
    if q["reverb"] > 0:
        r = int(q["reverb"]) / 100.0
        f.append(f"aecho=0.8:{0.7 + 0.15 * r:.2f}:40|70|110|160:{0.35 * r + .05:.2f}|{0.3 * r + .04:.2f}|{0.25 * r + .03:.2f}|{0.2 * r + .02:.2f}")
    if q["volume"]:
        f.append(f"volume={float(q['volume']):.1f}dB")
    if q["normalize"]:
        f.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    if q["fade_in"] > 0:
        f.append(f"afade=t=in:st=0:d={float(q['fade_in']):.2f}")
    if q["fade_out"] > 0 and out_dur > q["fade_out"]:
        f.append(f"afade=t=out:st={out_dur - float(q['fade_out']):.2f}:d={float(q['fade_out']):.2f}")
    f.append(f"aresample={sr}")
    return ",".join(f), out_dur


def is_default(p):
    q = dict(DEFAULTS)
    q.update(p)
    return all(q[k] == v for k, v in DEFAULTS.items())


def build_cmd(src, dst, p, sr=44100, dur=0.0, preview=None, offset=0.0):
    """Orden completa de ffmpeg. preview: segundos de muestra (salida WAV) o None para el archivo final."""
    flt, _ = build_filters(p, sr, dur)
    cmd = [ffmpeg_exe() or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    if preview and offset > 0 and not p.get("reverse") and not p.get("trim_start") and not p.get("trim_end") \
            and int(p.get("loops", 1)) <= 1:
        cmd += ["-ss", f"{offset:.2f}"]
    cmd += ["-i", src]
    if preview:
        cmd += ["-vn", "-af", flt, "-t", str(preview), "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", dst]
    else:
        ext = os.path.splitext(dst)[1].lower()
        codec, with_cover = CODECS.get(ext, CODECS[".mp3"])
        cmd += ["-map", "0:a:0"]
        if with_cover:
            cmd += ["-map", "0:v?", "-c:v", "copy", "-disposition:v", "attached_pic"]
        cmd += ["-map_metadata", "0", "-af", flt] + codec + [dst]
    return cmd


class FxWorker(QThread):
    progress = pyqtSignal(int)
    ok = pyqtSignal(str)
    fail = pyqtSignal(str)

    def __init__(self, cmd, dst, total):
        super().__init__()
        self.cmd, self.dst, self.total = cmd, dst, max(total, 0.1)
        self.proc = None

    def run(self):
        cmd = list(self.cmd)
        cmd[1:1] = ["-progress", "pipe:1", "-nostats"]
        flags = 0x08000000 if sys.platform == "win32" else 0
        tail = []
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                         encoding="utf-8", errors="replace", creationflags=flags)
            for line in self.proc.stdout:
                line = line.strip()
                m = re.match(r"out_time_(?:us|ms)=(\d+)", line)
                if m:
                    self.progress.emit(min(99, int(int(m.group(1)) / 1e6 * 100 / self.total)))
                elif line and "=" not in line[:20]:
                    tail.append(line)
            rc = self.proc.wait()
        except Exception as e:
            self.fail.emit(str(e))
            return
        if self.isInterruptionRequested():
            self.fail.emit("cancelado")
            return
        if rc != 0 or not os.path.exists(self.dst) or os.path.getsize(self.dst) == 0:
            self.fail.emit("\n".join(tail[-6:]) or f"ffmpeg terminó con el código {rc}")
            return
        self.progress.emit(100)
        self.ok.emit(self.dst)

    def cancel(self):
        self.requestInterruption()
        try:
            if self.proc is not None:
                self.proc.kill()
        except Exception:
            pass


def unique_name(path, suffix=" (editada)"):
    base, ext = os.path.splitext(path)
    cand = f"{base}{suffix}{ext}"
    i = 2
    while os.path.exists(cand):
        cand = f"{base}{suffix} {i}{ext}"
        i += 1
    return cand


class Row:
    """Fila 'etiqueta + deslizador + valor' con doble clic para volver al valor normal."""
    def __init__(self, grid, r, label, lo, hi, default, scale=1, unit="", dec=0, tip=""):
        self.scale, self.unit, self.dec, self.default = scale, unit, dec, default
        self.lbl = QLabel(label)
        self.s = QSlider(Qt.Orientation.Horizontal)
        self.s.setRange(int(lo * scale), int(hi * scale))
        self.s.setValue(int(default * scale))
        self.s.setMinimumWidth(240)
        self.val = QLabel()
        self.val.setMinimumWidth(70)
        self.val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.s.valueChanged.connect(self.upd)
        self.s.mouseDoubleClickEvent = lambda e: self.s.setValue(int(self.default * self.scale))
        if tip:
            self.lbl.setToolTip(tip)
            self.s.setToolTip(tip + " (doble clic: valor normal)")
        grid.addWidget(self.lbl, r, 0)
        grid.addWidget(self.s, r, 1)
        grid.addWidget(self.val, r, 2)
        self.upd()

    def upd(self):
        v = self.value()
        txt = f"{v:+.{self.dec}f}" if self.default == 0 and self.unit in ("dB", " st") else f"{v:.{self.dec}f}"
        self.val.setText(f"{txt}{self.unit}")

    def value(self):
        return self.s.value() / self.scale

    def set(self, v):
        self.s.setValue(int(round(v * self.scale)))


class FxDialog(QDialog):
    """Ajustes de la canción. on_saved(path, reemplazado) se llama al terminar de guardar."""
    def __init__(self, path, parent=None, offset=0.0, release=None, on_saved=None):
        super().__init__(parent)
        self.path, self.offset, self.release, self.on_saved = path, offset, release, on_saved
        self.setWindowTitle("Ajustes de la canción")
        self.resize(640, 560)
        self.worker = self.tmp = self.cur_dst = None
        self.pplayer = None
        try:
            inf = file_info(path)
            self.sr, self.dur = inf.get("sr") or 44100, float(inf.get("length") or 0.0)
        except Exception:
            self.sr, self.dur = 44100, 0.0
        v = QVBoxLayout(self)
        title = QLabel(f"<b>{os.path.basename(path)}</b>")
        title.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(title)
        top = QHBoxLayout()
        top.addWidget(QLabel("Ajuste rápido"))
        self.presets = QComboBox()
        for n, _ in PRESETS:
            self.presets.addItem(n)
        self.presets.activated.connect(self.apply_preset)
        top.addWidget(self.presets, 1)
        rst = QPushButton("↺ Restablecer todo")
        rst.clicked.connect(lambda: self.set_all({}))
        top.addWidget(rst)
        v.addLayout(top)

        self.rows, self.checks = {}, {}
        tabs = QTabWidget()
        v.addWidget(tabs, 1)

        def page(name):
            w = QWidget()
            g = QGridLayout(w)
            g.setColumnStretch(1, 1)
            g.setVerticalSpacing(10)
            tabs.addTab(w, name)
            return g

        g = page("Sonido")
        for i, (k, lab, lo, hi, tip) in enumerate((
                ("bass", "Graves", -15, 15, "Refuerza o reduce los graves (bajos)"),
                ("mid", "Medios", -15, 15, "Voces e instrumentos del centro"),
                ("treble", "Agudos", -15, 15, "Brillo y platillos"),
                ("volume", "Volumen", -20, 12, "Sube o baja el volumen de la canción"))):
            self.rows[k] = Row(g, i, lab, lo, hi, 0, 1, " dB", 0, tip)
        self.add_check(g, 4, "normalize", "Normalizar volumen (que suene parejo, estilo streaming)")
        g.setRowStretch(5, 1)

        g = page("Velocidad y tono")
        self.rows["tempo"] = Row(g, 0, "Tempo", 0.5, 2.0, 1.0, 100, "×", 2, "Cambia la velocidad SIN cambiar el tono")
        self.rows["pitch"] = Row(g, 1, "Tono", -12, 12, 0, 1, " st", 0, "Sube o baja el tono (semitonos) SIN cambiar la velocidad")
        self.rows["rate"] = Row(g, 2, "Velocidad (tasa)", 0.5, 2.0, 1.0, 100, "×", 2,
                                "Cambia velocidad y tono a la vez (como un disco de vinilo)")
        h = QLabel("Tempo = más rápida o lenta con el mismo tono · Tono = más aguda o grave a la misma velocidad · "
                   "Velocidad = las dos cosas juntas.")
        h.setWordWrap(True)
        h.setObjectName("hint")
        g.addWidget(h, 3, 0, 1, 3)
        g.setRowStretch(4, 1)

        g = page("Bucle y recorte")
        self.sp_a = QDoubleSpinBox()
        self.sp_b = QDoubleSpinBox()
        mx = max(self.dur, 0.0) or 99999
        for sp in (self.sp_a, self.sp_b):
            sp.setRange(0, mx)
            sp.setDecimals(1)
            sp.setSuffix(" s")
        self.sp_b.setSpecialValueText("hasta el final")
        self.sp_loops = QSpinBox()
        self.sp_loops.setRange(1, 20)
        self.sp_loops.setSuffix(" vez/veces")
        g.addWidget(QLabel("Empezar en"), 0, 0)
        g.addWidget(self.sp_a, 0, 1)
        g.addWidget(QLabel("Terminar en"), 1, 0)
        g.addWidget(self.sp_b, 1, 1)
        g.addWidget(QLabel("Repetir (bucle)"), 2, 0)
        g.addWidget(self.sp_loops, 2, 1)
        self.add_check(g, 3, "reverse", "Reproducir al revés")
        h = QLabel("El bucle repite el fragmento elegido (o la canción entera) las veces que indiques y lo guarda "
                   "como una sola pista.")
        h.setWordWrap(True)
        h.setObjectName("hint")
        g.addWidget(h, 4, 0, 1, 3)
        g.setRowStretch(5, 1)

        g = page("Efectos")
        self.rows["echo"] = Row(g, 0, "Eco", 0, 100, 0, 1, " %", 0)
        self.rows["reverb"] = Row(g, 1, "Reverberación", 0, 100, 0, 1, " %", 0, "Sensación de sala")
        self.rows["width"] = Row(g, 2, "Ancho estéreo", 0, 300, 100, 1, " %", 0, "0 = mono · 100 = normal · más = más amplio")
        self.rows["fade_in"] = Row(g, 3, "Entrada gradual", 0, 15, 0, 10, " s", 1)
        self.rows["fade_out"] = Row(g, 4, "Salida gradual", 0, 15, 0, 10, " s", 1)
        self.add_check(g, 5, "mono", "Convertir a mono")
        self.add_check(g, 6, "karaoke", "Quitar la voz (karaoke; funciona mejor en grabaciones estéreo)")
        g.setRowStretch(7, 1)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.bar)
        v.addWidget(self.status)

        pr = QHBoxLayout()
        self.btn_prev = QPushButton("▶ Escuchar 30 s")
        self.btn_prev.setToolTip("Genera una muestra con los ajustes y la reproduce, para que oigas el resultado")
        self.btn_prev.clicked.connect(self.preview)
        self.btn_pstop = QPushButton("⏹ Parar")
        self.btn_pstop.clicked.connect(self.stop_preview)
        self.btn_pstop.setEnabled(False)
        pr.addWidget(self.btn_prev)
        pr.addWidget(self.btn_pstop)
        pr.addStretch(1)
        v.addLayout(pr)
        br = QHBoxLayout()
        self.btn_new = QPushButton("💾 Guardar como canción nueva")
        self.btn_new.setObjectName("accent")
        self.btn_new.setToolTip("Crea un archivo nuevo «… (editada)» y deja el original intacto")
        self.btn_new.clicked.connect(lambda: self.save(False))
        self.btn_rep = QPushButton("Reemplazar la original")
        self.btn_rep.setToolTip("Sustituye el archivo original por la versión con los ajustes (no se puede deshacer)")
        self.btn_rep.clicked.connect(lambda: self.save(True))
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.btn_new)
        br.addWidget(self.btn_rep)
        br.addWidget(close)
        v.addLayout(br)

    # ------------------------------------------------------------ valores
    def add_check(self, grid, r, key, text):
        c = QCheckBox(text)
        self.checks[key] = c
        grid.addWidget(c, r, 0, 1, 3)

    def params(self):
        p = {k: r.value() for k, r in self.rows.items()}
        for k in ("bass", "mid", "treble", "volume", "pitch", "echo", "reverb", "width"):
            p[k] = int(round(p[k]))
        p.update({k: c.isChecked() for k, c in self.checks.items()})
        p.update(trim_start=self.sp_a.value(), trim_end=self.sp_b.value() if self.sp_b.value() > 0 else 0.0,
                 loops=self.sp_loops.value())
        return p

    def set_all(self, vals):
        q = dict(DEFAULTS)
        q.update(vals)
        for k, r in self.rows.items():
            r.set(q[k])
        for k, c in self.checks.items():
            c.setChecked(bool(q[k]))
        self.sp_a.setValue(q["trim_start"])
        self.sp_b.setValue(q["trim_end"])
        self.sp_loops.setValue(q["loops"])

    def apply_preset(self, i):
        self.set_all(PRESETS[i][1])

    # ------------------------------------------------------------ muestra
    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def set_busy(self, on):
        for b in (self.btn_prev, self.btn_new, self.btn_rep):
            b.setEnabled(not on)
        self.bar.setVisible(on)
        if on:
            self.bar.setValue(0)

    def preview(self):
        if self.busy():
            return
        if not HAS_AUDIO:
            self.status.setText("Este equipo no tiene reproductor integrado para la muestra.")
            return
        self.stop_preview()
        fd, self.tmp = tempfile.mkstemp(prefix="mmfx_", suffix=".wav")
        os.close(fd)
        n = 30
        cmd = build_cmd(self.path, self.tmp, self.params(), self.sr, self.dur, preview=n, offset=self.offset)
        self.status.setText("Preparando la muestra…")
        self.set_busy(True)
        self.worker = FxWorker(cmd, self.tmp, n)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.ok.connect(self.on_preview)
        self.worker.fail.connect(self.on_fail)
        self.worker.start()

    def on_preview(self, wav):
        self.set_busy(False)
        if self.pplayer is None:
            self.pplayer = QMediaPlayer()
            self.paudio = QAudioOutput()
            self.pplayer.setAudioOutput(self.paudio)
            self.paudio.setVolume(0.8)
            self.pplayer.playbackStateChanged.connect(
                lambda st: self.btn_pstop.setEnabled(st == QMediaPlayer.PlaybackState.PlayingState))
        if self.release:
            self.release(None)   # pausa el reproductor principal para no mezclar sonidos
        self.pplayer.setSource(QUrl.fromLocalFile(wav))
        self.pplayer.play()
        self.status.setText("Reproduciendo la muestra. Puedes mover los ajustes y volver a pulsar «Escuchar».")

    def stop_preview(self):
        if self.pplayer is not None:
            self.pplayer.stop()
            self.pplayer.setSource(QUrl())
        if self.tmp and os.path.exists(self.tmp):
            try:
                os.remove(self.tmp)
            except OSError:
                pass
        self.tmp = None

    # ------------------------------------------------------------ guardar
    def save(self, replace):
        if self.busy():
            return
        p = self.params()
        if is_default(p):
            self.status.setText("No has cambiado nada todavía.")
            return
        if replace:
            if QMessageBox.question(self, "Reemplazar la original",
                                    "Se sustituirá el archivo original por la versión con los ajustes.\n"
                                    "No se puede deshacer. ¿Continuar?") != QMessageBox.StandardButton.Yes:
                return
        self.stop_preview()
        ext = os.path.splitext(self.path)[1].lower()
        folder = os.path.dirname(self.path)
        if replace:
            self.dst = os.path.join(folder, f".mmfx_tmp{ext if ext in CODECS else '.mp3'}")
        else:
            self.dst = unique_name(self.path if ext in CODECS else os.path.splitext(self.path)[0] + ".mp3")
        self.replace = replace
        self.cur_dst = self.dst
        _, out = build_filters(p, self.sr, self.dur)
        cmd = build_cmd(self.path, self.dst, p, self.sr, self.dur)
        self.status.setText("Aplicando los ajustes… (según la duración puede tardar un momento)")
        self.set_busy(True)
        self.worker = FxWorker(cmd, self.dst, out or self.dur or 60)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.ok.connect(self.on_saved_ok)
        self.worker.fail.connect(self.on_fail)
        self.worker.start()

    def on_saved_ok(self, dst):
        self.cur_dst = None
        final = dst
        if self.replace:
            try:
                if self.release:
                    self.release(self.path)   # libera el archivo si se estaba reproduciendo
                final = self.path if os.path.splitext(dst)[1].lower() == os.path.splitext(self.path)[1].lower() \
                    else os.path.splitext(self.path)[0] + os.path.splitext(dst)[1]
                os.replace(dst, final)
                if final != self.path and os.path.exists(self.path):
                    os.remove(self.path)
            except OSError as e:
                self.set_busy(False)
                self.status.setText(f"No se pudo reemplazar el archivo: {e}. La versión nueva quedó en {dst}")
                return
        self.set_busy(False)
        self.status.setText(("✔ Original reemplazada: " if self.replace else "✔ Guardada como canción nueva: ")
                            + os.path.basename(final))
        if self.on_saved:
            self.on_saved(final, self.replace)

    def on_fail(self, msg):
        self.set_busy(False)
        bad = self.cur_dst
        self.cur_dst = None
        if bad and os.path.exists(bad):   # resto a medias de un guardado fallido
            try:
                os.remove(bad)
            except OSError:
                pass
        if msg != "cancelado":
            self.status.setText("No se pudo aplicar: " + msg)

    def closeEvent(self, e):
        if self.busy():
            self.worker.cancel()
            self.worker.wait(3000)
        self.stop_preview()
        super().closeEvent(e)

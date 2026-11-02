"""Convertir canciones a otros formatos (MP3, FLAC, M4A, OGG, Opus, WAV) con ffmpeg."""
import os, subprocess
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton,
                             QProgressBar, QFileDialog, QRadioButton, QPlainTextEdit, QFormLayout)
from spectro import ffmpeg_exe, _run

# nombre -> (extensión, calidades, calidad por defecto, lleva portada)
FORMATS = {
    "MP3": (".mp3", [128, 192, 256, 320], 256, True),
    "FLAC (sin pérdida)": (".flac", [], 0, True),
    "M4A (AAC)": (".m4a", [128, 192, 256, 320], 256, True),
    "OGG (Vorbis)": (".ogg", [96, 128, 192, 256, 320], 192, False),
    "Opus": (".opus", [64, 96, 128, 160, 192], 128, False),
    "WAV (sin pérdida)": (".wav", [], 0, False),
}


def build_cmd(exe, src, dst, fmt, kbps):
    ext, _, _, cover = FORMATS[fmt]
    cmd = [exe, "-nostdin", "-y", "-v", "error", "-i", src, "-map", "0:a:0", "-map_metadata", "0"]
    if cover:
        cmd += ["-map", "0:v:0?", "-c:v", "copy", "-disposition:v:0", "attached_pic"]
    else:
        cmd += ["-vn"]
    if ext == ".mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{kbps}k", "-id3v2_version", "3"]
    elif ext == ".flac":
        cmd += ["-c:a", "flac"]
    elif ext == ".m4a":
        cmd += ["-c:a", "aac", "-b:a", f"{kbps}k", "-movflags", "use_metadata_tags"]
    elif ext == ".ogg":
        cmd += ["-c:a", "libvorbis", "-b:a", f"{kbps}k"]
    elif ext == ".opus":
        cmd += ["-c:a", "libopus", "-b:a", f"{kbps}k"]
    else:
        cmd += ["-c:a", "pcm_s16le"]
    return cmd + [dst]


def free_name(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


class ConvWorker(QThread):
    step = pyqtSignal(int, str, bool, str)

    def __init__(self, paths, fmt, kbps, outdir):
        super().__init__()
        self.paths, self.fmt, self.kbps, self.outdir = paths, fmt, kbps, outdir
        self._stop = False

    def run(self):
        exe = ffmpeg_exe()
        ext = FORMATS[self.fmt][0]
        for i, src in enumerate(self.paths):
            if self._stop:
                return
            name = os.path.basename(src)
            if not exe:
                self.step.emit(i, name, False, "No se encontró ffmpeg (instala imageio-ffmpeg).")
                continue
            folder = self.outdir or os.path.dirname(src)
            dst = os.path.join(folder, os.path.splitext(name)[0] + ext)
            if os.path.normcase(os.path.abspath(dst)) == os.path.normcase(os.path.abspath(src)):
                dst = os.path.join(folder, os.path.splitext(name)[0] + " (convertido)" + ext)
            dst = free_name(dst)
            try:
                p = _run(build_cmd(exe, src, dst, self.fmt, self.kbps), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if p.returncode != 0:
                    if os.path.exists(dst):
                        os.remove(dst)
                    self.step.emit(i, name, False, p.stderr.decode("utf-8", "ignore").strip()[-160:] or "Error")
                else:
                    self.step.emit(i, name, True, os.path.basename(dst))
            except Exception as e:
                self.step.emit(i, name, False, str(e))


class ConvertDialog(QDialog):
    def __init__(self, paths, parent=None, on_done=None):
        super().__init__(parent)
        self.setWindowTitle("🔄 Convertir formato")
        self.resize(520, 480)
        self.paths, self.on_done, self.outdir, self.worker = paths, on_done, None, None
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{len(paths)}</b> canción(es) seleccionada(s)"))
        f = QFormLayout()
        self.fmt = QComboBox()
        self.fmt.addItems(list(FORMATS))
        self.fmt.currentTextChanged.connect(self.on_fmt)
        self.q = QComboBox()
        f.addRow("Formato de salida", self.fmt)
        f.addRow("Calidad", self.q)
        v.addLayout(f)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setObjectName("hint")
        v.addWidget(self.note)
        self.r_same = QRadioButton("Guardar junto a los originales")
        self.r_same.setChecked(True)
        self.r_other = QRadioButton("Guardar en otra carpeta…")
        self.r_other.clicked.connect(self.pick_dir)
        v.addWidget(self.r_same)
        v.addWidget(self.r_other)
        self.bar = QProgressBar()
        self.bar.setRange(0, len(paths))
        v.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        v.addWidget(self.log, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.go = QPushButton("▶ Convertir")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.start)
        self.close_btn = QPushButton("Cerrar")
        self.close_btn.clicked.connect(self.close)
        row.addWidget(self.go)
        row.addWidget(self.close_btn)
        v.addLayout(row)
        self.on_fmt(self.fmt.currentText())

    def on_fmt(self, name):
        ext, quals, default, cover = FORMATS[name]
        self.q.clear()
        if quals:
            for k in quals:
                self.q.addItem(f"{k} kbps", k)
            self.q.setCurrentIndex(quals.index(default))
            self.q.setEnabled(True)
        else:
            self.q.addItem("Sin pérdida", 0)
            self.q.setEnabled(False)
        txt = "Se conservan las etiquetas" + (" y la portada." if cover else ". Este formato no guarda portada.")
        if ext in (".flac", ".wav"):
            txt += " Convertir desde MP3/AAC a un formato sin pérdida no mejora la calidad."
        self.note.setText(txt)

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de destino")
        if d:
            self.outdir = d
            self.r_other.setText(f"Guardar en: {d}")
        else:
            self.outdir = None
            self.r_same.setChecked(True)

    def start(self):
        self.go.setEnabled(False)
        self.fmt.setEnabled(False)
        self.q.setEnabled(False)
        self.ok = 0
        self.done_n = 0
        self.worker = ConvWorker(self.paths, self.fmt.currentText(), int(self.q.currentData() or 0),
                                 self.outdir if self.r_other.isChecked() else None)
        self.worker.step.connect(self.on_step)
        self.worker.start()

    def on_step(self, i, name, ok, msg):
        self.done_n += 1
        self.ok += 1 if ok else 0
        self.bar.setValue(self.done_n)
        self.log.appendPlainText(("✔ " if ok else "✘ ") + f"{name}  →  {msg}")
        if self.done_n >= len(self.paths):
            self.log.appendPlainText(f"\nListo: {self.ok} de {len(self.paths)} convertida(s).")
            self.go.setEnabled(True)
            self.fmt.setEnabled(True)
            self.on_fmt(self.fmt.currentText())
            if self.on_done:
                self.on_done()

    def closeEvent(self, e):
        if self.worker and self.worker.isRunning():
            self.worker._stop = True
            self.worker.wait(5000)
        super().closeEvent(e)

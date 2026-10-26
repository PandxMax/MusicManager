"""Descargar el audio de un vídeo de YouTube como MP3 (con yt-dlp + ffmpeg)."""
import os
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QPushButton,
                             QComboBox, QProgressBar, QPlainTextEdit, QFileDialog)
from spectro import ffmpeg_exe


class DlWorker(QThread):
    progress = pyqtSignal(int, str)
    log = pyqtSignal(str)
    done = pyqtSignal(list)
    fail = pyqtSignal(str)

    def __init__(self, url, outdir, kbps):
        super().__init__()
        self.url, self.outdir, self.kbps = url, outdir, kbps

    def run(self):
        try:
            import yt_dlp
        except ImportError:
            self.fail.emit("Falta el componente yt-dlp (reinstala el programa o actualízalo).")
            return
        worker = self

        class Lg:
            def debug(self, m):
                pass

            def info(self, m):
                pass

            def warning(self, m):
                pass

            def error(self, m):
                worker.log.emit(str(m))

        def hook(d):
            if d.get("status") == "downloading":
                tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                pct = int(d.get("downloaded_bytes", 0) * 100 / tot) if tot else 0
                self.progress.emit(min(pct, 99), f"Descargando… {pct}%")
            elif d.get("status") == "finished":
                self.progress.emit(99, "Convirtiendo a MP3…")

        before = set(os.listdir(self.outdir)) if os.path.isdir(self.outdir) else set()
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(self.outdir, "%(title)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "logger": Lg(),
            "progress_hooks": [hook],
            "windowsfilenames": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(self.kbps)},
                {"key": "FFmpegMetadata", "add_metadata": True},
            ],
        }
        ff = ffmpeg_exe()
        if ff:
            opts["ffmpeg_location"] = ff
        try:
            with yt_dlp.YoutubeDL(opts) as y:
                y.download([self.url])
        except Exception as e:
            self.fail.emit(str(e))
            return
        after = set(os.listdir(self.outdir))
        new = sorted(os.path.join(self.outdir, f) for f in after - before if f.lower().endswith(".mp3"))
        self.done.emit(new)


class YoutubeDialog(QDialog):
    def __init__(self, outdir, parent=None, on_done=None):
        super().__init__(parent)
        self.setWindowTitle("⬇ Descargar de YouTube a MP3")
        self.resize(560, 420)
        self.on_done, self.worker = on_done, None
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Pega el enlace del vídeo. Descarga solo música o contenido que tengas derecho a guardar "
                           "(tuyo, con licencia libre o con permiso). Eres responsable del uso que le des."))
        v.itemAt(0).widget().setWordWrap(True)
        f = QFormLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.dir = QLineEdit(outdir)
        pick = QPushButton("📂")
        pick.setFixedWidth(40)
        pick.clicked.connect(self.pick_dir)
        row = QHBoxLayout()
        row.addWidget(self.dir, 1)
        row.addWidget(pick)
        self.q = QComboBox()
        for k in ("320", "256", "192", "128"):
            self.q.addItem(f"{k} kbps", int(k))
        f.addRow("Enlace", self.url)
        f.addRow("Guardar en", row)
        f.addRow("Calidad MP3", self.q)
        v.addLayout(f)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.status = QLabel("")
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        v.addWidget(self.bar)
        v.addWidget(self.status)
        v.addWidget(self.logbox, 1)
        br = QHBoxLayout()
        self.go = QPushButton("⬇ Descargar MP3")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.start)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.go)
        br.addWidget(close)
        v.addLayout(br)

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Carpeta de destino", self.dir.text())
        if d:
            self.dir.setText(d)

    def start(self):
        url, out = self.url.text().strip(), self.dir.text().strip()
        if not url.lower().startswith("http"):
            self.status.setText("Pega un enlace válido (empieza con https://).")
            return
        if not out or not os.path.isdir(out):
            self.status.setText("Elige una carpeta de destino que exista.")
            return
        self.go.setEnabled(False)
        self.bar.setValue(0)
        self.logbox.clear()
        self.status.setText("Empezando…")
        self.worker = DlWorker(url, out, self.q.currentData())
        self.worker.progress.connect(lambda p, t: (self.bar.setValue(p), self.status.setText(t)))
        self.worker.log.connect(self.logbox.appendPlainText)
        self.worker.fail.connect(self.on_fail)
        self.worker.done.connect(self.on_ok)
        self.worker.start()

    def on_fail(self, msg):
        self.go.setEnabled(True)
        self.status.setText("No se pudo descargar.")
        self.logbox.appendPlainText(msg)

    def on_ok(self, files):
        self.go.setEnabled(True)
        self.bar.setValue(100)
        if not files:
            self.status.setText("Terminó, pero no encuentro el MP3 nuevo (quizá ya existía).")
        else:
            self.status.setText(f"✔ Listo: {os.path.basename(files[0])}. Se seleccionó en la lista para que le pongas metadatos y portada.")
        if self.on_done:
            self.on_done(self.dir.text().strip(), files)

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(2000)
        super().closeEvent(e)

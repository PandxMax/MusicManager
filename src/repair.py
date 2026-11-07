"""Reparar recortes (clipping): reconstruye los picos «aplastados» de la onda con el filtro adeclip de ffmpeg.
Conserva las etiquetas y la portada. Se puede guardar como copia o reemplazar el original."""
import os, sys, subprocess
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton, QProgressBar,
                             QListWidget, QMessageBox)
from i18n import tr as T

CODECS = {
    ".mp3": ["-c:a", "libmp3lame", "-b:a", "320k", "-id3v2_version", "3"],
    ".flac": ["-c:a", "flac"],
    ".m4a": ["-c:a", "aac", "-b:a", "256k"],
    ".ogg": ["-c:a", "libvorbis", "-q:a", "8"],
    ".opus": ["-c:a", "libopus", "-b:a", "192k"],
    ".wav": ["-c:a", "pcm_s16le"],
}
WITH_COVER = {".mp3", ".flac", ".m4a"}
LOSSY = {".mp3", ".m4a", ".ogg", ".opus", ".aac", ".wma"}


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        return shutil.which("ffmpeg")


def build_cmd(src, dst):
    ext = os.path.splitext(dst)[1].lower()
    cmd = [ffmpeg_exe() or "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-nostdin", "-i", src,
           "-map", "0:a:0"]
    if ext in WITH_COVER:
        cmd += ["-map", "0:v?", "-c:v", "copy", "-disposition:v", "attached_pic"]
    cmd += ["-map_metadata", "0", "-af", "adeclip"] + CODECS.get(ext, CODECS[".flac"]) + [dst]
    return cmd


class RepairWorker(QThread):
    step = pyqtSignal(int, str, str)   # índice, ruta resultante, error
    done = pyqtSignal()

    def __init__(self, jobs):
        super().__init__()
        self.jobs, self.stop = jobs, False   # [(origen, destino, reemplazar)]

    def run(self):
        flags = 0x08000000 if sys.platform == "win32" else 0
        for i, (src, dst, replace) in enumerate(self.jobs):
            if self.stop:
                break
            out = dst
            if replace:   # se escribe al lado y luego se cambia por el original
                b, e = os.path.splitext(src)
                out = b + ".reparando" + e
            try:
                r = subprocess.run(build_cmd(src, out), capture_output=True, creationflags=flags, timeout=1800)
                if r.returncode != 0 or not os.path.exists(out):
                    raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[-300:] or T("ffmpeg falló"))
                if replace:
                    os.replace(out, src)
                    out = src
                self.step.emit(i, out, "")
            except Exception as e:
                try:
                    if replace and os.path.exists(out):
                        os.remove(out)
                except OSError:
                    pass
                self.step.emit(i, "", str(e))
        self.done.emit()


class RepairDialog(QDialog):
    def __init__(self, main, paths):
        super().__init__(main)
        self.main, self.paths, self.worker = main, list(paths), None
        self.setWindowTitle(T("Reparar recortes (clipping)"))
        self.resize(600, 520)
        v = QVBoxLayout(self)
        info = QLabel(T("Reconstruye los golpes fuertes que quedaron «aplastados» (recortes o clipping) y suenan "
                        "ásperos o distorsionados. Se conservan las etiquetas y la portada. Si una canción no tiene "
                        "recortes, queda prácticamente igual."))
        info.setObjectName("dlgsub")
        info.setWordWrap(True)
        v.addWidget(info)
        self.lst = QListWidget()
        for p in self.paths:
            self.lst.addItem(os.path.basename(p))
        v.addWidget(self.lst, 1)
        self.r_copy = QRadioButton(T("Guardar como copia («… (reparada)») junto al original"))
        self.r_copy.setChecked(True)
        self.r_repl = QRadioButton(T("Reemplazar el original"))
        v.addWidget(self.r_copy)
        v.addWidget(self.r_repl)
        lossy = sum(1 for p in self.paths if os.path.splitext(p)[1].lower() in LOSSY)
        if lossy:
            n = QLabel(T(f"{lossy} son MP3/AAC/OGG: al guardarlas se vuelven a comprimir en alta calidad (MP3 320 kbps, "
                         f"AAC 256 kbps…). La diferencia no se nota, pero por eso conviene guardar como copia."))
            n.setObjectName("dlgsub")
            n.setWordWrap(True)
            v.addWidget(n)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        br.addStretch(1)
        self.go = QPushButton(T("🩹 Reparar"))
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.start)
        self.close_btn = QPushButton(T("Cerrar"))
        self.close_btn.clicked.connect(self.close)
        br.addWidget(self.go)
        br.addWidget(self.close_btn)
        v.addLayout(br)

    def start(self):
        if not ffmpeg_exe():
            QMessageBox.warning(self, self.windowTitle(), T("No se encontró ffmpeg."))
            return
        replace = self.r_repl.isChecked()
        jobs = []
        for p in self.paths:
            if replace:
                jobs.append((p, p, True))
            else:
                b, e = os.path.splitext(p)
                dst, n = f"{b} (reparada){e}", 2
                while os.path.exists(dst):
                    dst, n = f"{b} (reparada {n}){e}", n + 1
                jobs.append((p, dst, False))
        if replace:
            if QMessageBox.question(self, self.windowTitle(),
                                    T(f"¿Reemplazar {len(jobs)} canción(es) por su versión reparada? No se puede deshacer.")) \
                    != QMessageBox.StandardButton.Yes:
                return
            self.main.release_if([p for p, _, _ in jobs])
        self.ok = 0
        self.go.setEnabled(False)
        self.bar.setRange(0, len(jobs))
        self.bar.setValue(0)
        self.bar.show()
        self.status.setText(T("Reparando…"))
        self.worker = RepairWorker(jobs)
        self.worker.step.connect(self.on_step)
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_step(self, i, out, err):
        self.bar.setValue(i + 1)
        it = self.lst.item(i)
        if err:
            it.setText("❌ " + os.path.basename(self.paths[i]) + "  —  " + err[:120])
        else:
            self.ok += 1
            it.setText("✔ " + os.path.basename(out))

    def on_done(self):
        self.bar.hide()
        self.go.setEnabled(True)
        self.status.setText(T(f"Listo: {self.ok} de {len(self.paths)} canción(es) reparada(s)."))
        try:
            self.main.after_fs_change()
        except Exception:
            pass

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop = True
            self.worker.wait(60000)
        super().closeEvent(e)

"""Mejorar la calidad de una portada con IA (Real-ESRGAN, funciona en tu PC, sin internet ni claves).
El motor (unos 45 MB) se descarga solo la primera vez que se usa."""
import os, sys, hashlib, zipfile, tempfile, subprocess, urllib.request, shutil
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStandardPaths, QByteArray, QBuffer, QIODevice
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QProgressBar,
                             QCheckBox, QFrame, QSizePolicy)
from i18n import tr as T

ESR_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
ESR_SHA256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d"
EXE = "realesrgan-ncnn-vulkan.exe"
MODELS = [("Anime / ilustración", "realesrgan-x4plus-anime"), ("General / foto", "realesrgan-x4plus")]
SIZES = [1000, 1200, 1500, 2000]


def engine_dir():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) or \
        os.path.join(os.path.expanduser("~"), ".musicmanager")
    return os.path.join(base, "realesrgan")


def engine_exe():
    p = os.path.join(engine_dir(), EXE)
    return p if os.path.isfile(p) else None


def img_bytes(img, fmt="JPG", q=95):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, fmt, q)
    return bytes(ba)


class DownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(bool, str)

    def run(self):
        d = engine_dir()
        tmp = None
        try:
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            req = urllib.request.Request(ESR_URL, headers={"User-Agent": "MusicManager"})
            h = hashlib.sha256()
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    if self.isInterruptionRequested():
                        raise RuntimeError(T("cancelado"))
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
            if h.hexdigest() != ESR_SHA256:
                raise RuntimeError(T("El archivo descargado no es el esperado (no se instaló por seguridad)."))
            with zipfile.ZipFile(tmp) as z:
                for name in z.namelist():   # solo el programa, sus librerías y los modelos (no las demos)
                    low = name.lower()
                    if name.endswith("/") or not (low.endswith((".exe", ".dll")) or low.startswith("models/")):
                        continue
                    dest = os.path.join(d, *name.split("/"))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with z.open(name) as src, open(dest, "wb") as fh:
                        shutil.copyfileobj(src, fh)
            self.done.emit(True, "")
        except Exception as e:
            self.done.emit(False, str(e))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


class UpscaleWorker(QThread):
    done = pyqtSignal(object, str)   # QImage o None, mensaje

    def __init__(self, data, model, side):
        super().__init__()
        self.data, self.model, self.side = data, model, side

    def run(self):
        exe = engine_exe()
        work = tempfile.mkdtemp(prefix="mmup_")
        try:
            src = QImage.fromData(self.data)
            if src.isNull():
                raise RuntimeError(T("No se pudo leer esa imagen."))
            if src.hasAlphaChannel():
                src = src.convertToFormat(QImage.Format.Format_RGB888)
            inp, outp = os.path.join(work, "in.png"), os.path.join(work, "out.png")
            src.save(inp, "PNG")
            flags = 0x08000000 if sys.platform == "win32" else 0
            r = subprocess.run([exe, "-i", inp, "-o", outp, "-n", self.model, "-s", "4", "-f", "png"],
                               cwd=os.path.dirname(exe), capture_output=True, text=True, errors="replace",
                               creationflags=flags, timeout=600)
            big = QImage(outp) if os.path.exists(outp) else QImage()
            if r.returncode != 0 or big.isNull():
                tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or [""]
                raise RuntimeError(T("La IA no pudo procesar la imagen (¿tu tarjeta gráfica no tiene Vulkan?).") + " " + tail[0])
            if max(big.width(), big.height()) > self.side:   # tamaño final pedido
                big = big.scaled(self.side, self.side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.done.emit(big, "")
        except Exception as e:
            self.done.emit(None, str(e))
        finally:
            shutil.rmtree(work, ignore_errors=True)


class Preview(QLabel):
    def __init__(self, title):
        super().__init__()
        self.setFixedSize(300, 300)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("cover")
        self.setText(title)

    def show_img(self, img):
        if img is None or img.isNull():
            return
        self.setPixmap(QPixmap.fromImage(img).scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                                      Qt.TransformationMode.SmoothTransformation))


class UpscaleDialog(QDialog):
    """Antes / después lado a lado; «Usar esta portada» la deja pendiente de guardar (en naranja)."""
    def __init__(self, main, paths, data):
        super().__init__(main)
        self.main, self.paths, self.data = main, list(paths), data
        self.result, self.worker, self.dl = None, None, None
        self.setWindowTitle("Mejorar calidad de la portada con IA")
        self.resize(700, 560)
        v = QVBoxLayout(self)
        src = QImage.fromData(data)
        self.src_size = (src.width(), src.height())
        info = QLabel("La IA reconstruye la nitidez y agranda la portada. Funciona en tu PC, sin internet. "
                      "Puede deformar textos pequeños: compara antes de usarla.")
        info.setWordWrap(True)
        v.addWidget(info)
        row = QHBoxLayout()
        self.before, self.after = Preview(T("Antes")), Preview(T("Después"))
        self.before.show_img(src)
        cb, ca = QVBoxLayout(), QVBoxLayout()
        self.lb_before = QLabel(f"{T('Antes')}: {src.width()}×{src.height()} px")
        self.lb_after = QLabel(T("Después") + ": —")
        for lay, w, lb in ((cb, self.before, self.lb_before), (ca, self.after, self.lb_after)):
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(w)
            lay.addWidget(lb)
        row.addLayout(cb)
        row.addLayout(ca)
        v.addLayout(row)
        opts = QHBoxLayout()
        opts.addWidget(QLabel("Estilo"))
        self.model = QComboBox()
        for name, key in MODELS:
            self.model.addItem(name, key)
        opts.addWidget(self.model, 1)
        opts.addWidget(QLabel("Tamaño final"))
        self.size = QComboBox()
        for s in SIZES:
            self.size.addItem(f"{s} px", s)
        self.size.setCurrentIndex(1)
        opts.addWidget(self.size)
        v.addLayout(opts)
        self.all_sel = QCheckBox(T(f"Usarla en las {len(self.paths)} canciones seleccionadas"))
        self.all_sel.setChecked(True)
        self.all_sel.setVisible(len(self.paths) > 1)
        v.addWidget(self.all_sel)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        self.go = QPushButton("✨ Mejorar")
        self.go.clicked.connect(self.start)
        self.use = QPushButton("✔ Usar esta portada")
        self.use.setObjectName("accent")
        self.use.setEnabled(False)
        self.use.clicked.connect(self.apply)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.go)
        br.addWidget(self.use)
        br.addWidget(close)
        v.addLayout(br)
        if not engine_exe():
            self.status.setText(T("La primera vez se descarga el motor de IA (unos 45 MB). Después funciona sin internet."))

    def busy(self, on):
        self.go.setEnabled(not on)
        self.model.setEnabled(not on)
        self.size.setEnabled(not on)

    def start(self):
        if not engine_exe():
            self.download()
            return
        self.busy(True)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText(T("Mejorando la portada… (unos segundos; sin tarjeta gráfica puede tardar más)"))
        self.worker = UpscaleWorker(self.data, self.model.currentData(), self.size.currentData())
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def download(self):
        self.busy(True)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.show()
        self.status.setText(T("Descargando el motor de IA (solo esta vez)…"))
        self.dl = DownloadWorker()
        self.dl.progress.connect(lambda got, tot: (self.bar.setValue(int(got * 100 / tot)) if tot else None,
                                                   self.status.setText(T(f"Descargando el motor de IA (solo esta vez)… {got // 1048576} MB"))))
        self.dl.done.connect(self.on_downloaded)
        self.dl.start()

    def on_downloaded(self, ok, err):
        self.bar.hide()
        self.busy(False)
        if not ok:
            self.status.setText(T("No se pudo descargar el motor de IA: ") + err)
            return
        self.start()

    def on_done(self, img, err):
        self.bar.hide()
        self.busy(False)
        if img is None:
            self.status.setText(err)
            return
        self.result = img
        self.after.show_img(img)
        self.lb_after.setText(f"{T('Después')}: {img.width()}×{img.height()} px")
        self.use.setEnabled(True)
        self.status.setText(T("Listo. Compara y pulsa «Usar esta portada» si te gusta."))

    def apply(self):
        if self.result is None:
            return
        data = img_bytes(self.result, "JPG", 95)
        targets = self.paths if self.all_sel.isChecked() else self.paths[:1]
        self.main.apply_cover_bytes(targets, data)
        self.accept()

    def closeEvent(self, e):
        for w in (self.worker, self.dl):
            if w is not None and w.isRunning():
                w.requestInterruption()
                w.wait(2000)
        super().closeEvent(e)

"""Herramientas de biblioteca: organizar en carpetas, etiquetas desde el nombre del archivo,
normalizar el volumen e informe de la biblioteca."""
import os, re, sys, shutil, subprocess
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QMessageBox, QLineEdit,
                             QListWidget, QListWidgetItem, QSplitter, QApplication)
from i18n import tr as T

BAD_CHARS = r'<>:"/\|?*'


def safe_name(t, fallback):
    t = "".join("_" if c in BAD_CHARS or ord(c) < 32 else c for c in (t or "")).strip().rstrip(". ")
    return t[:120] or T(fallback)


def list_audio(folder, recursive, audio_ext):
    out = []
    if recursive:
        for dp, _, fs in os.walk(folder):
            out += [os.path.join(dp, f) for f in fs if os.path.splitext(f)[1].lower() in audio_ext]
    else:
        try:
            out = [os.path.join(folder, f) for f in os.listdir(folder) if os.path.splitext(f)[1].lower() in audio_ext]
        except OSError:
            pass
    return sorted(f for f in out if os.path.isfile(f))


def _table(headers):
    tb = QTableWidget(0, len(headers))
    tb.setHorizontalHeaderLabels(headers)
    tb.verticalHeader().setVisible(False)
    tb.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    tb.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    tb.setAlternatingRowColors(True)
    for c in range(len(headers)):
        tb.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
    return tb


# =========================================================== 1. Organizar en carpetas
PATTERNS = [
    ("Artista / Álbum", ["artist", "album"]),
    ("Artista / Año - Álbum", ["artist", "year_album"]),
    ("Artista", ["artist"]),
    ("Género / Artista", ["genre", "artist"]),
    ("Género / Artista / Álbum", ["genre", "artist", "album"]),
]


class OrganizeDialog(QDialog):
    def __init__(self, main, folder, audio_ext):
        super().__init__(main)
        self.main, self.folder, self.audio_ext = main, folder, audio_ext
        self.setWindowTitle("Organizar en carpetas")
        self.resize(900, 560)
        v = QVBoxLayout(self)
        info = QLabel("Mueve las canciones a carpetas según sus etiquetas, por ejemplo «Bad Bunny / Un Verano Sin Ti». "
                      "Usa el «Intérprete del álbum» si lo tiene (así los álbumes con invitados no se separan). "
                      "Primero ves la vista previa; no se mueve nada hasta que pulses «Organizar».")
        info.setWordWrap(True)
        v.addWidget(info)
        row = QHBoxLayout()
        row.addWidget(QLabel("Estructura"))
        self.pat = QComboBox()
        for name, _ in PATTERNS:
            self.pat.addItem(name)
        row.addWidget(self.pat, 1)
        self.rec = QCheckBox("Incluir subcarpetas")
        self.rec.setChecked(True)
        self.clean = QCheckBox("Borrar las carpetas que queden vacías")
        self.clean.setChecked(True)
        row.addWidget(self.rec)
        row.addWidget(self.clean)
        v.addLayout(row)
        self.where = QLabel(folder)
        self.where.setObjectName("hint")
        v.addWidget(self.where)
        self.tb = _table([T("Canción"), T("Ahora en"), T("Irá a")])
        v.addWidget(self.tb, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        self.go = QPushButton("🗂 Organizar")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.run)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.go)
        br.addWidget(close)
        v.addLayout(br)
        self.pat.currentIndexChanged.connect(self.preview)
        self.rec.toggled.connect(self.preview)
        self.plan = []
        self.preview()

    def target(self, p):
        val = self.main.val
        artist = val(p, "albumartist") or val(p, "artist")
        parts = []
        for key in PATTERNS[self.pat.currentIndex()][1]:
            if key == "artist":
                parts.append(safe_name(artist, "Artista desconocido"))
            elif key == "album":
                parts.append(safe_name(val(p, "album"), "Sin álbum"))
            elif key == "genre":
                parts.append(safe_name(val(p, "genre"), "Sin género"))
            elif key == "year_album":
                y = (val(p, "date") or "")[:4]
                alb = safe_name(val(p, "album"), "Sin álbum")
                parts.append(f"{y} - {alb}" if y.isdigit() else alb)
        return os.path.join(self.folder, *parts)

    def preview(self):
        files = list_audio(self.folder, self.rec.isChecked(), self.audio_ext)
        self.plan, taken = [], set()
        self.tb.setRowCount(0)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for p in files:
                dst_dir = self.target(p)
                if os.path.normcase(os.path.normpath(dst_dir)) == os.path.normcase(os.path.dirname(os.path.normpath(p))):
                    continue
                name = os.path.basename(p)
                base, ext = os.path.splitext(name)
                dst, n = os.path.join(dst_dir, name), 2
                while os.path.exists(dst) or os.path.normcase(dst) in taken:
                    dst = os.path.join(dst_dir, f"{base} ({n}){ext}")
                    n += 1
                taken.add(os.path.normcase(dst))
                self.plan.append((p, dst))
                r = self.tb.rowCount()
                self.tb.insertRow(r)
                for c, txt in enumerate((name, os.path.relpath(os.path.dirname(p), self.folder),
                                         os.path.relpath(dst_dir, self.folder))):
                    self.tb.setItem(r, c, QTableWidgetItem(txt))
        finally:
            QApplication.restoreOverrideCursor()
        self.go.setEnabled(bool(self.plan))
        self.status.setText(T(f"{len(self.plan)} canción(es) se moverán.") if self.plan
                            else T("Todo está ya en su sitio: no hay nada que mover."))

    def run(self):
        if not self.plan:
            return
        if any(self.main.pending.values()):
            if QMessageBox.question(self, T("Organizar en carpetas"),
                                    T("Hay cambios sin guardar. Hay que guardarlos antes de mover las canciones. ¿Guardar ahora?")) \
                    != QMessageBox.StandardButton.Yes:
                return
            self.main.save_all()
        if QMessageBox.question(self, T("Organizar en carpetas"),
                                T(f"¿Mover {len(self.plan)} canción(es) a sus carpetas?")) != QMessageBox.StandardButton.Yes:
            return
        self.main.release_if([p for p, _ in self.plan])
        moved, fails, olddirs = 0, [], set()
        for src, dst in self.plan:
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
                olddirs.add(os.path.dirname(src))
                lrc = os.path.splitext(src)[0] + ".lrc"   # la letra .lrc va con su canción
                if os.path.exists(lrc):
                    try:
                        shutil.move(lrc, os.path.splitext(dst)[0] + ".lrc")
                    except OSError:
                        pass
            except OSError as e:
                fails.append(f"{os.path.basename(src)}: {e}")
        removed = 0
        if self.clean.isChecked():
            for d in sorted(olddirs, key=len, reverse=True):
                cur = d
                while os.path.normcase(os.path.normpath(cur)).startswith(os.path.normcase(os.path.normpath(self.folder)) + os.sep):
                    try:
                        left = [f for f in os.listdir(cur) if f.lower() not in ("desktop.ini", "thumbs.db")]
                        if left:
                            break
                        for f in os.listdir(cur):
                            os.remove(os.path.join(cur, f))
                        os.rmdir(cur)
                        removed += 1
                    except OSError:
                        break
                    cur = os.path.dirname(cur)
        if fails:
            QMessageBox.warning(self, T("Organizar en carpetas"), "\n".join(fails[:15]))
        if not (self.main.current_dir and os.path.isdir(self.main.current_dir)):
            self.main.open_dir(self.folder)
        self.main.reload_all()
        self.status.setText(T(f"✔ {moved} canción(es) movidas · {removed} carpeta(s) vacías borradas."))
        self.preview()


# =========================================================== 2. Etiquetas desde el nombre del archivo
NAME_PATTERNS = ["{artista} - {titulo}", "{titulo} - {artista}", "{pista} - {titulo}", "{pista}. {titulo}",
                 "{pista} - {artista} - {titulo}", "{pista}. {artista} - {titulo}", "{artista} - {album} - {pista} - {titulo}"]
FIELD_OF = {"artista": "artist", "titulo": "title", "album": "album", "pista": "tracknumber", "año": "date", "ano": "date",
            "genero": "genre"}


def pattern_regex(pat):
    out, pos = "", 0
    for m in re.finditer(r"\{(\w+)\}", pat):
        out += re.escape(pat[pos:m.start()])
        name = m.group(1).lower()
        key = FIELD_OF.get(name)
        if key is None:
            out += ".+?"
        elif key in ("tracknumber", "date"):
            out += f"(?P<{key}>\\d+)"
        else:
            out += f"(?P<{key}>.+?)"
        pos = m.end()
    out += re.escape(pat[pos:])
    return re.compile("^\\s*" + out + "\\s*$")


class TagsFromNameDialog(QDialog):
    def __init__(self, main, paths):
        super().__init__(main)
        self.main, self.paths = main, paths
        self.setWindowTitle("Etiquetas desde el nombre del archivo")
        self.resize(900, 540)
        v = QVBoxLayout(self)
        info = QLabel("Saca artista, título, pista… del nombre de los archivos seleccionados. "
                      "Usa {artista}, {titulo}, {album}, {pista}, {año} y {genero}. Los cambios quedan pendientes (en naranja) hasta que guardes.")
        info.setWordWrap(True)
        v.addWidget(info)
        row = QHBoxLayout()
        row.addWidget(QLabel("Formato del nombre"))
        self.pat = QComboBox()
        self.pat.setEditable(True)
        self.pat.addItems(NAME_PATTERNS)
        row.addWidget(self.pat, 1)
        v.addLayout(row)
        row2 = QHBoxLayout()
        self.only_empty = QCheckBox("Solo rellenar los campos que estén vacíos")
        self.underscores = QCheckBox("Cambiar «_» por espacios")
        self.underscores.setChecked(True)
        row2.addWidget(self.only_empty)
        row2.addWidget(self.underscores)
        row2.addStretch(1)
        v.addLayout(row2)
        self.tb = _table([T("Archivo"), T("Intérprete"), T("Título"), T("Álbum"), T("Pista"), T("Año")])
        v.addWidget(self.tb, 1)
        self.status = QLabel("")
        v.addWidget(self.status)
        br = QHBoxLayout()
        self.go = QPushButton("✔ Aplicar")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.apply)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.go)
        br.addWidget(close)
        v.addLayout(br)
        self.pat.currentTextChanged.connect(self.preview)
        self.underscores.toggled.connect(self.preview)
        self.result = {}
        # elige solo el formato que más nombres reconoce
        def score(pat):
            sc = 0.0
            for f in paths:
                d = self.parse(f, pat)
                if d:   # un «artista» que solo son números casi seguro es el número de pista
                    sc += 1 + (0.3 if "tracknumber" in d else 0) - (1.5 if d.get("artist", "").isdigit() else 0)
            return sc
        best = max(NAME_PATTERNS, key=score)
        self.pat.setCurrentText(best)
        self.preview()

    def parse(self, path, pat=None):
        base = os.path.splitext(os.path.basename(path))[0]
        if self.underscores.isChecked() if hasattr(self, "underscores") else True:
            base = base.replace("_", " ")
        base = re.sub(r"\s+", " ", base)
        try:
            m = pattern_regex(pat or self.pat.currentText()).match(base)
        except re.error:
            return None
        if not m:
            return None
        d = {k: v.strip() for k, v in m.groupdict().items() if v and v.strip()}
        if "tracknumber" in d:
            d["tracknumber"] = str(int(d["tracknumber"]))
        return d

    def preview(self):
        self.result = {}
        self.tb.setRowCount(0)
        for p in self.paths:
            d = self.parse(p)
            r = self.tb.rowCount()
            self.tb.insertRow(r)
            self.tb.setItem(r, 0, QTableWidgetItem(os.path.basename(p)))
            if d:
                self.result[p] = d
                for c, k in enumerate(("artist", "title", "album", "tracknumber", "date"), start=1):
                    self.tb.setItem(r, c, QTableWidgetItem(d.get(k, "")))
            else:
                it = QTableWidgetItem(T("(no coincide con el formato)"))
                it.setForeground(Qt.GlobalColor.gray)
                self.tb.setItem(r, 1, it)
        self.go.setEnabled(bool(self.result))
        self.status.setText(T(f"{len(self.result)} de {len(self.paths)} archivos reconocidos."))

    def apply(self):
        n = 0
        self.main.apply_form()
        for p, d in self.result.items():
            for k, val in d.items():
                if self.only_empty.isChecked() and self.main.val(p, k):
                    continue
                self.main.pending.setdefault(p, {})[k] = val
                n += 1
        self.main.mark_items()
        self.main.on_select()
        self.main.statusBar().showMessage(T(f"{n} dato(s) puestos desde el nombre del archivo (pendientes de guardar)."))
        self.accept()


# =========================================================== 3. Normalizar volumen
TARGETS = [("Normal: -14 LUFS (Spotify, YouTube)", -14), ("Suave: -16 LUFS (Apple Music)", -16),
           ("Fuerte: -11 LUFS", -11)]


class NormWorker(QThread):
    progress = pyqtSignal(int, int, str)
    finished_all = pyqtSignal(int, list)

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs   # [(src, dst_final, cmd, tmp)]

    def run(self):
        ok, fails = 0, []
        flags = 0x08000000 if sys.platform == "win32" else 0
        for i, (src, dst, cmd, tmp) in enumerate(self.jobs):
            if self.isInterruptionRequested():
                break
            self.progress.emit(i, len(self.jobs), os.path.basename(src))
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   creationflags=flags)
                if r.returncode != 0 or not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
                    lines = (r.stderr or "").strip().splitlines()
                    raise RuntimeError(lines[-1] if lines else "ffmpeg")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(tmp, dst)
                ok += 1
            except Exception as e:
                fails.append(f"{os.path.basename(src)}: {e}")
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except OSError:
                    pass
        self.progress.emit(len(self.jobs), len(self.jobs), "")
        self.finished_all.emit(ok, fails)


class NormalizeDialog(QDialog):
    def __init__(self, main, paths):
        super().__init__(main)
        self.main, self.paths, self.worker = main, paths, None
        self.setWindowTitle("Normalizar volumen")
        self.resize(560, 330)
        v = QVBoxLayout(self)
        info = QLabel(f"Deja las {len(paths)} canciones seleccionadas con el mismo volumen percibido, para que ninguna suene "
                      "mucho más fuerte o más baja que otra. Se conservan las etiquetas y la portada.")
        info.setWordWrap(True)
        v.addWidget(info)
        row = QHBoxLayout()
        row.addWidget(QLabel("Nivel"))
        self.target = QComboBox()
        for name, _ in TARGETS:
            self.target.addItem(name)
        row.addWidget(self.target, 1)
        v.addLayout(row)
        self.mode = QComboBox()
        self.mode.addItem("Guardar copias en la subcarpeta «Volumen normalizado»", "copy")
        self.mode.addItem("Reemplazar las canciones originales", "replace")
        v.addWidget(self.mode)
        warn = QLabel("En MP3, M4A y OGG el audio se vuelve a codificar en alta calidad; la diferencia no se nota, pero "
                      "no conviene repetirlo muchas veces sobre el mismo archivo.")
        warn.setWordWrap(True)
        warn.setObjectName("hint")
        v.addWidget(warn)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status, 1)
        br = QHBoxLayout()
        self.go = QPushButton("🔊 Normalizar")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.start)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.go)
        br.addWidget(close)
        v.addLayout(br)

    def start(self):
        import fx
        from spectro import file_info
        replace = self.mode.currentData() == "replace"
        if replace and QMessageBox.question(self, T("Normalizar volumen"),
                                            T("Se reemplazarán los archivos originales. No se puede deshacer. ¿Continuar?")) \
                != QMessageBox.StandardButton.Yes:
            return
        lufs = TARGETS[self.target.currentIndex()][1]
        jobs = []
        for p in self.paths:
            ext = os.path.splitext(p)[1].lower()
            if ext not in fx.CODECS:
                continue
            try:
                inf = file_info(p)
            except Exception:
                inf = {}
            if replace:
                dst = p
                tmp = os.path.join(os.path.dirname(p), f".mmnorm_tmp{ext}")
            else:
                dst = os.path.join(os.path.dirname(p), T("Volumen normalizado"), os.path.basename(p))
                tmp = os.path.join(os.path.dirname(p), f".mmnorm_tmp{ext}")
            cmd = fx.build_cmd(p, tmp, {"normalize": True, "lufs": lufs}, inf.get("sr") or 44100, inf.get("length") or 0)
            jobs.append((p, dst, cmd, tmp))
        if not jobs:
            self.status.setText(T("Ninguna de las canciones tiene un formato que se pueda normalizar."))
            return
        if replace:
            self.main.release_if([j[0] for j in jobs])
        self.go.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, len(jobs))
        self.worker = NormWorker(jobs)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_all.connect(self.on_done)
        self.worker.start()

    def on_progress(self, i, n, name):
        self.bar.setValue(i)
        if name:
            self.status.setText(T(f"Normalizando {i + 1} de {n}: {name}"))

    def on_done(self, ok, fails):
        self.go.setEnabled(True)
        self.bar.hide()
        msg = T(f"✔ {ok} canción(es) normalizadas.")
        if fails:
            msg += "\n" + "\n".join(fails[:8])
        self.status.setText(msg)
        self.main.reload_all()

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(60000)
        super().closeEvent(e)


# =========================================================== 4. Informe de la biblioteca
CATEGORIES = [
    ("nocover", "Sin portada"), ("smallcover", "Portada pequeña (menos de 500 px)"), ("nolyrics", "Sin letra"),
    ("nogenre", "Sin género"), ("noyear", "Sin año"), ("nobasic", "Sin artista o sin título"),
    ("noalbum", "Sin álbum"), ("lowq", "Calidad baja (menos de 192 kbps)"),
]


class ReportWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(dict, int)

    def __init__(self, files, inspect_file, read_tags):
        super().__init__()
        self.files, self.inspect_file, self.read_tags = files, inspect_file, read_tags

    def run(self):
        import mutagen
        res = {k: [] for k, _ in CATEGORIES}
        for n, p in enumerate(self.files):
            if self.isInterruptionRequested():
                return
            if n % 10 == 0:
                self.progress.emit(n, len(self.files))
            try:
                d = self.inspect_file(p)
                t = self.read_tags(p)
            except Exception:
                continue
            cov = d.get("cover")
            if not cov:
                res["nocover"].append(p)
            else:
                img = QImage.fromData(cov)
                if not img.isNull() and max(img.width(), img.height()) < 500:
                    res["smallcover"].append(p)
            if not (d.get("lyrics") or "").strip():
                res["nolyrics"].append(p)
            if not t.get("genre"):
                res["nogenre"].append(p)
            if not t.get("date"):
                res["noyear"].append(p)
            if not t.get("artist") or not t.get("title"):
                res["nobasic"].append(p)
            if not t.get("album"):
                res["noalbum"].append(p)
            ext = os.path.splitext(p)[1].lower()
            if ext not in (".flac", ".wav", ".aiff", ".aif"):
                try:
                    br = int(getattr(mutagen.File(p).info, "bitrate", 0) or 0)
                    if 0 < br < 192000:
                        res["lowq"].append(p)
                except Exception:
                    pass
        self.progress.emit(len(self.files), len(self.files))
        self.done.emit(res, len(self.files))


class ReportDialog(QDialog):
    def __init__(self, main, folder, audio_ext, inspect_file, read_tags):
        super().__init__(main)
        self.main, self.folder, self.audio_ext = main, folder, audio_ext
        self.inspect_file, self.read_tags = inspect_file, read_tags
        self.res, self.worker = {}, None
        self.setWindowTitle("Informe de la biblioteca")
        self.resize(900, 560)
        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.rec = QCheckBox("Incluir subcarpetas")
        self.rec.setChecked(True)
        row.addWidget(QLabel(folder))
        row.addStretch(1)
        row.addWidget(self.rec)
        self.go = QPushButton("🔍 Analizar")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.start)
        row.addWidget(self.go)
        v.addLayout(row)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        sp = QSplitter()
        self.cats = QListWidget()
        self.cats.currentRowChanged.connect(self.show_cat)
        self.files = QListWidget()
        self.files.itemDoubleClicked.connect(self.open_item)
        sp.addWidget(self.cats)
        sp.addWidget(self.files)
        sp.setSizes([300, 600])
        v.addWidget(sp, 1)
        self.status = QLabel("Doble clic en una canción para ir a ella y arreglarla.")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(close)
        v.addLayout(br)
        self.start()

    def start(self):
        if self.worker is not None and self.worker.isRunning():
            return
        files = list_audio(self.folder, self.rec.isChecked(), self.audio_ext)
        self.cats.clear()
        self.files.clear()
        self.go.setEnabled(False)
        self.bar.setRange(0, max(len(files), 1))
        self.bar.show()
        self.worker = ReportWorker(files, self.inspect_file, self.read_tags)
        self.worker.progress.connect(lambda n, tot: self.bar.setValue(n))
        self.worker.done.connect(self.on_done)
        self.worker.start()

    def on_done(self, res, total):
        self.res = res
        self.go.setEnabled(True)
        self.bar.hide()
        self.cats.clear()
        for key, name in CATEGORIES:
            n = len(res.get(key, []))
            it = QListWidgetItem(f"{'✔' if n == 0 else '•'}  {T(name)}: {n}")
            it.setData(Qt.ItemDataRole.UserRole, key)
            if n == 0:
                it.setForeground(Qt.GlobalColor.darkGreen)
            self.cats.addItem(it)
        self.status.setText(T(f"{total} canciones analizadas. Doble clic en una canción para ir a ella y arreglarla."))
        first = next((i for i, (k, _) in enumerate(CATEGORIES) if res.get(k)), 0)
        self.cats.setCurrentRow(first)

    def show_cat(self, row):
        self.files.clear()
        if row < 0 or row >= len(CATEGORIES):
            return
        for p in self.res.get(CATEGORIES[row][0], []):
            it = QListWidgetItem(os.path.relpath(p, self.folder))
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            self.files.addItem(it)

    def open_item(self, it):
        p = it.data(Qt.ItemDataRole.UserRole)
        if p:
            self.main.reveal_file(p)

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3000)
        super().closeEvent(e)

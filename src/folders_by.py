"""Herramienta «Crear carpetas por…»: toma las canciones elegidas y las reparte en carpetas según sus etiquetas
(intérprete, álbum, género, año, década…), con hasta tres niveles, vista previa y trabajo en segundo plano
(sirve para lotes de miles de canciones)."""
import os, re, shutil
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox,
                             QTreeWidget, QTreeWidgetItem, QProgressBar, QMessageBox, QFileDialog, QApplication,
                             QGridLayout, QLineEdit)
from i18n import tr as T

BAD = r'<>:"/\|?*'
FIELDS = [
    ("", "(nada)"),
    ("artist", "Intérprete"),
    ("artist_main", "Intérprete principal (sin invitados)"),
    ("albumartist", "Intérprete del álbum (o intérprete)"),
    ("album", "Álbum"),
    ("year_album", "Año - Álbum"),
    ("genre", "Género"),
    ("date", "Año"),
    ("decade", "Década (1990s, 2000s…)"),
    ("composer", "Compositor"),
    ("letter", "Primera letra del intérprete (A, B, C…)"),
    ("format", "Formato (MP3, FLAC…)"),
]
MISSING = {"artist": "Artista desconocido", "artist_main": "Artista desconocido", "albumartist": "Artista desconocido",
           "album": "Sin álbum", "year_album": "Sin álbum", "genre": "Sin género", "date": "Sin año",
           "decade": "Sin año", "composer": "Sin compositor", "letter": "#", "format": "Otros"}


def safe(t):
    t = "".join("_" if c in BAD or ord(c) < 32 else c for c in (t or "")).strip().rstrip(". ")
    return t[:120]


_NAME_ARTIST = re.compile(r"^(?:\d{1,3}(?:[-.]\d{1,3})?\s*[.)\-–_]?\s+)?(.+?)\s+[-–]\s+.+$")
AUDIO = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".wav", ".wma", ".aac", ".aiff", ".aif", ".ape", ".wv"}


def artist_from_name(path):
    """Si la canción no tiene intérprete en las etiquetas, se saca del nombre: «03. Tungas - Dicen…» → «Tungas»."""
    m = _NAME_ARTIST.match(os.path.splitext(os.path.basename(path))[0])
    return m.group(1).strip() if m else ""


def audio_in(folder, sub=False):
    out = []
    try:
        if sub:
            for d, dirs, files in os.walk(folder):
                dirs[:] = [x for x in dirs if not x.startswith(".")]
                out += [os.path.join(d, f) for f in files if os.path.splitext(f)[1].lower() in AUDIO]
        else:
            out = [e.path for e in os.scandir(folder) if e.is_file() and os.path.splitext(e.name)[1].lower() in AUDIO]
    except OSError:
        pass
    return sorted(out, key=str.lower)


def main_artist(a):
    return re.split(r"\s*(?:,|&|;|/| feat\.? | ft\.? | x )\s*", a or "", maxsplit=1, flags=re.I)[0].strip()


class MoveWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(int, list, list)

    def __init__(self, plan, copy):
        super().__init__()
        self.plan, self.copy, self.stop = plan, copy, False

    def run(self):
        ok, fails, moved = 0, [], []
        for i, (src, dst) in enumerate(self.plan):
            if self.stop:
                break
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                (shutil.copy2 if self.copy else shutil.move)(src, dst)
                ok += 1
                moved.append((dst, src))
                lrc = os.path.splitext(src)[0] + ".lrc"   # la letra .lrc acompaña a su canción
                if os.path.exists(lrc):
                    try:
                        (shutil.copy2 if self.copy else shutil.move)(lrc, os.path.splitext(dst)[0] + ".lrc")
                    except OSError:
                        pass
            except OSError as e:
                fails.append(f"{os.path.basename(src)}: {e}")
            if i % 5 == 0 or i == len(self.plan) - 1:
                self.progress.emit(i + 1, len(self.plan))
        self.done.emit(ok, fails, moved)


class FoldersByDialog(QDialog):
    def __init__(self, main, paths, tech_info, folder=None):
        """folder: modo «Separar carpeta por artista»: toma las canciones de esa carpeta y crea dentro una carpeta por
        artista."""
        super().__init__(main)
        self.main, self.paths, self.tech_info = main, list(paths), tech_info
        self.folder = folder
        self.worker, self.plan = None, []
        self.title = T("Separar carpeta por artista") if folder else T("Crear carpetas por…")
        self.setWindowTitle(self.title)
        scr = (main.screen() or QApplication.primaryScreen()).availableGeometry()
        self.resize(min(860, scr.width() - 60), min(660, scr.height() - 80))
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        if folder:
            info = QLabel(T("Crea dentro de la carpeta una carpeta por cada artista y mete ahí sus canciones. El artista "
                            "se toma de las etiquetas o, si falta, del nombre del archivo («03. Artista - Canción»). "
                            "Primero ves cómo quedará; no se mueve nada hasta que pulses el botón, y luego se puede "
                            "deshacer con Ctrl+Alt+Z."))
        else:
            info = QLabel(T("Reparte las canciones elegidas en carpetas según sus datos. Elige hasta tres niveles "
                            "(por ejemplo Género → Intérprete → Álbum). Primero ves cómo quedará; no se mueve nada hasta "
                            "que pulses el botón."))
        info.setWordWrap(True)
        v.addWidget(info)
        if folder:
            fr = QHBoxLayout()
            fr.addWidget(QLabel(T("Carpeta:")))
            self.folder_le = QLineEdit(folder)
            self.folder_le.setReadOnly(True)
            fr.addWidget(self.folder_le, 1)
            pick = QPushButton(T("Elegir otra…"))
            pick.clicked.connect(self.pick_folder)
            fr.addWidget(pick)
            self.sub = QCheckBox(T("Incluir subcarpetas"))
            self.sub.toggled.connect(self.rescan)
            fr.addWidget(self.sub)
            v.addLayout(fr)
        g = QGridLayout()
        self.levels = []
        defaults = ["artist_main", "", ""] if folder else ["albumartist", "album", ""]
        for i, lab in enumerate((T("Crear carpetas por"), T("y dentro, por"), T("y dentro, por"))):
            cb = QComboBox()
            for k, name in FIELDS:
                if i == 0 and not k:
                    continue
                cb.addItem(T(name), k)
            cb.setCurrentIndex(max(0, cb.findData(defaults[i])))
            cb.currentIndexChanged.connect(self.preview)
            g.addWidget(QLabel(lab), i, 0)
            g.addWidget(cb, i, 1)
            self.levels.append(cb)
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        common = os.path.commonpath([os.path.dirname(p) for p in self.paths]) if self.paths else ""
        self.base = folder or (main.current_dir if main.current_dir and os.path.isdir(main.current_dir) else common)
        wr = QHBoxLayout()
        wr.addWidget(QLabel(T("Dónde crearlas:")))
        self.base_le = QLineEdit(self.base)
        self.base_le.setReadOnly(True)
        wr.addWidget(self.base_le, 1)
        chg = QPushButton(T("Cambiar…"))
        chg.clicked.connect(self.pick_base)
        wr.addWidget(chg)
        v.addLayout(wr)
        opts = QHBoxLayout()
        self.copy = QCheckBox(T("Copiar (dejar también las originales)"))
        self.skip_missing = QCheckBox(T("Si falta el dato, dejar la canción donde está"))
        self.min_n = QCheckBox(T("No crear carpetas de una sola canción (van a «Varios»)"))
        for c in (self.copy, self.skip_missing, self.min_n):
            c.toggled.connect(self.preview)
            opts.addWidget(c)
        opts.addStretch(1)
        v.addLayout(opts)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([T("Carpeta / canción"), T("Canciones")])
        self.tree.setColumnWidth(0, 560)
        self.tree.setUniformRowHeights(True)
        v.addWidget(self.tree, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        br = QHBoxLayout()
        self.go = QPushButton(T("📁 Crear carpetas y mover"))
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.run)
        self.close_btn = QPushButton(T("Cerrar"))
        self.close_btn.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.go)
        br.addWidget(self.close_btn)
        v.addLayout(br)
        self.copy.toggled.connect(lambda on: self.go.setText(T("📁 Crear carpetas y copiar") if on else T("📁 Crear carpetas y mover")))
        self.preview()

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, T("Carpeta a separar"), self.folder)
        if d:
            self.folder = self.base = os.path.normpath(d)
            self.folder_le.setText(self.folder)
            self.base_le.setText(self.folder)
            self.rescan()

    def rescan(self):
        self.paths = audio_in(self.folder, self.sub.isChecked())
        self.preview()

    # ------------------------------------------------------------ datos
    def value(self, p, key):
        val = self.main.val
        if key == "artist":
            return safe(val(p, "artist") or artist_from_name(p))
        if key == "artist_main":
            return safe(main_artist(val(p, "artist") or artist_from_name(p)))
        if key == "albumartist":
            return safe(val(p, "albumartist") or val(p, "artist") or artist_from_name(p))
        if key == "album":
            return safe(val(p, "album"))
        if key == "year_album":
            y, alb = (val(p, "date") or "")[:4], safe(val(p, "album"))
            return (f"{y} - {alb}" if y.isdigit() else alb) if alb else ""
        if key == "genre":
            return safe(re.split(r"\s*[;/]\s*", val(p, "genre") or "")[0])
        if key == "date":
            y = (val(p, "date") or "")[:4]
            return y if y.isdigit() else ""
        if key == "decade":
            y = (val(p, "date") or "")[:4]
            return f"{int(y) // 10 * 10}s" if y.isdigit() else ""
        if key == "composer":
            return safe(val(p, "composer"))
        if key == "letter":
            a = (val(p, "albumartist") or val(p, "artist") or "").strip()
            c = a[:1].upper()
            return c if c.isalpha() else ("#" if a else "")
        if key == "format":
            c = self.tech_info(p).get("codec", "")
            return safe(c) if c and c != "—" else ""
        return ""

    def pick_base(self):
        d = QFileDialog.getExistingDirectory(self, T("Dónde crear las carpetas"), self.base)
        if d:
            self.base = d
            self.base_le.setText(d)
            self.preview()

    # ------------------------------------------------------------ vista previa
    def preview(self):
        keys = [cb.currentData() for cb in self.levels if cb.currentData()]
        groups, skipped, canon = {}, 0, {}
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for i, p in enumerate(self.paths):
                if i % 200 == 0:
                    QApplication.processEvents()
                parts, missing = [], False
                for k in keys:
                    val = self.value(p, k)
                    if not val:
                        missing = True
                        val = T(MISSING.get(k, "Otros"))
                    parts.append(val)
                if missing and self.skip_missing.isChecked():
                    skipped += 1
                    continue
                key = tuple(canon.setdefault(x.lower(), x) for x in parts)   # «BUNBURY» y «Bunbury» = una carpeta
                groups.setdefault(key, []).append(p)
            if self.min_n.isChecked() and len(keys) >= 1:   # grupos de 1 canción → «Varios» del nivel de arriba
                merged = {}
                for parts, ps in groups.items():
                    key = parts if len(ps) > 1 else parts[:-1] + (T("Varios"),)
                    merged.setdefault(key, []).extend(ps)
                groups = merged
            self.plan, taken = [], set()
            self.tree.setUpdatesEnabled(False)
            self.tree.clear()
            nodes = {}
            existing = {}
            try:   # si ya hay una carpeta «bunbury» se usa esa aunque cambien las mayúsculas
                existing = {e.name.lower(): e.name for e in os.scandir(self.base) if e.is_dir()}
            except OSError:
                pass
            for orig in sorted(groups, key=lambda t: [x.lower() for x in t]):
                parts = (existing.get(orig[0].lower(), orig[0]),) + tuple(orig[1:])
                dst_dir = os.path.join(self.base, *parts)
                parent = None
                for d in range(len(parts)):
                    k = parts[:d + 1]
                    if k not in nodes:
                        it = QTreeWidgetItem([("📁 " + parts[d]), ""])
                        (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
                        nodes[k] = [it, 0]
                    parent = nodes[k][0]
                for p in groups[orig]:
                    name = os.path.basename(p)
                    if os.path.normcase(os.path.normpath(os.path.dirname(p))) == os.path.normcase(os.path.normpath(dst_dir)):
                        continue   # ya está en su carpeta
                    base, ext = os.path.splitext(name)
                    dst, n = os.path.join(dst_dir, name), 2
                    while os.path.exists(dst) or os.path.normcase(dst) in taken:
                        dst = os.path.join(dst_dir, f"{base} ({n}){ext}")
                        n += 1
                    taken.add(os.path.normcase(dst))
                    self.plan.append((p, dst))
                    parent.addChild(QTreeWidgetItem(["🎵 " + os.path.basename(dst), ""]))
                    for d in range(len(parts)):
                        nodes[parts[:d + 1]][1] += 1
            for it, n in nodes.values():
                it.setText(1, str(n))
            if len(nodes) <= 40:
                self.tree.expandAll()
            self.tree.setUpdatesEnabled(True)
        finally:
            QApplication.restoreOverrideCursor()
        folders = len({os.path.dirname(d) for _, d in self.plan})
        msg = T(f"{len(self.plan)} de {len(self.paths)} canciones irán a {folders} carpeta(s).")
        if skipped:
            msg += " " + T(f"{skipped} se quedan donde están (les falta el dato).")
        self.status.setText(msg)
        self.go.setEnabled(bool(self.plan))

    # ------------------------------------------------------------ mover
    def run(self):
        if not self.plan or self.worker is not None:
            return
        m = self.main
        if any(m.pending.get(p) for p, _ in self.plan) or (m.edited and set(m.cur_paths) & {p for p, _ in self.plan}):
            if QMessageBox.question(self, self.title,
                                    T("Algunas de estas canciones tienen cambios sin guardar. ¿Guardar ahora antes de moverlas?")) \
                    != QMessageBox.StandardButton.Yes:
                return
            m.save_all()
        verb = T("copiar") if self.copy.isChecked() else T("mover")
        if QMessageBox.question(self, self.title,
                                T(f"¿{verb.capitalize()} {len(self.plan)} canción(es) a sus carpetas?")) != QMessageBox.StandardButton.Yes:
            return
        if not self.copy.isChecked():
            m.release_if([p for p, _ in self.plan])
        self.go.setEnabled(False)
        self.close_btn.setText(T("Detener"))
        self.close_btn.clicked.disconnect()
        self.close_btn.clicked.connect(self.stop)
        self.bar.setRange(0, len(self.plan))
        self.bar.setValue(0)
        self.bar.show()
        self.worker = MoveWorker(list(self.plan), self.copy.isChecked())
        self.worker.progress.connect(lambda i, n: (self.bar.setValue(i), self.status.setText(T(f"Procesando {i} de {n}…"))))
        self.worker.done.connect(self.finished_ok)
        self.worker.start()

    def stop(self):
        if self.worker is not None:
            self.worker.stop = True

    def finished_ok(self, ok, fails, moved=None):
        self.worker = None
        if moved and not self.copy.isChecked():
            try:   # Ctrl+Alt+Z lo devuelve todo a su sitio
                self.main.push_undo(T("separar en carpetas"), moved)
            except Exception:
                pass
        self.bar.hide()
        self.close_btn.setText(T("Cerrar"))
        self.close_btn.clicked.disconnect()
        self.close_btn.clicked.connect(self.close)
        done = {p for p, _ in self.plan[:ok + len(fails)]}
        if not self.copy.isChecked():
            self.paths = [p for p in self.paths if os.path.exists(p)]
        try:
            self.main.reload_all()
        except Exception:
            pass
        if fails:
            QMessageBox.warning(self, self.title, "\n".join(fails[:15]))
        self.preview()
        self.status.setText(T(f"✔ {ok} canción(es) listas en {self.base}.") + (" " + T(f"{len(fails)} con error.") if fails else ""))

    def closeEvent(self, e):
        if self.worker is not None:
            self.worker.stop = True
            self.worker.wait(5000)
        super().closeEvent(e)

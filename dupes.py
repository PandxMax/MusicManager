"""Buscar canciones repetidas: agrupa por artista + título (o solo título, o archivo idéntico) y deja
marcadas las copias de peor calidad para enviarlas a la papelera."""
import os, re, hashlib, unicodedata
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QProgressBar,
                             QTreeWidget, QTreeWidgetItem, QHeaderView, QMessageBox, QCheckBox)
from i18n import tr as T

LOSSLESS = {".flac", ".wav", ".aiff", ".aif", ".ape", ".wv", ".alac"}


def _norm(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    # versiones distintas (remix, en vivo, acústica…) NO son la misma canción
    kinds = sorted(set(re.findall(r"\b(remix|live|en vivo|acoustic|acustic[oa]|instrumental|karaoke|sped up|slowed|"
                                  r"nightcore|cover|demo|extended|radio edit)\b", t)))
    t = re.sub(r"\s-\s*(\d{4}\s*)?(digital(ly)?\s*)?remaster(ed)?(\s*\d{4})?.*$", " ", t)   # «- Remastered 2011»
    t = re.sub(r"\(.*?\)|\[.*?\]|\bfeat\.?.*|\bft\.?.*", " ", t)
    t = re.sub(r"\b(remaster(ed)?|official|audio|video|lyrics?|hd|hq|version)\b", " ", t)
    for k in kinds:
        t = re.sub(r"\b" + re.escape(k) + r"\b", " ", t)
    t = re.sub(r"[^0-9a-zñ]+", " ", t).strip()
    return (t + " " + " ".join(kinds)).strip() if t else ""


class ScanWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(list)

    def __init__(self, folder, recursive, mode, audio_ext):
        super().__init__()
        self.folder, self.recursive, self.mode, self.audio_ext = folder, recursive, mode, audio_ext

    def files(self):
        out = []
        if self.recursive:
            for dp, _, fs in os.walk(self.folder):
                out += [os.path.join(dp, f) for f in fs if os.path.splitext(f)[1].lower() in self.audio_ext]
        else:
            try:
                out = [os.path.join(self.folder, f) for f in os.listdir(self.folder)
                       if os.path.splitext(f)[1].lower() in self.audio_ext]
            except OSError:
                pass
        return [f for f in out if os.path.isfile(f)]

    def info(self, path):
        import mutagen
        d = {"path": path, "artist": "", "title": "", "bitrate": 0, "length": 0.0,
             "ext": os.path.splitext(path)[1].lower(), "size": 0}
        try:
            d["size"] = os.path.getsize(path)
            f = mutagen.File(path, easy=True)
            if f is not None:
                if f.tags:
                    d["artist"] = str((f.tags.get("artist") or [""])[0])
                    d["title"] = str((f.tags.get("title") or [""])[0])
                i = f.info
                d["bitrate"] = int(getattr(i, "bitrate", 0) or 0)
                d["length"] = float(getattr(i, "length", 0) or 0)
        except Exception:
            pass
        if not d["title"]:   # sin etiquetas: «Artista - Título.mp3»
            base = os.path.splitext(os.path.basename(path))[0]
            if " - " in base:
                a, t = base.split(" - ", 1)
                d["artist"] = d["artist"] or a
                d["title"] = t
            else:
                d["title"] = base
        return d

    @staticmethod
    def digest(path):
        h = hashlib.sha1()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def run(self):
        files = self.files()
        infos, groups = [], {}
        for n, p in enumerate(files):
            if self.isInterruptionRequested():
                return
            infos.append(self.info(p))
            if n % 10 == 0:
                self.progress.emit(n, len(files))
        if self.mode == "hash":
            by_size = {}
            for d in infos:
                by_size.setdefault(d["size"], []).append(d)
            for same in by_size.values():
                if len(same) < 2:
                    continue
                for d in same:
                    try:
                        groups.setdefault(self.digest(d["path"]), []).append(d)
                    except OSError:
                        pass
        else:
            for d in infos:
                t = _norm(d["title"])
                if not t:
                    continue
                key = t if self.mode == "title" else (_norm(d["artist"]) + "|" + t)
                groups.setdefault(key, []).append(d)
        self.progress.emit(len(files), len(files))
        self.done.emit([g for g in groups.values() if len(g) > 1])


def quality(d):
    """Cuanto más alto, mejor copia: sin pérdida > más kbps > más grande."""
    return (1 if d["ext"] in LOSSLESS else 0, d["bitrate"], d["size"])


def fmt_size(b):
    return f"{b / 1048576:.1f} MB"


class DupesDialog(QDialog):
    def __init__(self, folder, audio_ext, parent=None, on_changed=None, on_open=None, send2trash=None):
        super().__init__(parent)
        self.folder, self.audio_ext, self.on_changed, self.on_open = folder, audio_ext, on_changed, on_open
        self.trash = send2trash
        self.worker = None
        self.setWindowTitle("Canciones repetidas")
        self.resize(900, 560)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Buscar en"))
        self.scope = QComboBox()
        self.scope.addItem("Esta carpeta", False)
        self.scope.addItem("Esta carpeta y sus subcarpetas", True)
        self.scope.setCurrentIndex(1)
        top.addWidget(self.scope)
        top.addSpacing(12)
        top.addWidget(QLabel("Repetidas si tienen"))
        self.mode = QComboBox()
        self.mode.addItem("El mismo artista y título (recomendado)", "artist")
        self.mode.addItem("Solo el mismo título", "title")
        self.mode.addItem("Exactamente el mismo archivo", "hash")
        top.addWidget(self.mode, 1)
        self.go = QPushButton("🔍 Buscar")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.start)
        top.addWidget(self.go)
        v.addLayout(top)
        self.where = QLabel(folder)
        self.where.setObjectName("hint")
        v.addWidget(self.where)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([T("Archivo"), T("Formato"), T("Calidad"), T("Duración"), T("Tamaño"), T("Carpeta")])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 5):
            self.tree.header().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.itemChanged.connect(lambda *_: self.update_count())
        v.addWidget(self.tree, 1)
        self.status = QLabel("Pulsa «Buscar». Se marcarán solas las copias de peor calidad; la mejor de cada grupo queda sin marcar.")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        self.btn_del = QPushButton("🗑 Enviar las marcadas a la papelera")
        self.btn_del.setEnabled(False)
        self.btn_del.clicked.connect(self.delete_checked)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addStretch(1)
        br.addWidget(self.btn_del)
        br.addWidget(close)
        v.addLayout(br)

    def start(self):
        if self.worker is not None and self.worker.isRunning():
            return
        self.tree.clear()
        self.go.setEnabled(False)
        self.btn_del.setEnabled(False)
        self.bar.setRange(0, 0)
        self.bar.show()
        self.status.setText(T("Leyendo las canciones…"))
        self.worker = ScanWorker(self.folder, self.scope.currentData(), self.mode.currentData(), self.audio_ext)
        self.worker.progress.connect(lambda n, tot: (self.bar.setRange(0, max(tot, 1)), self.bar.setValue(n)))
        self.worker.done.connect(self.show_groups)
        self.worker.start()

    def show_groups(self, groups):
        self.go.setEnabled(True)
        self.bar.hide()
        self.tree.blockSignals(True)
        groups.sort(key=lambda g: (g[0]["artist"].lower(), g[0]["title"].lower()))
        for g in groups:
            g.sort(key=quality, reverse=True)
            name = " – ".join(x for x in (g[0]["artist"], g[0]["title"]) if x)
            top = QTreeWidgetItem([f"{name}  ({len(g)})"])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for i, d in enumerate(g):
                q = "Sin pérdida" if d["ext"] in LOSSLESS else (f"{d['bitrate'] // 1000} kbps" if d["bitrate"] else "—")
                ln = f"{int(d['length'] // 60)}:{int(d['length'] % 60):02d}" if d["length"] else "—"
                it = QTreeWidgetItem([os.path.basename(d["path"]), d["ext"].lstrip(".").upper(), T(q), ln,
                                      fmt_size(d["size"]), os.path.dirname(d["path"])])
                it.setData(0, Qt.ItemDataRole.UserRole, d["path"])
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
                it.setCheckState(0, Qt.CheckState.Unchecked if i == 0 else Qt.CheckState.Checked)
                it.setToolTip(0, T("La mejor copia del grupo") if i == 0 else d["path"])
                top.addChild(it)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        if not groups:
            self.status.setText(T("✔ No hay canciones repetidas."))
        self.update_count()

    def checked(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                it = top.child(j)
                if it.checkState(0) == Qt.CheckState.Checked:
                    out.append(it.data(0, Qt.ItemDataRole.UserRole))
        return out

    def update_count(self):
        n = self.tree.topLevelItemCount()
        if not n:
            self.btn_del.setEnabled(False)
            return
        sel = self.checked()
        size = sum(os.path.getsize(p) for p in sel if os.path.exists(p))
        self.btn_del.setEnabled(bool(sel))
        self.status.setText(T(f"{n} grupos de repetidas · {len(sel)} marcadas ({fmt_size(size)}). "
                              f"Doble clic para ver la canción en la lista."))

    def open_item(self, it, _col):
        p = it.data(0, Qt.ItemDataRole.UserRole)
        if p and self.on_open:
            self.on_open(p)

    def delete_checked(self):
        sel = self.checked()
        if not sel:
            return
        # nunca borrar todas las copias de un grupo
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.childCount() and all(top.child(j).checkState(0) == Qt.CheckState.Checked for j in range(top.childCount())):
                QMessageBox.warning(self, T("Canciones repetidas"),
                                    T("En algún grupo están marcadas TODAS las copias. Deja al menos una sin marcar."))
                return
        how = T("a la papelera") if self.trash else T("de forma PERMANENTE")
        if QMessageBox.question(self, T("Canciones repetidas"),
                                T(f"¿Enviar {len(sel)} canción(es) {how}?")) != QMessageBox.StandardButton.Yes:
            return
        fails = []
        for p in sel:
            try:
                if self.trash:
                    self.trash(os.path.normpath(p))
                else:
                    os.remove(p)
            except Exception as e:
                fails.append(f"{os.path.basename(p)}: {e}")
        if fails:
            QMessageBox.warning(self, T("Canciones repetidas"), "\n".join(fails[:15]))
        if self.on_changed:
            self.on_changed()
        self.start()   # vuelve a buscar para mostrar cómo quedó

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3000)
        super().closeEvent(e)

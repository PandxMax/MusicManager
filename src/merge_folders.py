"""«Unir carpeta de artistas con la biblioteca por géneros».

Origen: una carpeta con una subcarpeta por artista (Artistas/Bunbury, Artistas/Tungas…).
Destino: la biblioteca ordenada por género, con los artistas dentro, a cualquier profundidad
(MUSICAS/ROCK/Español/Rock Alternativo/Bunbury…).

Cada carpeta de artista del origen se «sobrepone» a la del mismo artista en el destino: su contenido pasa allí
(las subcarpetas de álbum también se juntan) y la carpeta del origen desaparece si queda vacía. Los artistas que
no existen en el destino se pueden mandar a un género a mano o dejar donde están. Antes se ve todo en una tabla;
luego se puede deshacer con Ctrl+Alt+Z."""
import os, re, shutil, unicodedata
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit,
                             QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QApplication,
                             QAbstractItemView)
from i18n import tr as T

AUDIO = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".wav", ".wma", ".aac", ".aiff", ".aif", ".ape", ".wv"}
KEEP = "__keep__"


def norm(name):
    """«Café Tacvba» = «cafe tacvba» = «Cafe-Tacvba»; «The Beatles» = «Beatles»; «Simon & Garfunkel» = «Simon y Garfunkel»."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^(the|los|las|la|el)\s+", "", s.strip())
    s = re.sub(r"\s*(&|\by\b|\band\b)\s*", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def count_audio(folder):
    n = 0
    for _d, dirs, files in os.walk(folder):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        n += sum(1 for f in files if os.path.splitext(f)[1].lower() in AUDIO)
    return n


def index_library(root, max_depth=7):
    """Todas las carpetas de la biblioteca: nombre normalizado → [rutas]. Y la lista de carpetas «de género» (las que
    tienen subcarpetas), para elegir a mano dónde va un artista nuevo."""
    by_name, genres = {}, []
    root = os.path.normpath(root)
    base = root.count(os.sep)
    for d, dirs, _files in os.walk(root):
        dirs[:] = sorted((x for x in dirs if not x.startswith(".")), key=str.lower)
        depth = d.count(os.sep) - base
        if depth >= max_depth:
            dirs[:] = []
        if d != root:
            by_name.setdefault(norm(os.path.basename(d)), []).append(d)
        if dirs:
            genres.append(d)
    return by_name, genres


def plan_merge(src_dir, dst_dir, keep_both=False):
    """Lista de (origen, destino) archivo por archivo, y los que ya existen en el destino."""
    moves, dup = [], []
    for d, dirs, files in os.walk(src_dir):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        rel = os.path.relpath(d, src_dir)
        tgt_dir = dst_dir if rel == "." else os.path.join(dst_dir, rel)
        existing = {}
        try:
            existing = {e.name.lower(): e.name for e in os.scandir(tgt_dir)}
        except OSError:
            pass
        for f in files:
            src = os.path.join(d, f)
            if f.lower() in existing:
                if not keep_both:
                    dup.append(src)
                    continue
                root, ext = os.path.splitext(f)
                n = 2
                while f"{root} ({n}){ext}".lower() in existing:
                    n += 1
                f = f"{root} ({n}){ext}"
                existing[f.lower()] = f
            moves.append((src, os.path.join(tgt_dir, f)))
    return moves, dup


def remove_empty(folder):
    for d, dirs, files in os.walk(folder, topdown=False):
        try:
            if not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass


class MergeFoldersDialog(QDialog):
    def __init__(self, main, src=None, dst=None):
        super().__init__(main)
        self.main = main
        self.rows = []   # [(carpeta del artista en el origen, nº canciones, combo de destino)]
        self.setWindowTitle(T("Unir carpeta de artistas con la biblioteca por géneros"))
        scr = (main.screen() or QApplication.primaryScreen()).availableGeometry()
        self.resize(min(980, scr.width() - 60), min(680, scr.height() - 80))
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        info = QLabel(T("Cada carpeta de artista de la izquierda se junta con la del mismo artista en tu biblioteca por "
                        "géneros: sus canciones y álbumes pasan allí y la carpeta vacía desaparece. Los artistas que no "
                        "están en la biblioteca puedes mandarlos a un género o dejarlos donde están. No se mueve nada "
                        "hasta que pulses «Unir», y luego se puede deshacer con Ctrl+Alt+Z."))
        info.setWordWrap(True)
        v.addWidget(info)
        self.src_le = self._path_row(v, T("Carpeta de artistas (lo que se mueve):"), src or "")
        self.dst_le = self._path_row(v, T("Biblioteca por géneros (a dónde va):"), dst or "")
        opt = QHBoxLayout()
        opt.addWidget(QLabel(T("Si una canción ya está en la biblioteca:")))
        self.dup = QComboBox()
        self.dup.addItem(T("Dejarla en la carpeta de artistas (no duplicar)"), False)
        self.dup.addItem(T("Guardar las dos (la nueva con «(2)»)"), True)
        self.dup.currentIndexChanged.connect(self.refresh_status)
        opt.addWidget(self.dup)
        opt.addStretch(1)
        v.addLayout(opt)
        self.tb = QTableWidget(0, 4)
        self.tb.setHorizontalHeaderLabels([T("Artista"), T("Canciones"), T("Destino"), T("Qué pasará")])
        hh = self.tb.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.tb.verticalHeader().setVisible(False)
        self.tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        v.addWidget(self.tb, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        bb = QHBoxLayout()
        bb.addStretch(1)
        self.go = QPushButton(T("🔀 Unir"))
        self.go.setObjectName("primary")
        self.go.clicked.connect(self.run)
        cancel = QPushButton(T("Cerrar"))
        cancel.clicked.connect(self.close)
        bb.addWidget(self.go)
        bb.addWidget(cancel)
        v.addLayout(bb)
        self.analyze()

    def _path_row(self, v, label, value):
        h = QHBoxLayout()
        lab = QLabel(label)
        lab.setMinimumWidth(260)
        h.addWidget(lab)
        le = QLineEdit(value)
        le.setReadOnly(True)
        h.addWidget(le, 1)
        b = QPushButton(T("Elegir…"))

        def pick():
            d = QFileDialog.getExistingDirectory(self, label, le.text() or "")
            if d:
                le.setText(os.path.normpath(d))
                self.analyze()
        b.clicked.connect(pick)
        h.addWidget(b)
        v.addLayout(h)
        return le

    # ------------------------------------------------------------ análisis
    def analyze(self):
        self.tb.setRowCount(0)
        self.rows = []
        src, dst = self.src_le.text(), self.dst_le.text()
        if not (src and dst and os.path.isdir(src) and os.path.isdir(dst)):
            self.status.setText(T("Elige las dos carpetas."))
            self.go.setEnabled(False)
            return
        if os.path.normcase(src) == os.path.normcase(dst) or \
                os.path.normcase(dst).startswith(os.path.normcase(src) + os.sep) or \
                os.path.normcase(src).startswith(os.path.normcase(dst) + os.sep):
            self.status.setText(T("Las dos carpetas no pueden ser la misma ni estar una dentro de la otra."))
            self.go.setEnabled(False)
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            by_name, genres = index_library(dst)
            artists = sorted((e.path for e in os.scandir(src) if e.is_dir() and not e.name.startswith(".")),
                             key=lambda p: os.path.basename(p).lower())
            gen_rel = [os.path.relpath(g, dst) for g in genres if g != os.path.normpath(dst)]
            for a in artists:
                n = count_audio(a)
                if not n:
                    continue
                cands = by_name.get(norm(os.path.basename(a)), [])
                # si el artista está en varios géneros, primero el que tiene más canciones
                cands = sorted(cands, key=lambda c: -count_audio(c))
                r = self.tb.rowCount()
                self.tb.insertRow(r)
                self.tb.setItem(r, 0, QTableWidgetItem(os.path.basename(a)))
                it = QTableWidgetItem(str(n))
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.tb.setItem(r, 1, it)
                cb = QComboBox()
                for c in cands:
                    cb.addItem("🔗 " + os.path.relpath(c, dst), "join|" + c)
                cb.addItem(T("(dejar donde está)"), KEEP)
                for g in gen_rel:
                    cb.addItem("📁 " + os.path.join(g, os.path.basename(a)), "new|" + os.path.join(dst, g, os.path.basename(a)))
                cb.setCurrentIndex(0 if cands else len(cands))
                cb.currentIndexChanged.connect(self.refresh_status)
                self.tb.setCellWidget(r, 2, cb)
                self.tb.setItem(r, 3, QTableWidgetItem(""))
                self.rows.append((a, n, cb))
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh_status()

    @staticmethod
    def choice(cb):
        d = cb.currentData() or KEEP
        return (KEEP, None) if d == KEEP else tuple(d.split("|", 1))

    def refresh_status(self):
        joins = news = keep = 0
        for r, (a, n, cb) in enumerate(self.rows):
            kind, target = self.choice(cb)
            if kind == "join":
                txt, joins = T(f"Se une con la carpeta que ya existe ({n} canciones)"), joins + 1
            elif kind == "new":
                txt, news = T("Se crea en ese género"), news + 1
            else:
                txt, keep = T("Se queda donde está (no está en la biblioteca)"), keep + 1
            self.tb.item(r, 3).setText(txt)
        self.status.setText(T(f"{len(self.rows)} artistas · {joins} se unen con su carpeta · {news} van a un género nuevo · "
                              f"{keep} se quedan donde están.") if self.rows else
                            T("La carpeta de artistas no tiene subcarpetas con canciones."))
        self.go.setEnabled(joins + news > 0)

    # ------------------------------------------------------------ unir
    def run(self):
        keep_both = bool(self.dup.currentData())
        jobs, dups, used = [], [], []
        for a, _n, cb in self.rows:
            kind, target = self.choice(cb)
            if kind == KEEP:
                continue
            mv, dp = plan_merge(a, target, keep_both)
            jobs += mv
            dups += dp
            used.append(a)
        if not jobs:
            QMessageBox.information(self, self.windowTitle(), T("No hay nada que mover: esas canciones ya están en la biblioteca."))
            return
        if QMessageBox.question(self, self.windowTitle(),
                                T(f"¿Mover {len(jobs)} archivo(s) de {len(used)} artista(s) a la biblioteca?")
                                + ("\n\n" + T(f"{len(dups)} ya están allí y se quedarán en la carpeta de artistas.") if dups else "")
                                ) != QMessageBox.StandardButton.Yes:
            return
        m = self.main
        try:
            m.release_if([a for a in used])
        except Exception:
            pass

        def one(job):
            src, dst = job
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)
            return dst
        out = m.run_batch(T(f"Uniendo {len(jobs)} archivos…"), jobs, one)
        moved = [(dst, src) for (src, dst), _r, err in out if err is None]
        errors = [f"{os.path.basename(src)}: {err}" for (src, _d), _r, err in out if err is not None]
        for src, _d in [j for j, _r, e in out if e is None]:
            try:
                m.retarget(src, _d)
            except Exception:
                pass
        for a in used:
            remove_empty(a)
        try:
            m.push_undo(T("unir carpetas"), moved)
            m.after_fs_change()
        except Exception:
            pass
        msg = T(f"Listo: {len(moved)} archivo(s) unidos a la biblioteca.")
        if dups:
            msg += "\n" + T(f"{len(dups)} ya estaban y se quedaron en la carpeta de artistas.")
        if errors:
            msg += "\n\n" + "\n".join(errors[:15])
        QMessageBox.information(self, self.windowTitle(), msg)
        self.analyze()

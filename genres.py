"""Géneros en lote: agrupa por álbum las canciones de una carpeta (o las seleccionadas), encuentra las que tienen
géneros demasiado generales («Electronic», «Rock»…) o vacíos, sugiere géneros específicos con MusicBrainz (gratis)
y con la IA solo para lo que falte, y deja revisar y elegir antes de cambiar nada.
Lo ya consultado se guarda, así se puede cortar y seguir otro día."""
import os, re, json, time, urllib.request, urllib.parse, unicodedata
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStandardPaths
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox,
                             QTreeWidget, QTreeWidgetItem, QHeaderView, QProgressBar, QMessageBox, QAbstractItemView)
from i18n import tr as T

GENERIC = {"", "electronic", "electronica", "electrónica", "electro", "electronic music", "dance", "edm", "rock", "pop",
           "hip-hop", "hip hop", "hiphop", "rap", "metal", "jazz", "classical", "clásica", "clasica", "other", "otros",
           "otro", "unknown", "desconocido", "world", "latin", "latino", "alternative", "alternativo", "indie",
           "soundtrack", "banda sonora", "r&b", "rnb", "folk", "country", "blues", "reggae", "funk", "soul", "música",
           "music", "misc", "various", "genre", "género", "anime", "j-pop", "k-pop", "vocal", "instrumental"}
COMMON = ["Phonk", "Drift Phonk", "Melodic Techno", "Techno", "Tech House", "Deep House", "Progressive House",
          "Big Room", "Future House", "Bass House", "Dubstep", "Riddim", "Future Bass", "Drum & Bass", "Liquid Drum & Bass",
          "Trance", "Psytrance", "Hardstyle", "Synthwave", "Darkwave", "Lo-Fi Hip Hop", "Trap", "Boom Bap", "Drill",
          "Reguetón", "Dembow", "Latin Trap", "Cumbia", "Salsa", "Bachata", "Merengue", "Pop Latino", "Rock Latino",
          "Indie Pop", "Dream Pop", "Synth-pop", "Electropop", "K-Pop", "J-Pop", "J-Rock", "Anisong", "City Pop",
          "Alternative Rock", "Indie Rock", "Pop Rock", "Pop Punk", "Post-Rock", "Shoegaze", "Hard Rock", "Grunge",
          "Heavy Metal", "Metalcore", "Nu Metal", "Symphonic Metal", "Neo Soul", "Contemporary R&B", "Funk",
          "Smooth Jazz", "Bossa Nova", "Ambient", "Downtempo", "Chillout", "Trip Hop", "Orchestral", "Video Game Music"]
BAD_TAGS = {"seen live", "favorites", "favourite", "albums i own", "british", "american", "english", "japanese",
            "spanish", "male vocalists", "female vocalists", "usa", "uk", "german", "french", "love", "beautiful"}
UA = "MusicManager/genres (https://github.com/PandxMax/MusicManager)"


def norm(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)
    return re.sub(r"[^0-9a-z]+", " ", t).strip()


def is_generic(genre):
    parts = [norm(p) for p in re.split(r"[;/,|]", genre or "")]
    return all(p in {norm(g) for g in GENERIC} for p in parts)


def cache_path():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) or \
        os.path.join(os.path.expanduser("~"), ".musicmanager")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "generos_sugeridos.json")


def load_cache():
    try:
        with open(cache_path(), "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_cache(c):
    try:
        with open(cache_path(), "w", encoding="utf-8") as fh:
            json.dump(c, fh, ensure_ascii=False)
    except OSError:
        pass


# ============================================================ leer la biblioteca
class ScanWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(list)

    def __init__(self, files, read_tags, by_album):
        super().__init__()
        self.files, self.read_tags, self.by_album = files, read_tags, by_album

    def run(self):
        groups = {}
        for n, p in enumerate(self.files):
            if self.isInterruptionRequested():
                return
            if n % 25 == 0:
                self.progress.emit(n, len(self.files))
            try:
                t = self.read_tags(p)
            except Exception:
                t = {}
            artist = t.get("albumartist") or t.get("artist") or ""
            album = t.get("album") or ""
            if self.by_album and album:
                key = norm(artist) + "|" + norm(album)
                label = album
            else:
                key = "song|" + p
                label = t.get("title") or os.path.splitext(os.path.basename(p))[0]
            g = groups.setdefault(key, {"key": key, "label": label, "artist": artist, "album": album,
                                        "title": t.get("title", ""), "paths": [], "genres": set()})
            g["paths"].append(p)
            g["genres"].add(t.get("genre", "") or "")
        self.progress.emit(len(self.files), len(self.files))
        out = []
        for g in groups.values():
            g["genre"] = "; ".join(sorted(x for x in g["genres"] if x)) or ""
            out.append(g)
        out.sort(key=lambda g: (g["artist"].lower(), g["label"].lower()))
        self.done.emit(out)


# ============================================================ MusicBrainz (gratis, sin clave)
class MBWorker(QThread):
    found = pyqtSignal(str, str, list)   # clave, género sugerido, otras opciones
    progress = pyqtSignal(int, int)
    finished_all = pyqtSignal()

    def __init__(self, groups):
        super().__init__()
        self.groups = groups

    def get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    def run(self):
        for n, g in enumerate(self.groups):
            if self.isInterruptionRequested():
                break
            self.progress.emit(n, len(self.groups))
            try:
                if g["album"]:
                    q = f'releasegroup:"{g["album"]}"' + (f' AND artist:"{g["artist"]}"' if g["artist"] else "")
                    url = "https://musicbrainz.org/ws/2/release-group/?fmt=json&limit=5&query=" + urllib.parse.quote(q)
                    items = self.get(url).get("release-groups", [])
                    title_of = lambda it: it.get("title", "")
                else:
                    q = f'recording:"{g["title"] or g["label"]}"' + (f' AND artist:"{g["artist"]}"' if g["artist"] else "")
                    url = "https://musicbrainz.org/ws/2/recording/?fmt=json&limit=5&query=" + urllib.parse.quote(q)
                    items = self.get(url).get("recordings", [])
                    title_of = lambda it: it.get("title", "")
                tags = {}
                want_t, want_a = norm(g["album"] or g["title"] or g["label"]), norm(g["artist"])
                for it in items:
                    if norm(title_of(it)) != want_t:
                        continue
                    names = norm(" ".join(c.get("name", "") for c in it.get("artist-credit", []) if isinstance(c, dict)))
                    if want_a and want_a not in names and names not in want_a:
                        continue
                    for tg in it.get("tags", []) or []:
                        name = (tg.get("name") or "").strip()
                        if not name or name.lower() in BAD_TAGS or re.search(r"\d", name):
                            continue
                        tags[name] = tags.get(name, 0) + int(tg.get("count") or 1)
                ranked = sorted(tags.items(), key=lambda kv: -kv[1])
                specific = [k for k, _ in ranked if not is_generic(k)]
                options = [k.title() if k.islower() else k for k in (specific or [k for k, _ in ranked])][:6]
                self.found.emit(g["key"], options[0] if options else "", options)
            except Exception:
                self.found.emit(g["key"], "", [])
            time.sleep(1.1)   # MusicBrainz pide como máximo una consulta por segundo
        self.progress.emit(len(self.groups), len(self.groups))
        self.finished_all.emit()


# ============================================================ IA (solo para lo que falte), 25 álbumes por consulta
def make_ai_worker(AIBase):
    class AIGenreWorker(AIBase):
        found = pyqtSignal(str, str, list)
        progress = pyqtSignal(int, int)
        finished_all = pyqtSignal()

        def __init__(self, prov, model, key, groups):
            super().__init__(prov, model, key)
            self.groups = groups

        def run(self):
            import urllib.error
            batch = 25
            for start in range(0, len(self.groups), batch):
                if self.isInterruptionRequested():
                    break
                chunk = self.groups[start:start + batch]
                self.progress.emit(start, len(self.groups))
                lines = "\n".join(f'{i} | {g["artist"] or "?"} | {g["album"] or g["title"] or g["label"]} | {g["genre"] or "-"}'
                                  for i, g in enumerate(chunk))
                system = ("Eres un experto en géneros musicales. Respondes SOLO con un objeto JSON válido, sin texto extra.")
                prompt = ("Para cada línea (id | artista | álbum o canción | género actual) da el género o subgénero MÁS "
                          "ESPECÍFICO y conocido (por ejemplo «Melodic Techno», «Future Garage», «Drift Phonk», «Reguetón», "
                          "«J-Rock»). Usa el nombre más común del género (normalmente en inglés, salvo géneros latinos). "
                          "Si no conoces la obra, deja la cadena vacía: no inventes.\n"
                          'Devuelve {"0": ["Género principal", "alternativa 1", "alternativa 2"], "1": [...], ...}\n\n' + lines)
                try:
                    txt = self.chat([{"role": "user", "content": prompt}], system)
                    m = re.search(r"\{.*\}", txt, re.S)
                    data = json.loads(m.group(0)) if m else {}
                except urllib.error.HTTPError as e:
                    self.failed.emit(self.error_text(e))
                    break
                except Exception:
                    data = {}
                for i, g in enumerate(chunk):
                    v = data.get(str(i)) or []
                    if isinstance(v, str):
                        v = [v]
                    opts = [str(x).strip() for x in v if str(x).strip()]
                    self.found.emit(g["key"], opts[0] if opts else "", opts)
            self.progress.emit(len(self.groups), len(self.groups))
            self.finished_all.emit()
    return AIGenreWorker


# ============================================================ ventana
COL_NAME, COL_ARTIST, COL_N, COL_CUR, COL_NEW, COL_SRC = range(6)


class BatchGenresDialog(QDialog):
    def __init__(self, main, folder=None, paths=None, audio_ext=None, read_tags=None, ai_base=None):
        super().__init__(main)
        self.main, self.folder, self.paths = main, folder, paths
        self.audio_ext, self.read_tags, self.ai_base = audio_ext, read_tags, ai_base
        self.groups, self.items, self.worker = [], {}, None
        self.cache = load_cache()
        self.setWindowTitle("Géneros en lote")
        self.resize(1050, 640)
        v = QVBoxLayout(self)
        info = QLabel("Agrupa por álbum, encuentra los géneros demasiado generales («Electronic», «Rock»…) o vacíos y sugiere "
                      "géneros específicos. Primero MusicBrainz (gratis); la IA solo para lo que falte. Nada se cambia hasta "
                      "que pulses «Aplicar».")
        info.setWordWrap(True)
        v.addWidget(info)
        top = QHBoxLayout()
        self.scope = QComboBox()
        if paths:
            self.scope.addItem(T(f"Las {len(paths)} canciones seleccionadas"), "sel")
        if folder:
            name = os.path.basename(folder.rstrip("/\\")) or folder
            self.scope.addItem(T(f"Carpeta «{name}»"), "folder")
            self.scope.addItem(T(f"Carpeta «{name}» y sus subcarpetas"), "rec")
        top.addWidget(self.scope, 1)
        pick = QPushButton("📂 Elegir carpeta…")
        pick.setToolTip("Elige cualquier carpeta para revisar sus géneros")
        pick.clicked.connect(self.pick_folder)
        top.addWidget(pick)
        self.only_generic = QCheckBox("Solo géneros generales o vacíos")
        self.only_generic.setChecked(True)
        self.by_album = QCheckBox("Agrupar por álbum")
        self.by_album.setChecked(True)
        top.addWidget(self.only_generic)
        top.addWidget(self.by_album)
        self.go = QPushButton("🔍 Buscar")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.scan)
        top.addWidget(self.go)
        v.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([T("Álbum / canción"), T("Intérprete"), "#", T("Género actual"), T("Género nuevo"), T("Fuente")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(True)
        hd = self.tree.header()
        hd.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        for c, w in ((COL_ARTIST, 170), (COL_N, 40), (COL_CUR, 140), (COL_NEW, 190), (COL_SRC, 95)):
            hd.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
            hd.resizeSection(c, w)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(lambda it, col: self.tree.editItem(it, COL_NEW))
        self.tree.itemChanged.connect(self.on_changed)
        self.tree.itemSelectionChanged.connect(self.on_sel)
        v.addWidget(self.tree, 1)

        # poner un género a varios a la vez
        row = QHBoxLayout()
        row.addWidget(QLabel("Género para las filas elegidas:"))
        self.genre_cb = QComboBox()
        self.genre_cb.setEditable(True)
        self.genre_cb.addItems(COMMON)
        self.genre_cb.setCurrentText("")
        self.genre_cb.lineEdit().setPlaceholderText(T("escribe o elige un género…"))
        row.addWidget(self.genre_cb, 1)
        b_set = QPushButton("✔ Poner a las elegidas")
        b_set.clicked.connect(self.set_selected)
        row.addWidget(b_set)
        v.addLayout(row)

        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        self.b_mb = QPushButton("🎼 Sugerir con MusicBrainz (gratis)")
        self.b_ai = QPushButton("✨ Sugerir con IA (lo que falte)")
        self.b_stop = QPushButton("⏹ Parar")
        self.b_apply = QPushButton("✔ Aplicar (pendiente de guardar)")
        self.b_save = QPushButton("💾 Aplicar y guardar")
        self.b_save.setObjectName("accent")
        self.b_mb.clicked.connect(self.suggest_mb)
        self.b_ai.clicked.connect(self.suggest_ai)
        self.b_stop.clicked.connect(self.stop)
        self.b_apply.clicked.connect(lambda: self.apply(False))
        self.b_save.clicked.connect(lambda: self.apply(True))
        for b in (self.b_mb, self.b_ai, self.b_stop):
            br.addWidget(b)
        br.addStretch(1)
        br.addWidget(self.b_apply)
        br.addWidget(self.b_save)
        close = QPushButton("Cerrar")
        close.clicked.connect(self.close)
        br.addWidget(close)
        v.addLayout(br)
        self.set_busy(False)
        self.b_stop.setEnabled(False)

    # ------------------------------------------------------------ buscar
    def pick_folder(self):
        from PyQt6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, T("Carpeta para revisar los géneros"), self.folder or "")
        if not d:
            return
        self.folder = d
        self.scope.clear()
        name = os.path.basename(d.rstrip("/\\")) or d
        self.scope.addItem(T(f"Carpeta «{name}»"), "folder")
        self.scope.addItem(T(f"Carpeta «{name}» y sus subcarpetas"), "rec")
        self.scope.setCurrentIndex(1)
        self.tree.clear()
        self.groups = []
        self.status.setText(T("Pulsa «Buscar»."))

    def files(self):
        mode = self.scope.currentData()
        if mode == "sel":
            return list(self.paths)
        out = []
        if mode == "rec":
            for dp, _, fs in os.walk(self.folder):
                out += [os.path.join(dp, f) for f in fs if os.path.splitext(f)[1].lower() in self.audio_ext]
        else:
            try:
                out = [os.path.join(self.folder, f) for f in os.listdir(self.folder)
                       if os.path.splitext(f)[1].lower() in self.audio_ext]
            except OSError:
                pass
        return sorted(f for f in out if os.path.isfile(f))

    def set_busy(self, on, stoppable=False):
        for b in (self.go, self.b_mb, self.b_ai, self.b_apply, self.b_save):
            b.setEnabled(not on)
        self.b_stop.setEnabled(on and stoppable)
        self.bar.setVisible(on)

    def scan(self):
        files = self.files()
        if not files:
            self.status.setText(T("No hay canciones."))
            return
        self.set_busy(True)
        self.bar.setRange(0, len(files))
        self.status.setText(T("Leyendo las canciones…"))
        self.worker = ScanWorker(files, self.read_tags, self.by_album.isChecked())
        self.worker.progress.connect(lambda n, t: self.bar.setValue(n))
        self.worker.done.connect(self.show_groups)
        self.worker.start()

    def show_groups(self, groups):
        self.set_busy(False)
        if self.only_generic.isChecked():
            groups = [g for g in groups if is_generic(g["genre"])]
        self.groups = groups
        self.items = {}
        self.tree.setSortingEnabled(False)
        self.tree.blockSignals(True)
        self.tree.clear()
        for g in groups:
            it = QTreeWidgetItem([g["label"], g["artist"], str(len(g["paths"])), g["genre"] or "—", "", ""])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            it.setCheckState(COL_NAME, Qt.CheckState.Unchecked)
            it.setData(COL_NAME, Qt.ItemDataRole.UserRole, g["key"])
            it.setToolTip(COL_NAME, "\n".join(g["paths"][:12]) + ("\n…" if len(g["paths"]) > 12 else ""))
            self.tree.addTopLevelItem(it)
            self.items[g["key"]] = it
            c = self.cache.get(g["key"])
            if c and c.get("genre"):
                self.put(g["key"], c["genre"], c.get("options", []), c.get("src", ""), save=False)
        self.tree.blockSignals(False)
        self.tree.setSortingEnabled(True)
        self.update_count()

    # ------------------------------------------------------------ sugerencias
    def put(self, key, genre, options, src, save=True):
        it = self.items.get(key)
        if it is None:
            return
        if genre:
            it.setText(COL_NEW, genre)
            it.setText(COL_SRC, T(src))
            it.setCheckState(COL_NAME, Qt.CheckState.Checked)
            it.setToolTip(COL_NEW, T("Otras opciones: ") + ", ".join(options[1:]) if len(options) > 1 else "")
            if save:
                self.cache[key] = {"genre": genre, "options": options, "src": src}
        elif not it.text(COL_SRC):
            it.setText(COL_SRC, "—")

    def pending_groups(self, need_empty=True):
        out = []
        for g in self.groups:
            it = self.items.get(g["key"])
            if it is None:
                continue
            if need_empty and it.text(COL_NEW):
                continue
            out.append(g)
        return out

    def run_worker(self, w, label):
        self.worker = w
        self.set_busy(True, stoppable=True)
        self.bar.setRange(0, max(1, len(w.groups)))
        w.progress.connect(lambda n, t: (self.bar.setValue(n), self.status.setText(T(f"{label}: {n} de {t}…"))))
        w.found.connect(lambda k, g, o, src=("MusicBrainz" if isinstance(w, MBWorker) else "IA"): self.put(k, g, o, src))
        w.finished_all.connect(self.done_worker)
        if hasattr(w, "failed"):
            w.failed.connect(lambda msg: QMessageBox.warning(self, T("Error de IA"), msg))
        w.start()

    def suggest_mb(self):
        gs = self.pending_groups()
        if not gs:
            self.status.setText(T("No queda nada sin sugerencia."))
            return
        self.run_worker(MBWorker(gs), T("Consultando MusicBrainz"))

    def suggest_ai(self):
        gs = self.pending_groups()
        if not gs:
            self.status.setText(T("No queda nada sin sugerencia."))
            return
        settings = self.main.ai_settings()
        if not settings or self.ai_base is None:
            return
        cls = make_ai_worker(self.ai_base)
        self.run_worker(cls(*settings, gs), T("Preguntando a la IA"))

    def stop(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText(T("Parando… (lo ya encontrado se guarda)"))

    def done_worker(self):
        save_cache(self.cache)
        self.set_busy(False)
        self.update_count()

    # ------------------------------------------------------------ edición manual
    def on_changed(self, it, col):
        if col == COL_NEW:   # escrito a mano en la tabla
            self.tree.blockSignals(True)
            g = it.text(COL_NEW).strip()
            if g:
                it.setText(COL_SRC, T("Manual"))
                it.setCheckState(COL_NAME, Qt.CheckState.Checked)
                self.cache[it.data(COL_NAME, Qt.ItemDataRole.UserRole)] = {"genre": g, "options": [g], "src": "Manual"}
            self.tree.blockSignals(False)
        self.update_count()

    def on_sel(self):
        sel = self.tree.selectedItems()
        if len(sel) == 1 and sel[0].text(COL_NEW):
            self.genre_cb.setCurrentText(sel[0].text(COL_NEW))

    def set_selected(self):
        g = self.genre_cb.currentText().strip()
        sel = self.tree.selectedItems()
        if not g or not sel:
            self.status.setText(T("Elige filas en la tabla (Ctrl o Mayús para varias) y escribe o elige un género."))
            return
        for it in sel:
            it.setText(COL_NEW, g)
            it.setText(COL_SRC, T("Manual"))
            it.setCheckState(COL_NAME, Qt.CheckState.Checked)
            self.cache[it.data(COL_NAME, Qt.ItemDataRole.UserRole)] = {"genre": g, "options": [g], "src": "Manual"}
        save_cache(self.cache)
        self.update_count()

    def update_count(self):
        n = self.tree.topLevelItemCount()
        ok = [self.tree.topLevelItem(i) for i in range(n)]
        marked = [it for it in ok if it.checkState(COL_NAME) == Qt.CheckState.Checked and it.text(COL_NEW).strip()]
        songs = sum(int(it.text(COL_N) or 0) for it in marked)
        sug = sum(1 for it in ok if it.text(COL_NEW).strip())
        if n:
            self.status.setText(T(f"{n} grupos · {sug} con sugerencia · {len(marked)} marcados para cambiar ({songs} canciones). "
                                  f"Doble clic en «Género nuevo» para escribirlo a mano."))
        else:
            self.status.setText(T("No hay géneros que afinar con estos filtros."))

    # ------------------------------------------------------------ aplicar
    def apply(self, save):
        groups = {g["key"]: g for g in self.groups}
        changes = 0
        self.main.apply_form()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            genre = it.text(COL_NEW).strip()
            if it.checkState(COL_NAME) != Qt.CheckState.Checked or not genre:
                continue
            g = groups.get(it.data(COL_NAME, Qt.ItemDataRole.UserRole))
            for p in (g["paths"] if g else []):
                self.main.pending.setdefault(p, {})["genre"] = genre
                changes += 1
        if not changes:
            self.status.setText(T("No hay nada marcado con un género nuevo."))
            return
        save_cache(self.cache)
        self.main.mark_items()
        self.main.on_select()
        if save:
            self.main.save_all()
            self.status.setText(T(f"✔ Género guardado en {changes} canción(es)."))
        else:
            self.status.setText(T(f"✔ Género puesto en {changes} canción(es) (pendiente de guardar, en naranja)."))

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(3000)
        save_cache(self.cache)
        super().closeEvent(e)

"""Herramienta Navidrome: conectar con tu servidor (API Subsonic), pedirle que vuelva a leer la biblioteca,
revisar qué se verá mal allí y ver tus canciones más escuchadas y favoritas.

La contraseña nunca se guarda: se guarda solo el «token» de la API Subsonic (md5 de contraseña + sal), en los
ajustes locales del programa (no en el repositorio)."""
import os, re, json, hashlib, secrets, urllib.request, urllib.parse, urllib.error
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QCheckBox, QTabWidget,
                             QWidget, QTreeWidget, QTreeWidgetItem, QProgressBar, QFormLayout, QComboBox, QMessageBox,
                             QApplication, QHeaderView)
from i18n import tr as T

CLIENT = "MusicManager"
API_V = "1.16.1"


# ------------------------------------------------------------------ API Subsonic
def creds(cfg):
    return (str(cfg.value("navi_url", "") or "").strip().rstrip("/"), str(cfg.value("navi_user", "") or "").strip(),
            str(cfg.value("navi_token", "") or ""), str(cfg.value("navi_salt", "") or ""))


def call(cfg, method, timeout=15, **params):
    url, user, token, salt = creds(cfg)
    if not (url and user and token):
        raise RuntimeError(T("Primero conecta tu servidor en la pestaña «Conexión»."))
    q = {"u": user, "t": token, "s": salt, "v": API_V, "c": CLIENT, "f": "json"}
    q.update({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(f"{url}/rest/{method}?" + urllib.parse.urlencode(q),
                                 headers={"User-Agent": f"{CLIENT}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{T('El servidor respondió')} {e.code} ({e.reason})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RuntimeError(f"{T('No se pudo conectar con')} {url} ({getattr(e, 'reason', e)})")
    except ValueError:
        raise RuntimeError(T("La dirección no parece un servidor Navidrome / Subsonic."))
    resp = data.get("subsonic-response") or {}
    if resp.get("status") != "ok":
        err = resp.get("error") or {}
        msg = err.get("message") or T("error desconocido")
        if err.get("code") in (40, 41):
            msg = T("Usuario o contraseña incorrectos.")
        raise RuntimeError(msg)
    return resp


class ApiWorker(QThread):
    done = pyqtSignal(str, object, str)   # tarea, resultado, error

    def __init__(self, cfg, task, fn):
        super().__init__()
        self.cfg, self.task, self.fn = cfg, task, fn

    def run(self):
        try:
            self.done.emit(self.task, self.fn(), "")
        except Exception as e:
            self.done.emit(self.task, None, str(e))


def start_scan(cfg):
    return call(cfg, "startScan").get("scanStatus") or {}


def scan_in_background(main):
    """Tras guardar cambios (si está activado): pide al servidor que vuelva a leer la biblioteca, sin esperar."""
    if not int(main.cfg.value("navi_autoscan", 0) or 0) or not creds(main.cfg)[2]:
        return
    w = ApiWorker(main.cfg, "scan", lambda: start_scan(main.cfg))
    w.done.connect(lambda _t, _r, err: main.statusBar().showMessage(
        T("Navidrome: no se pudo pedir el escaneo: ") + err if err else T("Navidrome está releyendo la biblioteca."), 5000))
    keep = getattr(main, "_navi_workers", set())
    keep.add(w)
    main._navi_workers = keep
    w.finished.connect(lambda w=w: keep.discard(w))
    w.start()


# ------------------------------------------------------------------ revisión local
GENERIC = {"", "electronic", "electronica", "electrónica", "dance", "pop", "rock", "latin", "latin music", "latina",
           "música latina", "other", "otros", "unknown", "desconocido", "music", "música", "various", "soundtrack"}
ISSUES = [
    ("split", "Álbumes que Navidrome partirá en varios (falta o cambia el «Intérprete del álbum»)"),
    ("years", "Álbumes con años distintos entre sus canciones"),
    ("track", "Canciones sin número de pista (el álbum sale desordenado)"),
    ("disc", "Pistas repetidas en el mismo álbum sin «Número de disco»"),
    ("noalbum", "Canciones sin álbum (van a «[Unknown Album]»)"),
    ("noartist", "Canciones sin intérprete o sin título"),
    ("nocover", "Sin portada (ni en el archivo ni cover.jpg en la carpeta)"),
    ("smallcover", "Portada pequeña (menos de 500 px: se ve borrosa en el celular)"),
    ("genre", "Sin género o con un género demasiado general"),
]


class CheckWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(dict, int)

    def __init__(self, files, read_tags, inspect_file, folder_image):
        super().__init__()
        self.files, self.read_tags, self.inspect_file, self.folder_image = files, read_tags, inspect_file, folder_image

    def run(self):
        res = {k: [] for k, _ in ISSUES}
        albums = {}
        n = len(self.files)
        for i, p in enumerate(self.files):
            if self.isInterruptionRequested():
                return
            if i % 10 == 0:
                self.progress.emit(i, n)
            try:
                t = self.read_tags(p)
                d = self.inspect_file(p)
            except Exception:
                continue
            artist, title, album = t.get("artist", ""), t.get("title", ""), t.get("album", "")
            if not artist or not title:
                res["noartist"].append((p, ""))
            if not album:
                res["noalbum"].append((p, ""))
            else:
                albums.setdefault((os.path.dirname(p), album.strip().lower()), []).append((p, t))
            if not re.match(r"\s*\d", t.get("tracknumber", "") or ""):
                res["track"].append((p, ""))
            g = (t.get("genre", "") or "").strip().lower()
            if g in GENERIC:
                res["genre"].append((p, t.get("genre", "") or T("vacío")))
            cov = d.get("cover")
            if not cov:
                if not self.folder_image(os.path.dirname(p)):
                    res["nocover"].append((p, ""))
            else:
                img = QImage.fromData(cov)
                if not img.isNull() and max(img.width(), img.height()) < 500:
                    res["smallcover"].append((p, f"{img.width()}×{img.height()}"))
        for (_d, _a), songs in albums.items():
            if len(songs) < 2:
                continue
            aa = {(t.get("albumartist") or "").strip().lower() for _p, t in songs}
            arts = {(t.get("artist") or "").strip().lower() for _p, t in songs}
            if len(aa) > 1 or ("" in aa and len(arts) > 1):
                why = T("intérpretes distintos sin «Intérprete del álbum» común")
                res["split"] += [(p, why) for p, _t in songs]
            years = {(t.get("date") or "")[:4] for _p, t in songs} - {""}
            if len(years) > 1:
                res["years"] += [(p, ", ".join(sorted(years))) for p, _t in songs]
            seen, dup = {}, False
            for p, t in songs:
                m = re.match(r"\s*(\d+)", t.get("tracknumber", "") or "")
                if m:
                    k = (m.group(1).lstrip("0"), (t.get("discnumber") or "").strip())
                    dup = dup or k in seen
                    seen[k] = p
            if dup and not any((t.get("discnumber") or "").strip() for _p, t in songs):
                res["disc"] += [(p, "") for p, _t in songs]
        self.progress.emit(n, n)
        self.done.emit(res, n)


# ------------------------------------------------------------------ ventana
class NavidromeDialog(QDialog):
    def __init__(self, main, folder, audio_ext, read_tags, inspect_file, folder_image):
        super().__init__(main)
        self.main, self.cfg = main, main.cfg
        self.folder, self.audio_ext = folder, audio_ext
        self.read_tags, self.inspect_file, self.folder_image = read_tags, inspect_file, folder_image
        self.workers = set()
        self.setWindowTitle("Navidrome")
        self.resize(940, 660)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        try:
            from picard_tools import dialog_header
            dialog_header(v, "📡 Navidrome", T("Tu servidor de música: actualizar la biblioteca, revisar lo que se verá mal "
                                               "y ver lo que más escuchas."))
        except Exception:
            pass
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        self.tabs.addTab(self.build_conn(), T("🔌 Conexión"))
        self.tabs.addTab(self.build_check(), T("🩺 Revisión para Navidrome"))
        self.tabs.addTab(self.build_stats(), T("📈 Más escuchadas y favoritas"))
        br = QHBoxLayout()
        br.addStretch(1)
        close = QPushButton(T("Cerrar"))
        close.clicked.connect(self.close)
        br.addWidget(close)
        v.addLayout(br)
        if not creds(self.cfg)[2]:
            self.tabs.setCurrentIndex(0)
        else:
            self.tabs.setCurrentIndex(1)

    def run_api(self, task, fn, on_done):
        w = ApiWorker(self.cfg, task, fn)
        w.done.connect(lambda t, r, e: on_done(r, e))
        w.finished.connect(lambda w=w: self.workers.discard(w))
        self.workers.add(w)
        w.start()

    # ---------------------------------------------------------- conexión
    def build_conn(self):
        page = QWidget()
        v = QVBoxLayout(page)
        info = QLabel(T("Navidrome es tu propio servidor de música: escuchas tu biblioteca desde el celular o el navegador. "
                        "Escribe la dirección de tu servidor (por ejemplo http://192.168.1.10:4533), tu usuario y tu "
                        "contraseña. La contraseña no se guarda: solo un código de acceso (token)."))
        info.setWordWrap(True)
        v.addWidget(info)
        f = QFormLayout()
        url, user, token, _salt = creds(self.cfg)
        self.url_le = QLineEdit(url)
        self.url_le.setPlaceholderText("http://localhost:4533")
        self.user_le = QLineEdit(user)
        self.pass_le = QLineEdit()
        self.pass_le.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_le.setPlaceholderText(T("(ya guardada)") if token else "")
        f.addRow(T("Dirección del servidor"), self.url_le)
        f.addRow(T("Usuario"), self.user_le)
        f.addRow(T("Contraseña"), self.pass_le)
        v.addLayout(f)
        self.auto = QCheckBox(T("Avisar a Navidrome que relea la biblioteca cada vez que guardo cambios"))
        self.auto.setChecked(bool(int(self.cfg.value("navi_autoscan", 0) or 0)))
        self.auto.toggled.connect(lambda on: self.cfg.setValue("navi_autoscan", 1 if on else 0))
        v.addWidget(self.auto)
        row = QHBoxLayout()
        test = QPushButton(T("💾 Guardar y probar conexión"))
        test.setObjectName("accent")
        test.clicked.connect(self.save_and_test)
        self.scan_btn = QPushButton(T("🔄 Actualizar biblioteca ahora"))
        self.scan_btn.setToolTip(T("Pide a Navidrome que vuelva a leer tus carpetas (para ver ya los cambios que guardaste)"))
        self.scan_btn.clicked.connect(self.scan_now)
        forget = QPushButton(T("Olvidar servidor"))
        forget.clicked.connect(self.forget)
        for b in (test, self.scan_btn, forget):
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        self.conn_status = QLabel("")
        self.conn_status.setWordWrap(True)
        v.addWidget(self.conn_status)
        v.addStretch(1)
        return page

    def save_and_test(self):
        url = self.url_le.text().strip().rstrip("/")
        if url and not re.match(r"^https?://", url, re.I):
            url = "http://" + url
            self.url_le.setText(url)
        user, pw = self.user_le.text().strip(), self.pass_le.text()
        if not url or not user:
            self.conn_status.setText(T("Escribe la dirección y el usuario."))
            return
        self.cfg.setValue("navi_url", url)
        self.cfg.setValue("navi_user", user)
        if pw:   # solo se guarda el token (md5 de contraseña + sal), nunca la contraseña
            salt = secrets.token_hex(8)
            self.cfg.setValue("navi_salt", salt)
            self.cfg.setValue("navi_token", hashlib.md5((pw + salt).encode("utf-8")).hexdigest())
            self.pass_le.clear()
            self.pass_le.setPlaceholderText(T("(ya guardada)"))
        self.conn_status.setText(T("Probando…"))

        def test():
            r = call(self.cfg, "ping")
            st = call(self.cfg, "getScanStatus").get("scanStatus") or {}
            return r.get("serverVersion") or r.get("type") or "", st.get("count")

        def shown(res, err):
            if err:
                self.conn_status.setText("❌ " + err)
                return
            ver, count = res
            txt = "✅ " + T("Conectado") + (f" · Navidrome {ver}" if ver else "")
            if count is not None:
                txt += " · " + T(f"{count} canciones en el servidor")
            self.conn_status.setText(txt)
        self.run_api("test", test, shown)

    def scan_now(self):
        self.conn_status.setText(T("Pidiendo a Navidrome que relea la biblioteca…"))
        self.run_api("scan", lambda: start_scan(self.cfg), lambda r, e: self.conn_status.setText(
            "❌ " + e if e else "✅ " + T("Navidrome está releyendo la biblioteca. En unos minutos verás los cambios.")))

    def forget(self):
        for k in ("navi_url", "navi_user", "navi_token", "navi_salt"):
            self.cfg.remove(k)
        self.url_le.clear()
        self.user_le.clear()
        self.pass_le.clear()
        self.pass_le.setPlaceholderText("")
        self.conn_status.setText(T("Servidor olvidado."))

    # ---------------------------------------------------------- revisión
    def build_check(self):
        page = QWidget()
        v = QVBoxLayout(page)
        info = QLabel(T("Revisa tus archivos (no hace falta servidor) y te dice lo que se verá mal en Navidrome: "
                        "álbumes partidos, sin portada, sin número de pista… Doble clic en una canción para ir a ella y arreglarla."))
        info.setWordWrap(True)
        v.addWidget(info)
        row = QHBoxLayout()
        self.check_where = QLabel(self.folder or "")
        self.check_where.setObjectName("hint")
        row.addWidget(self.check_where, 1)
        self.check_btn = QPushButton(T("🩺 Revisar esta carpeta (con subcarpetas)"))
        self.check_btn.setObjectName("accent")
        self.check_btn.clicked.connect(self.start_check)
        row.addWidget(self.check_btn)
        v.addLayout(row)
        self.check_bar = QProgressBar()
        self.check_bar.hide()
        v.addWidget(self.check_bar)
        self.check_tree = QTreeWidget()
        self.check_tree.setHeaderLabels([T("Problema / canción"), T("Detalle")])
        self.check_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.check_tree.itemDoubleClicked.connect(self.open_item)
        v.addWidget(self.check_tree, 1)
        self.check_status = QLabel("")
        v.addWidget(self.check_status)
        return page

    def start_check(self):
        if not self.folder or not os.path.isdir(self.folder):
            self.check_status.setText(T("Abre primero una carpeta de música."))
            return
        files = []
        for dp, _, fs in os.walk(self.folder):
            files += [os.path.join(dp, f) for f in fs if os.path.splitext(f)[1].lower() in self.audio_ext]
        if not files:
            self.check_status.setText(T("No hay canciones en esta carpeta."))
            return
        self.check_btn.setEnabled(False)
        self.check_bar.setRange(0, len(files))
        self.check_bar.show()
        w = CheckWorker(files, self.read_tags, self.inspect_file, self.folder_image)
        w.progress.connect(lambda i, n: self.check_bar.setValue(i))
        w.done.connect(self.check_done)
        w.finished.connect(lambda w=w: self.workers.discard(w))
        self.workers.add(w)
        w.start()

    def check_done(self, res, total):
        self.check_btn.setEnabled(True)
        self.check_bar.hide()
        self.check_tree.clear()
        bad = set()
        for key, label in ISSUES:
            items = res.get(key) or []
            if not items:
                continue
            top = QTreeWidgetItem([f"{T(label)}  ({len(items)})", ""])
            for p, detail in items[:2000]:
                ch = QTreeWidgetItem([os.path.relpath(p, self.folder), detail])
                ch.setData(0, Qt.ItemDataRole.UserRole, p)
                ch.setToolTip(0, p)
                top.addChild(ch)
                bad.add(p)
            self.check_tree.addTopLevelItem(top)
        self.check_status.setText(
            T(f"{total} canciones revisadas · {len(bad)} con algo que arreglar.") if bad
            else "✅ " + T(f"{total} canciones revisadas: todo se verá bien en Navidrome."))

    def open_item(self, it, _col=0):
        p = it.data(0, Qt.ItemDataRole.UserRole)
        if p and os.path.exists(p):
            self.main.reveal_file(p)

    # ---------------------------------------------------------- estadísticas
    def build_stats(self):
        page = QWidget()
        v = QVBoxLayout(page)
        row = QHBoxLayout()
        self.stats_kind = QComboBox()
        self.stats_kind.addItem(T("Canciones más escuchadas"), "plays")
        self.stats_kind.addItem(T("Canciones favoritas (⭐)"), "starred")
        self.stats_kind.addItem(T("Álbumes más escuchados"), "frequent")
        self.stats_kind.addItem(T("Álbumes escuchados hace poco"), "recent")
        row.addWidget(self.stats_kind, 1)
        load = QPushButton(T("Cargar desde Navidrome"))
        load.setObjectName("accent")
        load.clicked.connect(self.load_stats)
        row.addWidget(load)
        v.addLayout(row)
        self.stats_tree = QTreeWidget()
        self.stats_tree.setHeaderLabels([T("Título / álbum"), T("Intérprete"), T("Reproducciones")])
        self.stats_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.stats_tree.itemDoubleClicked.connect(self.find_local)
        v.addWidget(self.stats_tree, 1)
        self.stats_status = QLabel(T("Doble clic en una canción para buscarla en el programa."))
        self.stats_status.setWordWrap(True)
        v.addWidget(self.stats_status)
        return page

    def load_stats(self):
        kind = self.stats_kind.currentData()
        self.stats_status.setText(T("Cargando…"))

        def fetch():
            if kind == "plays":   # todas las canciones (por tandas) y se ordenan por reproducciones
                songs, off = [], 0
                while off < 20000:
                    r = call(self.cfg, "search3", timeout=30, query="", songCount=500, songOffset=off,
                             artistCount=0, albumCount=0)
                    part = (r.get("searchResult3") or {}).get("song") or []
                    songs += part
                    if len(part) < 500:
                        break
                    off += 500
                songs = [s for s in songs if s.get("playCount")]
                songs.sort(key=lambda s: -int(s.get("playCount") or 0))
                return ("song", songs[:300])
            if kind == "starred":
                r = call(self.cfg, "getStarred2")
                return ("song", (r.get("starred2") or {}).get("song") or [])
            r = call(self.cfg, "getAlbumList2", type=kind, size=100)
            return ("album", (r.get("albumList2") or {}).get("album") or [])

        def shown(res, err):
            self.stats_tree.clear()
            if err:
                self.stats_status.setText("❌ " + err)
                return
            what, rows = res
            for s in rows:
                name = s.get("title") if what == "song" else s.get("name")
                it = QTreeWidgetItem([name or "", s.get("artist") or "", str(s.get("playCount") or "")])
                it.setData(0, Qt.ItemDataRole.UserRole, (what, s.get("title") or s.get("name") or "", s.get("artist") or ""))
                self.stats_tree.addTopLevelItem(it)
            self.stats_status.setText(T(f"{len(rows)} resultados. Doble clic para buscarla en el programa.") if rows
                                      else T("No hay datos todavía (escucha algo en Navidrome primero)."))
        self.run_api("stats", fetch, shown)

    def find_local(self, it, _col=0):
        d = it.data(0, Qt.ItemDataRole.UserRole)
        if not d:
            return
        _what, name, _artist = d
        try:
            self.main.search.setText(name)   # filtra la lista del programa por ese nombre
            self.main.raise_()
            self.main.activateWindow()
        except Exception:
            pass

    def closeEvent(self, e):
        for w in list(self.workers):
            w.requestInterruption()
            w.wait(3000)
        super().closeEvent(e)

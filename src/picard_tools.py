"""Ideas de MusicBrainz Picard dentro de Music Manager:

1. Identificar por sonido (AcoustID): reconoce la canción escuchándola, aunque no tenga nombre ni etiquetas.
   Usa «fpcalc» (Chromaprint, ~1,5 MB), que se descarga solo la primera vez, y una clave gratuita de AcoustID.
2. Emparejar un álbum completo con MusicBrainz: busca el lanzamiento, coloca cada archivo en su pista
   (título, número de pista y de disco, año, intérprete del álbum), guarda los IDs de MusicBrainz y la portada
   del Cover Art Archive."""
import os, re, sys, json, time, zipfile, hashlib, tempfile, shutil, subprocess, difflib, unicodedata
import urllib.request, urllib.parse, urllib.error
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QStandardPaths, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit, QCheckBox, QComboBox,
                             QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QMessageBox, QAbstractItemView,
                             QFrame, QWidget)


def dialog_header(v, title, subtitle):
    """Cabecera de las ventanas: título grande y una línea de explicación en gris."""
    t = QLabel(title)
    t.setObjectName("dlgtitle")
    sub = QLabel(subtitle)
    sub.setObjectName("dlgsub")
    sub.setWordWrap(True)
    v.addWidget(t)
    v.addWidget(sub)
    v.addSpacing(4)


def nice_table(tb):
    tb.setShowGrid(False)
    tb.setAlternatingRowColors(True)
    tb.verticalHeader().setDefaultSectionSize(34)
from i18n import tr as T

UA = "MusicManager/1.96 ( https://github.com/PandxMax/MusicManager )"
FP_URL = "https://github.com/acoustid/chromaprint/releases/download/v1.5.1/chromaprint-fpcalc-1.5.1-windows-x86_64.zip"
FP_SHA256 = "36b478e16aa69f757f376645db0d436073a42c0097b6bb2677109e7835b59bbc"
MB_KEYS = {"musicbrainz_trackid", "musicbrainz_releasetrackid", "musicbrainz_albumid", "musicbrainz_releasegroupid",
           "musicbrainz_artistid", "musicbrainz_albumartistid", "acoustid_id"}


def norm(t):
    t = unicodedata.normalize("NFKD", (t or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[\(\[].*?[\)\]]", " ", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def credit(ac):
    return "".join((c.get("name") or (c.get("artist") or {}).get("name") or "") + (c.get("joinphrase") or "")
                   for c in (ac or [])).strip()


def http_json(url, data=None, timeout=25):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
    last = ""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            try:   # AcoustID responde los errores (p. ej. clave no válida) en JSON con código 400
                body = json.loads(e.read().decode("utf-8"))
                if isinstance(body, dict) and body.get("status") == "error":
                    return body
            except Exception:
                pass
            last = f"{e.code} {e.reason}"
            if e.code not in (429, 500, 502, 503, 504):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(getattr(e, "reason", e))
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(T("No se pudo conectar: ") + last)


def http_bytes(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


# ================================================================== fpcalc (huella acústica)
def tools_dir():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) or \
        os.path.join(os.path.expanduser("~"), ".musicmanager")
    return os.path.join(base, "chromaprint")


def fpcalc_exe():
    name = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"
    here = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
    for p in (os.path.join(here, name), os.path.join(tools_dir(), name)):   # viene incluido junto al programa
        if os.path.isfile(p):
            return p
    return shutil.which("fpcalc")


class FpDownload(QThread):
    done = pyqtSignal(bool, str)

    def run(self):
        tmp = None
        try:
            if sys.platform != "win32":
                raise RuntimeError(T("Instala «fpcalc» (chromaprint) con tu gestor de paquetes."))
            d = tools_dir()
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(suffix=".zip")
            os.close(fd)
            data = http_bytes(FP_URL, 60)
            if hashlib.sha256(data).hexdigest() != FP_SHA256:
                raise RuntimeError(T("El archivo descargado no es el esperado (no se instaló por seguridad)."))
            with open(tmp, "wb") as fh:
                fh.write(data)
            with zipfile.ZipFile(tmp) as z:
                for name in z.namelist():
                    if name.lower().endswith("fpcalc.exe"):
                        with z.open(name) as src, open(os.path.join(d, "fpcalc.exe"), "wb") as out:
                            shutil.copyfileobj(src, out)
            self.done.emit(bool(fpcalc_exe()), "" if fpcalc_exe() else T("No se encontró fpcalc en el archivo."))
        except Exception as e:
            self.done.emit(False, str(e))
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def fingerprint(path):
    flags = 0x08000000 if sys.platform == "win32" else 0   # sin ventana negra
    r = subprocess.run([fpcalc_exe(), "-json", "-length", "120", path], capture_output=True, timeout=90,
                       creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError(T("No se pudo analizar el audio."))
    d = json.loads(r.stdout.decode("utf-8", "replace"))
    return int(d.get("duration") or 0), d.get("fingerprint") or ""


class AcoustWorker(QThread):
    one = pyqtSignal(str, list, str)   # ruta, candidatos, error
    progress = pyqtSignal(int, int)

    def __init__(self, paths, key):
        super().__init__()
        self.paths, self.key = paths, key

    def run(self):
        n = len(self.paths)
        for i, p in enumerate(self.paths):
            if self.isInterruptionRequested():
                return
            self.progress.emit(i, n)
            try:
                dur, fp = fingerprint(p)
                body = urllib.parse.urlencode({"client": self.key, "meta": "recordings releasegroups compress",
                                               "duration": dur, "fingerprint": fp, "format": "json"}).encode()
                d = http_json("https://api.acoustid.org/v2/lookup", data=body) or {}
                if d.get("status") != "ok":
                    msg = (d.get("error") or {}).get("message") or T("error de AcoustID")
                    if "invalid" in msg.lower() and "key" in msg.lower():
                        msg = T("La clave de AcoustID no es válida.")
                    raise RuntimeError(msg)
                cands = []
                for res in d.get("results") or []:
                    for rec in res.get("recordings") or []:
                        if not rec.get("title"):
                            continue
                        rgs = rec.get("releasegroups") or []
                        rgs.sort(key=lambda g: (g.get("type") != "Album", bool(g.get("secondarytypes"))))
                        rg = rgs[0] if rgs else {}
                        arts = rec.get("artists") or []
                        cands.append({"score": float(res.get("score") or 0), "acoustid": res.get("id", ""),
                                      "title": rec.get("title", ""), "artist": credit(arts),
                                      "artist_id": arts[0].get("id", "") if arts else "",
                                      "album": rg.get("title", ""), "rg_id": rg.get("id", ""), "rec_id": rec.get("id", "")})
                seen, uniq = set(), []
                for c in sorted(cands, key=lambda c: -c["score"]):
                    k = (norm(c["title"]), norm(c["artist"]), norm(c["album"]))
                    if k not in seen:
                        seen.add(k)
                        uniq.append(c)
                self.one.emit(p, uniq[:8], "")
            except Exception as e:
                self.one.emit(p, [], str(e))
            time.sleep(0.35)   # AcoustID permite ~3 consultas por segundo
        self.progress.emit(n, n)


class AcoustIdDialog(QDialog):
    def __init__(self, main, paths):
        super().__init__(main)
        self.main, self.paths = main, list(paths)
        self.cands, self.worker, self.dl = {}, None, None
        self.setWindowTitle(T("Identificar por sonido (AcoustID)"))
        self.resize(1000, 600)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        dialog_header(v, T("🎧 Identificar por sonido"),
                      T("Reconoce cada canción escuchando su audio (como Shazam), aunque el archivo no tenga nombre ni "
                        "etiquetas. Elige el resultado correcto en cada fila y pulsa «Poner estos datos»."))
        # clave: si ya está guardada solo se ve una línea discreta con «Cambiar»
        self.key_ok = QFrame()
        self.key_ok.setObjectName("keyok")
        ko = QHBoxLayout(self.key_ok)
        ko.setContentsMargins(12, 6, 8, 6)
        self.key_ok_lbl = QLabel("")
        ko.addWidget(self.key_ok_lbl, 1)
        chg = QPushButton(T("Cambiar"))
        chg.setObjectName("link")
        chg.setCursor(Qt.CursorShape.PointingHandCursor)
        chg.clicked.connect(lambda: self.show_key_editor(True))
        ko.addWidget(chg)
        v.addWidget(self.key_ok)
        self.key_card = QFrame()
        self.key_card.setObjectName("card")
        kc = QVBoxLayout(self.key_card)
        kc.setContentsMargins(14, 12, 14, 12)
        kt = QLabel(T("<b>Clave de AcoustID</b> · gratis, solo se pone una vez"))
        kc.addWidget(kt)
        kh = QLabel(T("Pulsa «Conseguir clave gratis», inicia sesión en acoustid.org, registra una aplicación "
                      "(por ejemplo «Music Manager») y pega aquí la clave que te dan."))
        kh.setObjectName("dlgsub")
        kh.setWordWrap(True)
        kc.addWidget(kh)
        kr = QHBoxLayout()
        self.key = QLineEdit(str(main.cfg.value("acoustid_key", "") or ""))
        self.key.setPlaceholderText(T("pega aquí tu clave gratuita"))
        self.key.returnPressed.connect(self.save_key)
        kr.addWidget(self.key, 1)
        get = QPushButton(T("Conseguir clave gratis"))
        get.setToolTip(T("Entra en acoustid.org, inicia sesión y registra una aplicación: te dan la clave al momento"))
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://acoustid.org/new-application")))
        kr.addWidget(get)
        save = QPushButton(T("Guardar clave"))
        save.setObjectName("accent")
        save.clicked.connect(self.save_key)
        kr.addWidget(save)
        kc.addLayout(kr)
        v.addWidget(self.key_card)
        self.show_key_editor(not self.key.text().strip())
        self.tb = QTableWidget(len(self.paths), 3)
        self.tb.setHorizontalHeaderLabels([T("Archivo"), T("Resultado (seguridad · título · intérprete · álbum)"), T("Estado")])
        self.tb.verticalHeader().setVisible(False)
        self.tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self.tb.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tb.setColumnWidth(0, 300)
        nice_table(self.tb)
        self.combos = {}
        for r, p in enumerate(self.paths):
            self.tb.setItem(r, 0, QTableWidgetItem(os.path.basename(p)))
            cb = QComboBox()
            cb.addItem(T("(esperando)"), None)
            cb.setEnabled(False)
            self.tb.setCellWidget(r, 1, cb)
            self.tb.setItem(r, 2, QTableWidgetItem(""))
            self.combos[p] = (r, cb)
        v.addWidget(self.tb, 1)
        self.bar = QProgressBar()
        self.bar.hide()
        v.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        self.ids = QCheckBox(T("Guardar también los IDs de MusicBrainz (Navidrome y otros agrupan mejor)"))
        self.ids.setChecked(True)
        br.addWidget(self.ids)
        br.addStretch(1)
        self.go = QPushButton(T("🎧 Identificar"))
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.start)
        self.apply_btn = QPushButton(T("✔ Poner estos datos"))
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton(T("Cerrar"))
        close.clicked.connect(self.close)
        for b in (self.go, self.apply_btn, close):
            br.addWidget(b)
        v.addLayout(br)

    def show_key_editor(self, on):
        k = self.key.text().strip()
        self.key_card.setVisible(on)
        self.key_ok.setVisible(not on and bool(k))
        self.key_ok_lbl.setText("🔑  " + T("Clave de AcoustID guardada") + (f"  ·  ••••{k[-4:]}" if len(k) >= 4 else ""))
        if on:
            self.key.setFocus()

    def save_key(self):
        k = self.key.text().strip()
        if not k:
            self.key.setFocus()
            return
        self.main.cfg.setValue("acoustid_key", k)
        self.show_key_editor(False)

    def start(self):
        key = self.key.text().strip()
        if not key:
            self.show_key_editor(True)
            self.status.setText(T("Falta la clave de AcoustID. Pulsa «Conseguir clave gratis», regístrate y pégala aquí."))
            return
        self.main.cfg.setValue("acoustid_key", key)
        self.show_key_editor(False)
        if not fpcalc_exe():
            self.status.setText(T("Descargando el analizador de audio (fpcalc, 1,5 MB, solo la primera vez)…"))
            self.go.setEnabled(False)
            self.dl = FpDownload()
            self.dl.done.connect(lambda ok, err: (self.go.setEnabled(True),
                                                  self.start() if ok else self.status.setText("❌ " + err)))
            self.dl.start()
            return
        self.go.setEnabled(False)
        self.bar.setRange(0, len(self.paths))
        self.bar.show()
        self.status.setText(T("Escuchando las canciones…"))
        self.worker = AcoustWorker(self.paths, key)
        self.worker.progress.connect(lambda i, n: self.bar.setValue(i))
        self.worker.one.connect(self.got)
        self.worker.finished.connect(self.finished_all)
        self.worker.start()

    def got(self, path, cands, err):
        r, cb = self.combos[path]
        cb.clear()
        self.cands[path] = cands
        if err:
            cb.addItem("—", None)
            self.tb.item(r, 2).setText("❌ " + err)
            if err == T("La clave de AcoustID no es válida."):
                self.show_key_editor(True)
                self.status.setText("❌ " + err + " " + T("Revisa que la copiaste completa."))
            return
        if not cands:
            cb.addItem(T("(no reconocida)"), None)
            self.tb.item(r, 2).setText(T("Sin resultados"))
            return
        for c in cands:
            cb.addItem(f"{int(c['score'] * 100)}%  ·  {c['title']}  ·  {c['artist']}" + (f"  ·  {c['album']}" if c["album"] else ""), c)
        cb.addItem(T("(no cambiar esta canción)"), None)
        cb.setEnabled(True)
        self.tb.item(r, 2).setText("✅" if cands[0]["score"] >= 0.8 else T("revisa"))

    def finished_all(self):
        self.bar.hide()
        self.go.setEnabled(True)
        self.apply_btn.setEnabled(any(self.cands.values()))
        self.status.setText(T("Listo. Revisa los resultados y pulsa «Poner estos datos»."))

    def apply(self):
        m = self.main
        m.apply_form()
        n = 0
        for p, (r, cb) in self.combos.items():
            c = cb.currentData()
            if not c:
                continue
            ch = m.pending.setdefault(p, {})
            ch["title"], ch["artist"] = c["title"], c["artist"]
            if c["album"]:
                ch["album"] = c["album"]
            if self.ids.isChecked():
                for k, val in (("musicbrainz_trackid", c["rec_id"]), ("musicbrainz_artistid", c["artist_id"]),
                               ("musicbrainz_releasegroupid", c["rg_id"]), ("acoustid_id", c["acoustid"])):
                    if val:
                        ch[k] = val
            n += 1
        m.mark_items()
        m.on_select()
        self.status.setText(T(f"Datos puestos en {n} canción(es) (en naranja). Revisa y pulsa «Guardar»."))

    def closeEvent(self, e):
        for w in (self.worker, self.dl):
            if w is not None and w.isRunning():
                w.requestInterruption()
                w.wait(3000)
        super().closeEvent(e)


# ================================================================== emparejar álbum (MusicBrainz)
class MBWorker(QThread):
    done = pyqtSignal(str, object, str)

    def __init__(self, task, fn):
        super().__init__()
        self.task, self.fn = task, fn

    def run(self):
        try:
            self.done.emit(self.task, self.fn(), "")
        except Exception as e:
            self.done.emit(self.task, None, str(e))


def mb_search(album, artist):
    q = f'release:"{album}"' + (f' AND artist:"{artist}"' if artist else "")
    d = http_json("https://musicbrainz.org/ws/2/release/?" + urllib.parse.urlencode({"query": q, "fmt": "json", "limit": 20})) or {}
    out = []
    for r in d.get("releases") or []:
        media = r.get("media") or []
        out.append({"id": r.get("id"), "title": r.get("title", ""), "artist": credit(r.get("artist-credit")),
                    "date": r.get("date", ""), "country": r.get("country", ""),
                    "tracks": sum(int(m.get("track-count") or 0) for m in media),
                    "format": " + ".join(sorted({m.get("format") or "?" for m in media})),
                    "label": ", ".join((li.get("label") or {}).get("name", "") for li in (r.get("label-info") or [])[:2]),
                    "score": int(r.get("score") or 0)})
    return out


def mb_release(rid):
    time.sleep(1.1)   # MusicBrainz pide como mucho 1 consulta por segundo
    inc = "recordings+artist-credits+release-groups+labels"
    d = http_json(f"https://musicbrainz.org/ws/2/release/{rid}?inc={inc}&fmt=json") or {}
    rg = d.get("release-group") or {}
    acs = d.get("artist-credit") or []
    rel = {"id": d.get("id"), "title": d.get("title", ""), "artist": credit(acs),
           "artist_id": ((acs[0].get("artist") or {}).get("id", "")) if acs else "",
           "date": rg.get("first-release-date") or d.get("date", ""), "rg_id": rg.get("id", ""),
           "cover": bool((d.get("cover-art-archive") or {}).get("front")), "tracks": []}
    media = d.get("media") or []
    for m in media:
        for t in m.get("tracks") or []:
            rec = t.get("recording") or {}
            tac = t.get("artist-credit") or rec.get("artist-credit") or acs
            rel["tracks"].append({"disc": int(m.get("position") or 1), "discs": len(media),
                                  "pos": int(t.get("position") or 0), "title": t.get("title") or rec.get("title", ""),
                                  "artist": credit(tac), "artist_id": ((tac[0].get("artist") or {}).get("id", "")) if tac else "",
                                  "len": int(t.get("length") or rec.get("length") or 0) // 1000,
                                  "rec_id": rec.get("id", ""), "track_id": t.get("id", "")})
    return rel


class AlbumMatchDialog(QDialog):
    def __init__(self, main, paths, tech_info):
        super().__init__(main)
        self.main, self.paths, self.tech_info = main, list(paths), tech_info
        self.release, self.worker = None, None
        self.setWindowTitle(T("Emparejar álbum con MusicBrainz"))
        self.resize(1080, 720)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        dialog_header(v, T("💿 Emparejar álbum con MusicBrainz"),
                      T("Como en Picard: busca el álbum en MusicBrainz, coloca cada archivo en su pista y corrige de una vez "
                        "título, número de pista y de disco, año e intérprete del álbum. Puedes cambiar a mano la pista de "
                        "cada archivo antes de aplicar."))
        alb = self.most_common("album") or os.path.basename(os.path.dirname(self.paths[0]))
        art = self.most_common("albumartist") or self.most_common("artist")
        sr = QHBoxLayout()
        sr.addWidget(QLabel(T("Álbum")))
        self.q_album = QLineEdit(alb)
        sr.addWidget(self.q_album, 2)
        sr.addWidget(QLabel(T("Intérprete")))
        self.q_artist = QLineEdit(art)
        sr.addWidget(self.q_artist, 2)
        sb = QPushButton(T("🔎 Buscar"))
        sb.setObjectName("accent")
        sb.clicked.connect(self.search)
        sr.addWidget(sb)
        v.addLayout(sr)
        self.rel_tb = QTableWidget(0, 7)
        self.rel_tb.setHorizontalHeaderLabels([T("Álbum"), T("Intérprete"), T("Fecha"), T("País"), T("Pistas"), T("Formato"), T("Sello")])
        self.rel_tb.verticalHeader().setVisible(False)
        self.rel_tb.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.rel_tb.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rel_tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.rel_tb.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.rel_tb.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.rel_tb.setMaximumHeight(200)
        nice_table(self.rel_tb)
        self.rel_tb.itemSelectionChanged.connect(self.pick_release)
        v.addWidget(self.rel_tb)
        self.map_tb = QTableWidget(len(self.paths), 3)
        self.map_tb.setHorizontalHeaderLabels([T("Archivo"), T("Pista del álbum"), T("Coincidencia")])
        self.map_tb.verticalHeader().setVisible(False)
        self.map_tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self.map_tb.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.map_tb.setColumnWidth(0, 330)
        nice_table(self.map_tb)
        self.combos = []
        for r, p in enumerate(self.paths):
            self.map_tb.setItem(r, 0, QTableWidgetItem(os.path.basename(p)))
            cb = QComboBox()
            cb.setEnabled(False)
            self.map_tb.setCellWidget(r, 1, cb)
            self.map_tb.setItem(r, 2, QTableWidgetItem(""))
            self.combos.append(cb)
        v.addWidget(self.map_tb, 1)
        opts = QHBoxLayout()
        self.o_cover = QCheckBox(T("Poner la portada del álbum (Cover Art Archive)"))
        self.o_cover.setChecked(True)
        self.o_ids = QCheckBox(T("Guardar IDs de MusicBrainz"))
        self.o_ids.setChecked(True)
        self.o_titles = QCheckBox(T("Corregir títulos e intérpretes"))
        self.o_titles.setChecked(True)
        for c in (self.o_cover, self.o_ids, self.o_titles):
            opts.addWidget(c)
        opts.addStretch(1)
        v.addLayout(opts)
        self.status = QLabel(T("Pulsa «Buscar» y elige el lanzamiento correcto."))
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        br = QHBoxLayout()
        br.addStretch(1)
        self.apply_btn = QPushButton(T("✔ Aplicar al álbum"))
        self.apply_btn.setObjectName("accent")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        close = QPushButton(T("Cerrar"))
        close.clicked.connect(self.close)
        br.addWidget(self.apply_btn)
        br.addWidget(close)
        v.addLayout(br)
        self.results = []

    def most_common(self, key):
        cnt = {}
        for p in self.paths:
            val = (self.main.val(p, key) or "").strip()
            if val:
                cnt[val] = cnt.get(val, 0) + 1
        return max(cnt, key=cnt.get) if cnt else ""

    def run(self, task, fn, cb):
        if self.worker is not None and self.worker.isRunning():
            return
        self.worker = MBWorker(task, fn)
        self.worker.done.connect(lambda t, r, e: cb(r, e))
        self.worker.start()

    def search(self):
        album, artist = self.q_album.text().strip(), self.q_artist.text().strip()
        if not album:
            self.status.setText(T("Escribe el nombre del álbum."))
            return
        self.status.setText(T("Buscando en MusicBrainz…"))
        self.run("search", lambda: mb_search(album, artist), self.got_search)

    def got_search(self, res, err):
        if err:
            self.status.setText("❌ " + err)
            return
        n = len(self.paths)
        res = sorted(res or [], key=lambda r: (-(r["score"] >= 90), abs(r["tracks"] - n), -r["score"]))
        self.results = res
        self.rel_tb.blockSignals(True)
        self.rel_tb.setRowCount(len(res))
        for i, r in enumerate(res):
            for c, val in enumerate((r["title"], r["artist"], r["date"], r["country"], str(r["tracks"]), r["format"], r["label"])):
                self.rel_tb.setItem(i, c, QTableWidgetItem(val))
        self.rel_tb.blockSignals(False)
        self.status.setText(T(f"{len(res)} lanzamientos encontrados. Elige el que coincide con tus archivos ({n} canciones).")
                            if res else T("No se encontró el álbum en MusicBrainz. Prueba a escribir el nombre de otra forma."))
        if res:
            self.rel_tb.selectRow(0)

    def pick_release(self):
        rows = self.rel_tb.selectionModel().selectedRows()
        if not rows:
            return
        r = self.results[rows[0].row()]
        self.status.setText(T("Cargando las pistas del álbum…"))
        self.apply_btn.setEnabled(False)
        self.run("release", lambda: mb_release(r["id"]), self.got_release)

    def got_release(self, rel, err):
        if err:
            self.status.setText("❌ " + err)
            return
        self.release = rel
        tracks = rel["tracks"]
        multi = any(t["discs"] > 1 for t in tracks)
        labels = [(f"{t['disc']}-" if multi else "") + f"{t['pos']:02d}. {t['title']}" +
                  (f"  ({t['len'] // 60}:{t['len'] % 60:02d})" if t["len"] else "") for t in tracks]
        # puntuación de cada archivo con cada pista: título, duración y número de pista
        scores = []
        for i, p in enumerate(self.paths):
            title = self.main.val(p, "title") or os.path.splitext(os.path.basename(p))[0]
            try:
                mm, ss = self.tech_info(p).get("dur", "0:0").split(":")
                dur = int(mm) * 60 + int(ss)
            except Exception:
                dur = 0
            m = re.match(r"\s*(\d+)", self.main.val(p, "tracknumber") or "")
            tn = int(m.group(1)) if m else None
            for j, t in enumerate(tracks):
                s = max(sim(title, t["title"]), sim(os.path.basename(p), t["title"]) * 0.9)
                if dur and t["len"]:
                    s += 0.3 * max(0.0, 1 - abs(dur - t["len"]) / 15)
                if tn is not None and tn == t["pos"]:
                    s += 0.15
                scores.append((s, i, j))
        assign, used = {}, set()
        for s, i, j in sorted(scores, reverse=True):
            if i in assign or j in used or s < 0.45:
                continue
            assign[i] = (j, s)
            used.add(j)
        ok = 0
        for i, cb in enumerate(self.combos):
            cb.blockSignals(True)
            cb.clear()
            cb.addItem(T("(no cambiar este archivo)"), -1)
            for j, lab in enumerate(labels):
                cb.addItem(lab, j)
            got = assign.get(i)
            cb.setCurrentIndex(got[0] + 1 if got else 0)
            cb.setEnabled(True)
            cb.blockSignals(False)
            pct = int(min(1.0, got[1] / 1.45) * 100) if got else 0
            self.map_tb.item(i, 2).setText(f"{pct}%" if got else T("sin pareja"))
            ok += bool(got)
        self.apply_btn.setEnabled(True)
        extra = "" if rel.get("cover") else "  " + T("(este lanzamiento no tiene portada en el Cover Art Archive)")
        self.status.setText(T(f"«{rel['title']}» de {rel['artist']}: {len(tracks)} pistas · {ok} de {len(self.paths)} archivos emparejados.")
                            + extra)

    def apply(self):
        rel = self.release
        if not rel:
            return
        m = self.main
        m.apply_form()
        done = []
        for i, cb in enumerate(self.combos):
            j = cb.currentData()
            if j is None or j < 0:
                continue
            t = rel["tracks"][j]
            p = self.paths[i]
            ch = m.pending.setdefault(p, {})
            ch["album"] = rel["title"]
            ch["albumartist"] = rel["artist"]
            ch["tracknumber"] = str(t["pos"])
            ch["discnumber"] = str(t["disc"])
            if rel["date"]:
                ch["date"] = rel["date"]
            if self.o_titles.isChecked():
                ch["title"] = t["title"]
                ch["artist"] = t["artist"] or rel["artist"]
            if self.o_ids.isChecked():
                for k, val in (("musicbrainz_trackid", t["rec_id"]), ("musicbrainz_releasetrackid", t["track_id"]),
                               ("musicbrainz_albumid", rel["id"]), ("musicbrainz_releasegroupid", rel["rg_id"]),
                               ("musicbrainz_artistid", t["artist_id"]), ("musicbrainz_albumartistid", rel["artist_id"])):
                    if val:
                        ch[k] = val
            done.append(p)
        if not done:
            self.status.setText(T("No hay ningún archivo emparejado."))
            return
        m.mark_items()
        m.on_select()
        msg = T(f"Datos puestos en {len(done)} canción(es) (en naranja). Revisa y pulsa «Guardar».")
        if self.o_cover.isChecked() and rel.get("cover"):
            self.status.setText(T("Descargando la portada…"))

            def cover():
                for size in ("1200", "500", ""):
                    try:
                        url = f"https://coverartarchive.org/release/{rel['id']}/front" + (f"-{size}" if size else "")
                        return http_bytes(url, 40)
                    except Exception:
                        continue
                return None

            def got(data, err):
                if data:
                    m.apply_cover_bytes(done, data)
                self.status.setText(msg + ("" if data else "  " + T("(no se pudo bajar la portada)")))
            self.run("cover", cover, got)
        else:
            self.status.setText(msg)

    def closeEvent(self, e):
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(5000)
        super().closeEvent(e)

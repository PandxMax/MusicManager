"""Fuentes de etiquetas en línea: MusicBrainz (gratis) y Discogs (con token personal)."""
import json, urllib.request, urllib.parse, urllib.error
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QListWidget, QListWidgetItem, QCheckBox, QGridLayout)

UA = "MusicManager/1.0 (https://github.com/PandxMax/MusicManager)"


def http_get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("El servicio rechazó la petición (revisa tu token).")
        if e.code in (429, 503):
            raise RuntimeError("El servicio está saturado. Espera unos segundos y vuelve a intentarlo.")
        raise RuntimeError(f"Error {e.code} del servicio.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"No hay conexión: {e.reason}")


def musicbrainz(artist, title, album):
    parts = []
    if title:
        parts.append('recording:"%s"' % title.replace('"', ""))
    if artist:
        parts.append('artist:"%s"' % artist.replace('"', ""))
    if album:
        parts.append('release:"%s"' % album.replace('"', ""))
    if not parts:
        raise RuntimeError("Escribe al menos el título o el artista.")
    url = "https://musicbrainz.org/ws/2/recording?fmt=json&limit=12&query=" + urllib.parse.quote(" AND ".join(parts))
    data = json.loads(http_get(url).decode("utf-8"))
    out = []
    for r in data.get("recordings", []):
        art = "".join(c.get("name", "") + c.get("joinphrase", "") for c in r.get("artist-credit", [])) or ""
        tags = [t["name"].title() for t in sorted(r.get("tags", []), key=lambda t: -t.get("count", 0))][:4]
        rels = r.get("releases") or [{}]
        for rel in rels[:3]:
            date = rel.get("date", "") or ""
            track = ""
            try:
                track = str(rel["media"][0]["track"][0]["number"])
            except Exception:
                pass
            alb_art = "".join(c.get("name", "") + c.get("joinphrase", "") for c in rel.get("artist-credit", [])) or art
            out.append({"title": r.get("title", ""), "artist": art, "album": rel.get("title", ""),
                        "albumartist": alb_art, "date": date[:4], "tracknumber": track,
                        "genre": tags[0] if tags else "", "genres": tags,
                        "cover": f"https://coverartarchive.org/release/{rel['id']}/front-500" if rel.get("id") else ""})
    return out


def discogs(artist, title, album, token):
    q = " ".join(x for x in (artist, album or title) if x)
    if not q:
        raise RuntimeError("Escribe al menos el artista o el álbum.")
    url = ("https://api.discogs.com/database/search?type=release&per_page=12&q=" + urllib.parse.quote(q))
    hdr = {"Authorization": "Discogs token=" + token}
    data = json.loads(http_get(url, hdr).decode("utf-8"))
    out = []
    for r in data.get("results", []):
        t = r.get("title", "")
        art, _, alb = t.partition(" - ")
        styles, genres = r.get("style") or [], r.get("genre") or []
        allg = list(dict.fromkeys(styles + genres))
        out.append({"title": "", "artist": art.strip(), "album": (alb or art).strip(), "albumartist": art.strip(),
                    "date": str(r.get("year", "") or ""), "tracknumber": "",
                    "genre": (styles[0] if styles else (genres[0] if genres else "")), "genres": allg,
                    "cover": r.get("cover_image") or "", "_hdr": hdr})
    return out


class SearchWorker(QThread):
    done = pyqtSignal(list)
    fail = pyqtSignal(str)

    def __init__(self, source, token, artist, title, album):
        super().__init__()
        self.a = (source, token, artist, title, album)

    def run(self):
        source, token, artist, title, album = self.a
        try:
            res = musicbrainz(artist, title, album) if source == "musicbrainz" else discogs(artist, title, album, token)
            self.done.emit(res)
        except Exception as e:
            self.fail.emit(str(e))


class CoverWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, url, hdr):
        super().__init__()
        self.url, self.hdr = url, hdr

    def run(self):
        try:
            self.done.emit(http_get(self.url, self.hdr) if self.url else None)
        except Exception:
            self.done.emit(None)


FIELD_BOXES = [("title", "Título"), ("artist", "Artista"), ("album", "Álbum"), ("albumartist", "Artista del álbum"),
               ("date", "Año"), ("tracknumber", "Pista"), ("genre", "Género"), ("cover", "Portada")]


class TagSourceDialog(QDialog):
    applied = pyqtSignal(dict, object)

    def __init__(self, source, token, artist, title, album, parent=None):
        super().__init__(parent)
        self.source, self.token, self.results, self.w = source, token, [], None
        name = "MusicBrainz" if source == "musicbrainz" else "Discogs"
        self.setWindowTitle(f"{'🎼' if source == 'musicbrainz' else '💿'} Fuente de etiquetas: {name}")
        self.resize(640, 560)
        v = QVBoxLayout(self)
        g = QGridLayout()
        self.e_artist, self.e_title, self.e_album = QLineEdit(artist), QLineEdit(title), QLineEdit(album)
        for i, (lab, w) in enumerate((("Artista", self.e_artist), ("Título", self.e_title), ("Álbum", self.e_album))):
            g.addWidget(QLabel(lab), i, 0)
            g.addWidget(w, i, 1)
            w.returnPressed.connect(self.search)
        self.btn = QPushButton("🔍 Buscar")
        self.btn.setObjectName("accent")
        self.btn.clicked.connect(self.search)
        g.addWidget(self.btn, 0, 2, 3, 1)
        v.addLayout(g)
        self.status = QLabel("Pulsa «Buscar».")
        self.status.setObjectName("hint")
        v.addWidget(self.status)
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.show_detail)
        v.addWidget(self.list, 1)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        v.addWidget(self.detail)
        row = QHBoxLayout()
        row.addWidget(QLabel("Aplicar:"))
        self.boxes = {}
        for k, lab in FIELD_BOXES:
            c = QCheckBox(lab)
            c.setChecked(k not in ("title", "artist") if source == "discogs" else True)
            self.boxes[k] = c
            row.addWidget(c)
        row.addStretch(1)
        v.addLayout(row)
        row2 = QHBoxLayout()
        row2.addStretch(1)
        self.ok = QPushButton("✔ Aplicar a la canción")
        self.ok.setObjectName("accent")
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.apply)
        cancel = QPushButton("Cerrar")
        cancel.clicked.connect(self.close)
        row2.addWidget(self.ok)
        row2.addWidget(cancel)
        v.addLayout(row2)
        if artist or title:
            self.search()

    def search(self):
        self.btn.setEnabled(False)
        self.status.setText("Buscando…")
        self.list.clear()
        self.w = SearchWorker(self.source, self.token, self.e_artist.text().strip(), self.e_title.text().strip(),
                              self.e_album.text().strip())
        self.w.done.connect(self.on_results)
        self.w.fail.connect(self.on_fail)
        self.w.start()

    def on_fail(self, msg):
        self.btn.setEnabled(True)
        self.status.setText("⚠ " + msg)

    def on_results(self, res):
        self.btn.setEnabled(True)
        self.results = res
        if not res:
            self.status.setText("Sin resultados. Prueba con menos datos.")
            return
        self.status.setText(f"{len(res)} resultado(s). Elige el correcto:")
        for r in res:
            main = f"{r['title'] + ' — ' if r['title'] else ''}{r['artist']}"
            sub = f"{r['album']}" + (f" ({r['date']})" if r["date"] else "")
            self.list.addItem(QListWidgetItem(f"{main}\n    💿 {sub}" + (f"   🎼 {r['genre']}" if r["genre"] else "")))
        self.list.setCurrentRow(0)

    def show_detail(self, i):
        self.ok.setEnabled(0 <= i < len(self.results))
        if not (0 <= i < len(self.results)):
            return
        r = self.results[i]
        gen = ", ".join(r["genres"]) or "—"
        self.detail.setText(f"<b>Título:</b> {r['title'] or '—'} &nbsp; <b>Artista:</b> {r['artist'] or '—'} &nbsp; "
                            f"<b>Álbum:</b> {r['album'] or '—'}<br><b>Año:</b> {r['date'] or '—'} &nbsp; "
                            f"<b>Pista:</b> {r['tracknumber'] or '—'} &nbsp; <b>Géneros:</b> {gen}")

    def apply(self):
        i = self.list.currentRow()
        if not (0 <= i < len(self.results)):
            return
        r = self.results[i]
        fields = {k: r[k] for k, _ in FIELD_BOXES if k != "cover" and self.boxes[k].isChecked() and r.get(k)}
        if self.boxes["cover"].isChecked() and r.get("cover"):
            self.ok.setEnabled(False)
            self.status.setText("Descargando portada…")
            self.cw = CoverWorker(r["cover"], r.get("_hdr"))
            self.cw.done.connect(lambda data: self.finish(fields, data))
            self.cw.start()
        else:
            self.finish(fields, None)

    def finish(self, fields, cover):
        self.applied.emit(fields, cover)
        self.close()

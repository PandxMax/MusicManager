#!/usr/bin/env python3
"""
Music Manager: explorador de carpetas (arrastrar y soltar) + editor de metadatos
(con portada y letra) + sugerencia de géneros/subgéneros con Claude, ChatGPT o Gemini.

Instalación:   pip install PyQt6 mutagen send2trash
Ejecutar:      python src/music_manager.py
"""
import sys, os, json, re, shutil, time, base64, html, urllib.request, urllib.error, urllib.parse
import secret
from functools import lru_cache
from urllib.parse import quote_plus, quote

from PyQt6.QtCore import QItemSelectionModel, QEventLoop, QAbstractNativeEventFilter
from PyQt6.QtCore import (QAbstractNativeEventFilter, QCoreApplication, Qt, QSettings, QThread, pyqtSignal, QMimeData, QUrl, QSize,
                          QTimer, QRectF, QStandardPaths, QPropertyAnimation, QEasingCurve, QPoint, QRect, QBuffer, QByteArray, QIODevice, QEvent, QPointF, QPersistentModelIndex, QObject)
from PyQt6.QtGui import (QFontMetrics, QAction, QColor, QBrush, QIcon, QPixmap, QPainter, QImage,
                         QFont, QDesktopServices, QShortcut, QKeySequence, QDrag, QPalette, QLinearGradient, QPainterPath, QPolygonF, QCursor, QMouseEvent, QPen, QTextOption)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem, QListView, QAbstractItemView, QVBoxLayout,
    QHBoxLayout, QGridLayout, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QTextEdit,
    QPushButton, QComboBox, QGroupBox, QCheckBox, QFileDialog, QMessageBox,
    QInputDialog, QGraphicsDropShadowEffect, QToolTip, QStackedWidget, QStyle, QStyleOptionSlider, QHeaderView, QMenu, QToolBar, QTabWidget, QColorDialog, QSizePolicy, QScrollArea, QFileIconProvider, QFrame, QSlider, QDialog, QTextBrowser, QProgressDialog, QKeySequenceEdit, QAbstractSpinBox, QLayout, QRubberBand, QSplashScreen, QToolButton, QAbstractScrollArea, QStyledItemDelegate, QStyleOptionViewItem, QAbstractItemDelegate, QTableWidget, QTableWidgetItem, QRadioButton, QButtonGroup,
)
import mutagen
import i18n
import icons
import thumbs
import i18n_more
from i18n import tr as T
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from mutagen.id3 import USLT, APIC, SYLT, COMM
from mutagen.easyid3 import EasyID3


def _comm_get(id3, key):
    return [t for fr in id3.getall("COMM") for t in fr.text]


def _comm_set(id3, key, value):
    id3.delall("COMM")
    id3.add(COMM(encoding=1, lang="eng", desc="", text=list(value)))


def _comm_del(id3, key):
    id3.delall("COMM")


EasyID3.RegisterKey("comment", _comm_get, _comm_set, _comm_del)   # el comentario de los MP3 (COMM)

try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False

AUDIO_EXT = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4"}
FIELDS = [("title", "Título"), ("artist", "Intérprete"), ("album", "Álbum"),
          ("albumartist", "Intérprete del álbum"), ("composer", "Compositor"),
          ("genre", "Género"), ("date", "Año"), ("tracknumber", "Pista"),
          ("discnumber", "Número de disco"), ("comment", "Comentario")]
EASY_KEYS = {k for k, _ in FIELDS}
MB_KEYS = {"musicbrainz_trackid", "musicbrainz_releasetrackid", "musicbrainz_albumid", "musicbrainz_releasegroupid",
           "musicbrainz_artistid", "musicbrainz_albumartistid", "acoustid_id"}   # IDs de MusicBrainz / AcoustID
PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole.value + 1
MARK_ROLE = Qt.ItemDataRole.UserRole.value + 7   # estado ya pintado (pendiente, sonando): solo se toca si cambia
THUMB, COVER = 96, 200
THUMB_GEN = 160   # las miniaturas se generan a este tamaño para que se vean nítidas al agrandarlas
APP_VERSION = "2.31"


class TMenu(QMenu):
    """Menú contextual que traduce sus textos según el idioma elegido."""
    def addAction(self, *a):
        if a and isinstance(a[0], str):
            a = (T(a[0]),) + a[1:]
        return super().addAction(*a)


# ------------------------------------------------------------ Carpetas / disco
def main_folders():
    """Solo la carpeta de Música (más las que tú fijes con «Agregar carpeta»)."""
    p = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation)
    if p and os.path.isdir(p):
        return [("🎵 Música", os.path.normpath(p))]
    h = os.path.expanduser("~")
    return [("🏠 Inicio", h)] if os.path.isdir(h) else []


def _hidden(e):
    if e.name.startswith("."):
        return True
    try:
        return bool(e.stat(follow_symlinks=False).st_file_attributes & 0x6)  # oculto/sistema (Windows)
    except AttributeError:
        return False
    except OSError:
        return True


def subdirs(path):
    try:
        with os.scandir(path) as it:
            res = [(e.name, os.path.join(path, e.name)) for e in it
                   if e.is_dir(follow_symlinks=False) and not _hidden(e)]
    except OSError:
        return []
    return sorted(res, key=lambda x: x[0].lower())


def has_subdirs(path):
    try:
        with os.scandir(path) as it:
            return any(e.is_dir(follow_symlinks=False) and not _hidden(e) for e in it)
    except OSError:
        return False


@lru_cache(maxsize=128)
def find_folder_image(d):
    try:
        names = {n.lower(): n for n in os.listdir(d)}
    except OSError:
        return None
    for base in ("cover", "folder", "front", "album", "albumart"):
        for ext in (".jpg", ".jpeg", ".png"):
            if base + ext in names:
                return os.path.join(d, names[base + ext])
    return None


# ------------------------------------------------------------------ Metadatos
def read_tags(path):
    tags = {k: "" for k in EASY_KEYS}
    try:
        f = mutagen.File(path, easy=True)
        if f is not None and f.tags:
            for k in tags:
                try:
                    v = f.tags.get(k)
                except Exception:
                    v = None
                if v:
                    tags[k] = str(v[0])
    except Exception:
        note_quiet()
    return tags


def _save(f):
    """Guarda. Los MP3 van en ID3v2.3 + UTF-16: es lo que el Explorador de Windows entiende para mostrar la portada."""
    if isinstance(f, MP3) or type(f).__name__ == "EasyMP3":
        f.save(v2_version=3)
    else:
        f.save()


def write_tags(path, changes):
    f = mutagen.File(path, easy=True)
    if f is None:
        raise RuntimeError("formato no soportado")
    if f.tags is None:
        f.add_tags()
    skipped = []
    for k, v in changes.items():
        try:
            if v == "":
                if k in f.tags:
                    del f.tags[k]
            else:
                f[k] = [v]
        except Exception:
            skipped.append(k)
    _save(f)
    return skipped


LRC_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text):
    """Letra sincronizada [mm:ss.xx] -> [(texto, milisegundos)] ordenado por tiempo."""
    out = []
    for line in (text or "").splitlines():
        stamps = LRC_RE.findall(line)
        if not stamps:
            continue
        txt = LRC_RE.sub("", line).strip()
        for m, sec, fr in stamps:
            out.append((txt, int(m) * 60000 + int(sec) * 1000 + (int((fr + "00")[:3]) if fr else 0)))
    out.sort(key=lambda x: x[1])
    return out


def is_lrc(text):
    return len(parse_lrc(text)) >= 2


def mime_of(data):
    return "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"


def _pop(tags, key):
    try:
        del tags[key]
    except KeyError:
        pass


@lru_cache(maxsize=4096)
def _tech(path, mtime):
    out = {"codec": "—", "enc": "—", "enc_full": "", "tag": "—", "bitrate": "—", "freq": "—", "dur": "—", "mode": "—", "size": "—",
           "ch": "—"}
    try:
        out["size"] = f"{os.path.getsize(path) / 1048576:.2f} MB"
        f = mutagen.File(path)
        i = f.info
        kind = type(f).__name__
        t = getattr(f, "tags", None)
        if kind == "MP3":
            ver = getattr(t, "version", None)
            out["tag"] = ("ID3v%d.%d" % (ver[0], ver[1])) if ver else "Sin etiquetas"
            lay = {1: "I", 2: "II", 3: "III"}.get(getattr(i, "layer", 3), "III")
            mv = {1: "MPEG-1", 2: "MPEG-2", 2.5: "MPEG-2.5"}.get(getattr(i, "version", 1), "MPEG")
            enc = str(getattr(i, "encoder_info", "") or "").strip()
            out["enc"] = f"{mv} L{ {'I': 1, 'II': 2, 'III': 3}[lay] }"
            out["enc_full"] = f"{mv} Layer {lay}" + (f" · {enc}" if enc else "")
        elif kind == "MP4":
            c = str(getattr(i, "codec", "") or "")
            out["tag"] = "MP4 (iTunes)"
            out["enc"] = ("ALAC" if "alac" in c.lower() else
                          {"mp4a.40.2": "AAC-LC", "mp4a.40.5": "HE-AAC", "mp4a.40.29": "HE-AAC v2"}.get(c, c.upper() or "AAC"))
        elif kind == "FLAC":
            out["tag"] = "Vorbis Comment"
            out["enc"] = f"FLAC {getattr(i, 'bits_per_sample', 16)} bits"
        elif kind in ("OggVorbis", "OggOpus"):
            out["tag"] = "Vorbis Comment"
            out["enc"] = "Vorbis" if kind == "OggVorbis" else "Opus"
        if kind == "MP4":
            out["codec"] = "ALAC" if "alac" in str(getattr(i, "codec", "")).lower() else "AAC"
        else:
            out["codec"] = {"MP3": "MP3", "FLAC": "FLAC", "OggVorbis": "Vorbis", "OggOpus": "Opus"}.get(kind, kind)
        br = int(getattr(i, "bitrate", 0) or 0)
        if br:
            out["bitrate"] = f"{br // 1000} kbps"
        sr = int(getattr(i, "sample_rate", 0) or 0)
        if sr:
            out["freq"] = f"{sr / 1000:g} kHz"
        secs = int(getattr(i, "length", 0) or 0)
        out["dur"] = f"{secs // 60}:{secs % 60:02d}"
        chn = int(getattr(i, "channels", 0) or 0)
        if chn:
            out["ch"] = {1: "Mono", 2: "Estéreo"}.get(chn, f"{chn} canales")
        bm = getattr(i, "bitrate_mode", None)
        if bm is not None and str(bm).split(".")[-1] not in ("UNKNOWN", "0"):
            out["mode"] = str(bm).split(".")[-1]
        elif out["codec"] in ("FLAC", "ALAC"):
            out["mode"] = "Sin pérdida"
    except Exception:
        note_quiet()
    return out


TECH_MEM = {}   # ruta -> (fecha del archivo, datos, última comprobación): evita releer el archivo en cada repintado


def tech_info(path):
    """Datos técnicos de la canción. Se guardan en memoria y la fecha del archivo se comprueba como mucho cada 5 s."""
    now = time.monotonic()
    e = TECH_MEM.get(path)
    if e is not None and now - e[2] < 5:
        return e[1]
    try:
        m = os.path.getmtime(path)
    except OSError:
        m = 0
    if e is not None and e[0] == m:
        TECH_MEM[path] = (m, e[1], now)
        return e[1]
    info = _tech(path, m)
    TECH_MEM[path] = (m, info, now)
    return info


def tech_cached(path):
    """Solo lo que ya está en memoria (no lee el archivo)."""
    e = TECH_MEM.get(path)
    return e[1] if e is not None else None


def tech_compute(path):
    """Para el hilo de miniaturas: calcula los datos técnicos (sin tocar TECH_MEM). Devuelve [fecha, datos]."""
    try:
        m = os.path.getmtime(path)
    except OSError:
        m = 0
    return [m, _tech(path, m)]


def inspect_file(path):
    """Lee portada incrustada, letra e información técnica del archivo."""
    d = {"cover": None, "lyrics": "", "info": ""}
    try:
        f = mutagen.File(path)
        if f is None:
            return d
        t = f.tags
        if isinstance(f, MP3):
            if t:
                a = t.getall("APIC")
                if a:
                    d["cover"] = a[0].data
                u = t.getall("USLT")
                if u:
                    d["lyrics"] = u[0].text
        elif isinstance(f, MP4):
            if t:
                c = t.get("covr")
                if c:
                    d["cover"] = bytes(c[0])
                lyr = t.get("\xa9lyr")
                if lyr:
                    d["lyrics"] = lyr[0]
        else:  # FLAC, Ogg Vorbis, Opus
            if t:
                for k in ("lyrics", "unsyncedlyrics"):
                    v = t.get(k)
                    if v:
                        d["lyrics"] = v[0]
                        break
            if isinstance(f, FLAC):
                if f.pictures:
                    d["cover"] = f.pictures[0].data
            elif t and t.get("metadata_block_picture"):
                d["cover"] = Picture(base64.b64decode(t["metadata_block_picture"][0])).data
        i = f.info
        secs = int(getattr(i, "length", 0) or 0)
        br = int(getattr(i, "bitrate", 0) or 0) // 1000
        kind = {"MP3": "MP3", "FLAC": "FLAC", "MP4": "M4A", "OggVorbis": "OGG",
                "OggOpus": "OPUS"}.get(type(f).__name__, type(f).__name__)
        parts = [kind, f"{secs // 60}:{secs % 60:02d}"]
        if br:
            parts.append(f"{br} kbps")
        parts.append(f"{os.path.getsize(path) / 1048576:.1f} MB")
        d["info"] = " · ".join(parts)
    except Exception:
        note_quiet()
    return d


def write_extra(path, lyrics=None, cover=None):
    """Escribe letra y/o portada. cover=b'' significa quitar la portada."""
    f = mutagen.File(path)
    if f is None:
        raise RuntimeError("formato no soportado")
    if f.tags is None:
        f.add_tags()
    t = f.tags
    if isinstance(f, MP3):
        if lyrics is not None:
            t.delall("USLT")
            t.delall("SYLT")
            if lyrics.strip():
                t.add(USLT(encoding=1, lang="eng", desc="", text=lyrics))
                sy = parse_lrc(lyrics)
                if len(sy) >= 2:  # letra con tiempos: también como SYLT (letra sincronizada de ID3)
                    t.add(SYLT(encoding=1, lang="eng", format=2, type=1, desc="", text=sy))
        if cover is not None:
            t.delall("APIC")
            if cover:
                t.add(APIC(encoding=1, mime=mime_of(cover), type=3, desc="Cover", data=cover))
    elif isinstance(f, MP4):
        if lyrics is not None:
            _pop(t, "\xa9lyr")
            if lyrics.strip():
                t["\xa9lyr"] = [lyrics]
        if cover is not None:
            _pop(t, "covr")
            if cover:
                fmt = MP4Cover.FORMAT_PNG if mime_of(cover) == "image/png" else MP4Cover.FORMAT_JPEG
                t["covr"] = [MP4Cover(cover, imageformat=fmt)]
    else:
        if lyrics is not None:
            _pop(t, "lyrics")
            _pop(t, "unsyncedlyrics")
            if lyrics.strip():
                t["lyrics"] = [lyrics]
        if cover is not None:
            pic = Picture()
            pic.type, pic.desc = 3, "Cover"
            if cover:
                try:
                    im = QImage.fromData(cover)
                    pic.width, pic.height, pic.depth = im.width(), im.height(), 24
                except Exception:
                    note_quiet()
            if isinstance(f, FLAC):
                f.clear_pictures()
                if cover:
                    pic.mime, pic.data = mime_of(cover), cover
                    f.add_picture(pic)
            else:
                _pop(t, "metadata_block_picture")
                if cover:
                    pic.mime, pic.data = mime_of(cover), cover
                    t["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
    _save(f)


# ---------------------------------------------------------------------- Tema
THEMES = {
    "dark": dict(window="#1b1c23", base="#14151a", surface="#262833", surface2="#303243", text="#e9e9f1",
                 muted="#8c8fa3", border="#393b4d", accent="#7c5cff", accent_hover="#9179ff",
                 accent_soft="rgba(124, 92, 255, 70)"),
    "light": dict(window="#f3f4f8", base="#ffffff", surface="#ffffff", surface2="#eceef6", text="#1d1e26",
                  muted="#7a7d90", border="#d3d6e2", accent="#6c4cf5", accent_hover="#8267ff",
                  accent_soft="rgba(108, 76, 245, 45)"),
}

QSS = """
* { outline: 0; }
QToolBar { background: @surface; border: none; border-bottom: 1px solid @border; padding: 5px; spacing: 4px; }
QToolBar QToolButton { background: transparent; border: none; border-radius: 8px; padding: 6px 10px; }
QToolBar QToolButton:hover { background: @accent_soft; }
QToolBar QToolButton:checked { background: @accent; color: white; }
QToolButton#kofibtn { background: transparent; border: 1px solid @border; border-radius: 8px; padding: 3px 9px 3px 5px; font-weight: 600; }
QToolButton#kofibtn:hover { border-color: @accent; background: @accent_soft; }
QToolButton#langbtn { background: transparent; border: 1px solid @border; border-radius: 8px; padding: 3px 8px; font-weight: 600; }
QToolButton#langbtn:hover { border-color: @accent; background: @accent_soft; }
QToolButton#langbtn::menu-indicator { image: none; width: 0px; }
QToolButton#webbtn { background: @accent_soft; border: 1px solid @accent; border-radius: 12px; padding: 4px 14px; }
QToolButton#webbtn:hover { background: @accent; color: white; }
QToolButton#webbtn::menu-indicator { image: none; width: 0px; }
QToolButton#viewbtn { background: transparent; border: 1px solid transparent; border-radius: 7px; padding: 3px; }
QToolButton#viewbtn:hover { background: @accent_soft; }
QToolButton#viewbtn:checked { background: @accent; border-color: @accent; }
QHeaderView::section { background: @surface2; color: @text; border: none; border-right: 1px solid @border;
                       border-bottom: 1px solid @border; padding: 4px 8px; font-weight: 600; }
QHeaderView::section:hover { background: @accent_soft; }
QFrame#xfer { background: @surface2; border: 1px solid @border; border-radius: 10px; }
QToolBar QLineEdit { min-width: 200px; }
QLabel#title { font-size: 15px; font-weight: 700; }
QLabel#hint { color: @muted; font-size: 11px; }
QPlainTextEdit#renamebox { background: @accent_dark; color: white; border: 5px solid @accent; border-top-width: 3px;
                           border-top-left-radius: 0px; border-top-right-radius: 0px; border-bottom-left-radius: 10px;
                           border-bottom-right-radius: 10px; padding: 0px;
                           selection-background-color: white; selection-color: @accent_dark; }
QLineEdit#treeedit { background: @surface; border: 2px solid @accent; border-radius: 6px; padding: 0px 6px; margin: 0px; }
QLineEdit#renameedit { background: @surface; border: 1px solid @accent; border-radius: 6px; padding: 1px 6px; }
QToolButton#foldmini { background: transparent; border: 1px solid @border; border-radius: 8px; padding: 0px; }
QToolButton#foldmini:hover { background: @accent_soft; border-color: @accent; }
QToolButton#foldbar { background: transparent; border: none; border-top: 1px solid @border; color: @muted; padding: 2px 8px; font-size: 12px; }
QToolButton#foldbar:hover { background: @accent_soft; color: @text; }
QLabel#techchip { background: @surface2; border: 1px solid @border; border-radius: 10px; padding: 2px 8px; font-size: 12px; }
QLabel#chip { background: @surface2; border: 1px solid @border; border-radius: 10px; padding: 2px 7px; font-size: 11px; }
QPushButton#tabbtn { border-radius: 10px; padding: 7px 10px; }
QFrame#plpanel { background: @window; border: 1px solid @border; border-radius: 14px; }
QFrame#npcard { background: @surface2; border: 1px solid @border; border-radius: 12px; }
QPushButton#fab { background: @accent; color: white; border: none; border-radius: 20px; font-size: 18px; padding: 0; }
QPushButton#fab:hover { background: @accent_hover; }
QFrame#volpop { background: @surface2; border: 1px solid @border; border-radius: 10px; }
QSlider::groove:vertical { width: 6px; background: @border; border-radius: 3px; }
QSlider::add-page:vertical { background: @accent; border-radius: 3px; }
QSlider::handle:vertical { background: white; border: 2px solid @accent; height: 12px; width: 12px; margin: 0 -4px; border-radius: 8px; }
QListWidget#pl { background: transparent; border: none; outline: none; }
QListWidget#pl::item { background: @surface; border: 1px solid @border; border-radius: 8px; padding: 4px 8px; margin: 1px 2px; }
QListWidget#pl::item:selected { background: @accent_soft; border-color: @accent; color: @text; }
QPushButton#tabbtn:checked { background: @accent; color: white; border-color: @accent; font-weight: 600; }
QPushButton#chipbtn { background: @accent_soft; border: 1px solid @accent; border-radius: 10px; padding: 2px 8px; font-size: 11px; }
QPushButton#chipbtn:hover { background: @accent; color: white; }
QPushButton#iconbtn { background: @surface2; border: 1px solid @border; border-radius: 10px; font-size: 16px; padding: 0; }
QPushButton#iconbtn:hover { border-color: @accent; background: @accent_soft; }
QFrame#playerbar { background: transparent; border: none; }
QLabel#nowtitle { font-weight: 600; }
QLabel#nowcover { background: @base; border-radius: 8px; }
QPushButton#tbtn { background: transparent; border: none; font-size: 17px; padding: 4px 8px; border-radius: 8px; }
QPushButton#tbtn:hover { background: @accent_soft; }
QPushButton#playbtn { background: @accent; color: white; border: none; border-radius: 14px; min-width: 28px;
                      max-width: 28px; min-height: 28px; max-height: 28px; font-size: 13px; padding: 0; }
QPushButton#playbtn:hover { background: @accent_hover; }
QMenuBar { background: @surface; border-bottom: 1px solid @border; padding: 2px 4px; }
QMenuBar::item { padding: 6px 12px; border-radius: 6px; background: transparent; }
QMenuBar::item:selected { background: @accent_soft; }
QLabel#cover { background: @base; border: 1px solid @border; border-radius: 14px; }
QGroupBox { border: 1px solid @border; border-radius: 12px; margin-top: 16px; padding: 12px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 14px; padding: 0 6px;
                   color: @muted; font-weight: 600; }
QPushButton { background: @surface; border: 1px solid @border; border-radius: 8px; padding: 6px 12px; }
QPushButton:hover { border-color: @accent; background: @surface2; }
QPushButton:pressed { background: @accent; color: white; border-color: @accent; }
QPushButton:checked { border-color: @accent; background: @accent_soft; }
QPushButton:disabled { color: @muted; }
QPushButton#accent { background: @accent; color: white; border-color: @accent; font-weight: 600; }
QPushButton#accent:hover { background: @accent_hover; }
QPushButton#accent:disabled { background: @surface2; color: @muted; border-color: @border; }
QLineEdit, QPlainTextEdit, QTextBrowser { background: @base; border: 1px solid @border; border-radius: 8px;
                                         padding: 5px 8px; selection-background-color: @accent; selection-color: white; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: @accent; }
QLineEdit:disabled, QPlainTextEdit:disabled { color: @muted; }
QListWidget, QTreeWidget { background: @base; border: 1px solid @border; border-radius: 12px; padding: 4px; }
QListWidget::item { border-radius: 8px; padding: 4px; }
QTreeWidget::item { padding: 4px 2px; border-radius: 6px; }
QListWidget::item:hover:!selected, QTreeWidget::item:hover:!selected { background: @accent_soft; }
QListWidget::item:selected, QTreeWidget::item:selected { background: @accent; color: white; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: @border; border-radius: 4px; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: @muted; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: @border; border-radius: 4px; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: @muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QSlider::groove:horizontal { height: 6px; background: @border; border-radius: 3px; }
QSlider::sub-page:horizontal { background: @accent; border-radius: 3px; }
QSlider::handle:horizontal { background: white; border: 2px solid @accent; width: 12px; height: 12px;
                             margin: -6px 0; border-radius: 8px; }
QSplitter::handle { background: @border; border-radius: 3px; margin: 2px; }
QSplitter::handle:hover { background: @accent; }
QSplitter::handle:disabled { background: transparent; }
QStatusBar { background: @surface; border-top: 1px solid @border; color: @muted; }
QMenu { background: @surface; border: 1px solid @border; border-radius: 12px; padding: 6px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 8px; margin: 1px 2px; min-width: 190px; }
QMenu::icon { padding-left: 10px; }
QMenu::right-arrow { width: 10px; height: 10px; margin-right: 8px; }
QMenu::item:selected { background: @accent; color: white; }
QMenu::item:disabled { color: @muted; }
QMenu::separator { height: 1px; background: @border; margin: 4px 8px; }
QToolTip { background: @surface2; color: @text; border: 1px solid @border; border-radius: 6px; padding: 5px 8px; }
QDialog { background: @window; }
/* ---- pulido general (1.92) ---- */
QComboBox { background: @base; border: 1px solid @border; border-radius: 8px; padding: 5px 30px 5px 9px; min-height: 18px; }
QComboBox:hover { border-color: @accent; }
QComboBox:focus { border-color: @accent; }
QComboBox:disabled { color: @muted; background: @surface; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; }
QComboBox::down-arrow { image: url(@img_chev); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: @surface; border: 1px solid @border; border-radius: 8px; padding: 4px;
                              selection-background-color: @accent; selection-color: white; outline: 0; }
QCheckBox, QRadioButton { spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border: 1.5px solid @muted; background: @base; }
QCheckBox::indicator { border-radius: 5px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent; border-color: @accent; image: url(@img_check); }
QRadioButton::indicator:checked { border-color: @accent; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
                                  stop:0 @accent, stop:0.45 @accent, stop:0.55 @base, stop:1 @base); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { border-color: @border; background: @surface; }
QTabWidget::pane { background: @surface; border: 1px solid @border; border-radius: 12px; top: -1px; padding: 6px; }
QTabBar::tab { background: transparent; color: @muted; border: none; border-radius: 8px; padding: 8px 16px; margin: 0 4px 6px 0; }
QTabBar::tab:hover { background: @accent_soft; color: @text; }
QTabBar::tab:selected { background: @accent; color: white; font-weight: 600; }
QTableView, QTableWidget { background: @base; alternate-background-color: @surface; border: 1px solid @border;
                           border-radius: 12px; gridline-color: transparent; selection-background-color: @accent_soft;
                           selection-color: @text; padding: 2px; }
QTableView::item { padding: 4px 8px; border: none; }
QTableView QTableCornerButton::section { background: @surface2; border: none; }
QHeaderView { background: transparent; border: none; }
QProgressBar { background: @surface2; border: none; border-radius: 6px; min-height: 10px; max-height: 10px;
               text-align: center; color: transparent; }
QProgressBar::chunk { background: @accent; border-radius: 6px; }
QSpinBox, QDoubleSpinBox { background: @base; border: 1px solid @border; border-radius: 8px; padding: 4px 8px; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: @accent; }
QTreeView { show-decoration-selected: 1; }
QTreeView::branch:selected { background: @accent; border-top-left-radius: 6px; border-bottom-left-radius: 6px; }
QTreeView::item:selected { border-top-left-radius: 0px; border-bottom-left-radius: 0px; }
QTreeWidget#settingsnav { padding: 6px; }
QTreeWidget#settingsnav::item { padding: 7px 8px; border-radius: 8px; }
QLabel#menuhead { color: @muted; font-size: 10px; font-weight: 700; padding: 6px 12px 3px 12px; }
QRubberBand { background: @accent_soft; border: 1px solid @accent; border-radius: 6px; }
QLabel#dlgtitle { font-size: 17px; font-weight: 700; }
QLabel#dlgsub { color: @muted; }
QFrame#card { background: @surface; border: 1px solid @border; border-radius: 12px; }
QFrame#keyok { background: @accent_soft; border: 1px solid @accent; border-radius: 10px; }
QPushButton#link { background: transparent; border: none; color: @accent_hover; padding: 2px 4px; font-weight: 600; }
QPushButton#link:hover { text-decoration: underline; background: transparent; }
QScrollBar:vertical { width: 10px; }
QScrollBar:horizontal { height: 10px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { border-radius: 3px; }
"""


def ui_images(t):
    """Iconos pequeños para la hoja de estilos (flecha de los desplegables y la marca de las casillas), en SVG."""
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) or \
        os.path.join(os.path.expanduser("~"), ".musicmanager")
    d = os.path.join(base, "ui")
    os.makedirs(d, exist_ok=True)
    out = {}
    for name, svg in (("chev", '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                               '<path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="%s" stroke-width="1.8" '
                               'stroke-linecap="round" stroke-linejoin="round"/></svg>' % t["muted"]),
                      ("check", '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
                                '<path d="M3.5 8.5 L6.7 11.5 L12.5 4.8" fill="none" stroke="#ffffff" stroke-width="2.2" '
                                'stroke-linecap="round" stroke-linejoin="round"/></svg>')):
        p = os.path.join(d, f"{name}_{t['muted'].strip('#')}.svg")
        try:
            if not os.path.exists(p):
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(svg)
        except OSError:
            pass
        out["img_" + name] = p.replace("\\", "/")
    return out


ACCENTS = [("#7c5cff", "Violeta"), ("#3b82f6", "Azul"), ("#06b6d4", "Cian"), ("#22c55e", "Verde"),
           ("#f97316", "Naranja"), ("#ec4899", "Rosa"), ("#ef4444", "Rojo")]


def apply_theme(app, name, accent=None):
    t = dict(THEMES.get(name, THEMES["dark"]))
    if accent and QColor(accent).isValid():
        ac = QColor(accent)
        t["accent"] = ac.name()
        t["accent_hover"] = ac.lighter(125).name()
        t["accent_soft"] = f"rgba({ac.red()}, {ac.green()}, {ac.blue()}, {70 if name == 'dark' else 45})"
    app.setStyle("Fusion")
    c, R, G = QColor, QPalette.ColorRole, QPalette.ColorGroup
    pal = QPalette()
    for role, key in ((R.Window, "window"), (R.WindowText, "text"), (R.Base, "base"),
                      (R.AlternateBase, "surface"), (R.Text, "text"), (R.Button, "surface"),
                      (R.ButtonText, "text"), (R.ToolTipBase, "surface2"), (R.ToolTipText, "text"),
                      (R.Highlight, "accent"), (R.PlaceholderText, "muted"), (R.Link, "accent_hover")):
        pal.setColor(role, c(t[key]))
    pal.setColor(R.HighlightedText, c("white"))
    for role in (R.Text, R.ButtonText, R.WindowText):
        pal.setColor(G.Disabled, role, c(t["muted"]))
    app.setPalette(pal)
    t["accent_dark"] = QColor(t["accent"]).darker(155).name()
    t.update(ui_images(t))
    qss = QSS
    for k in sorted(t, key=len, reverse=True):  # primero los nombres largos (accent_hover antes que accent)
        qss = qss.replace("@" + k, t[k])
    app.setStyleSheet(qss)


def load_logo():
    """Logo de la app (dos notas entrelazadas), incrustado en logo_data.py."""
    try:
        from logo_data import LOGO_PNG_B64
        pm = QPixmap()
        if pm.loadFromData(base64.b64decode("".join(LOGO_PNG_B64))) and not pm.isNull():
            return pm
    except Exception:
        note_quiet()
    return note_icon(256).pixmap(256, 256)


def norm(p):
    return os.path.normcase(os.path.normpath(p))


# --------------------------------------------------------------------- Imágenes
def rounded_pm(pm, r=14):
    """Portada con las esquinas redondeadas."""
    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(out.rect()), r, r)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def note_icon(size=THUMB_GEN):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#8e5bff"))
    g.setColorAt(1, QColor("#3a8dff"))
    p.setBrush(QBrush(g))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(4, 4, size - 8, size - 8, size * 0.2, size * 0.2)
    p.setPen(QColor(255, 255, 255, 235))
    f = QFont()
    f.setPixelSize(int(size * 0.5))
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "♫")
    p.end()
    return QIcon(pm)


def make_icon(data):
    if not data:
        return None
    pm = QPixmap()
    if not pm.loadFromData(data) or pm.isNull():
        return None
    return QIcon(pm.scaled(THUMB_GEN, THUMB_GEN, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation))


SIZE_PRESETS = ["Original", "300", "500", "600", "800", "1000", "1200"]


def parse_side(text):
    """'600' o '600 px' -> 600. 'Original' (o algo inválido) -> None = no redimensionar."""
    t = (text or "").strip().lower().replace("px", "").strip()
    return int(t) if t.isdigit() and int(t) >= 50 else None


def dominant_color(data, dark=True):
    """Color vistoso predominante de una portada (para teñir el programa). None si no hay."""
    img = QImage.fromData(data)
    if img.isNull():
        return None
    img = img.scaled(40, 40, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    buckets = {}
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor(img.pixel(x, y))
            h, sat, v, _ = c.getHsvF()
            if v < 0.18 or sat < 0.12:
                continue
            w = sat * (0.4 + v)
            k = int(max(h, 0) * 12) % 12
            b = buckets.setdefault(k, [0.0, 0.0, 0.0, 0.0])
            b[0] += w; b[1] += w * max(h, 0); b[2] += w * sat; b[3] += w * v
    if not buckets:
        return None
    b = max(buckets.values(), key=lambda t: t[0])
    h, sat, v = b[1] / b[0], b[2] / b[0], b[3] / b[0]
    sat = min(1.0, max(sat, 0.45))
    v = min(1.0, max(v, 0.62)) if dark else min(0.78, max(v, 0.45))
    return QColor.fromHsvF(h % 1.0, sat, v).name()


def cover_dims(data):
    img = QImage.fromData(data)
    return (img.width(), img.height()) if not img.isNull() else (0, 0)


def prepare_cover(data, max_side=1200):
    """Valida la imagen y, si su lado mayor supera max_side, la reduce conservando la
    proporción. Nunca la agranda. max_side=None deja la imagen como está."""
    img = QImage.fromData(data)
    if img.isNull():
        return None
    if not max_side or max(img.width(), img.height()) <= max_side:
        return data
    img = img.scaled(max_side, max_side, Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG" if data[:4] == b"\x89PNG" else "JPG", 90)
    return bytes(ba)


# ----------------------------------------------------------------------- IA
PATTERNS = ["Artista - Título", "Pista - Título", "Álbum - Título", "Título"]


def safe_filename(name):
    """Quita los caracteres que Windows no permite en nombres de archivo."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    return name[:180]


def app_installed(scheme):
    """¿Hay un programa de Windows registrado para abrir enlaces «scheme:» (spotify:, tidal:)?"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):
            sub = f"Software\\Classes\\{scheme}" if root == winreg.HKEY_CURRENT_USER else scheme
            try:
                with winreg.OpenKey(root, sub) as k:
                    winreg.QueryValueEx(k, "URL Protocol")
                    return True
            except OSError:
                continue
    except Exception:
        note_quiet()
    return False


DRAG_ACTIVE = [False]   # True mientras se arrastran archivos (para que la rueda mueva lo que está debajo)


class DragWheelFilter(QAbstractNativeEventFilter):
    """Mientras arrastras archivos, Windows no deja que la rueda del ratón desplace las listas: aquí se hace a mano
    sobre el árbol o la lista que está debajo del cursor."""
    def nativeEventFilter(self, etype, message):
        if not DRAG_ACTIVE[0] or sys.platform != "win32":
            return False, 0
        try:
            import ctypes
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message not in (0x020A, 0x020E):   # WM_MOUSEWHEEL / WM_MOUSEHWHEEL
                return False, 0
            delta = ctypes.c_short((msg.wParam >> 16) & 0xFFFF).value
            w = QApplication.widgetAt(QCursor.pos())
            while w is not None and not isinstance(w, QAbstractScrollArea):
                w = w.parentWidget()
            if w is None:
                return False, 0
            sb = w.verticalScrollBar() if msg.message == 0x020A else w.horizontalScrollBar()
            step = max(20, sb.singleStep() * 3)
            sb.setValue(sb.value() - int(delta / 120 * step))
            return True, 0
        except Exception:
            return False, 0


ROW_STEP = 26   # desplazamiento de la rueda en la vista detalles (una fila)


def vol_curve(x):
    """0–100 de la barra → volumen real. El oído no es lineal: con esta curva cada paso se nota igual de suave."""
    x = max(0.0, min(1.0, x / 100.0))
    return x ** 2.2 if x > 0 else 0.0


def fmt_ms(ms):
    s = int(ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def looks_like_refusal(text):
    """True si la IA no dio una letra (se negó, no la conoce o devolvió algo mínimo)."""
    t = (text or "").strip()
    if len(t) < 30 or "SIN_LETRA" in t.upper():
        return True
    head = t[:150].lower()
    return any(x in head for x in ("no puedo", "lo siento", "i can't", "i cannot", "i'm sorry",
                                   "i am sorry", "i'm unable", "derechos de autor", "copyright"))


def make_options(val):
    """Convierte la respuesta de la IA en opciones (etiqueta, valor a guardar)."""
    g, subs = "", []
    if isinstance(val, str):
        g = val
    elif isinstance(val, list):
        subs = val
    elif isinstance(val, dict):
        g = str(val.get("genero") or val.get("genre") or "")
        subs = val.get("subgeneros") or val.get("subgenres") or []
    opts, seen = [], set()
    if g.strip():
        opts.append((f"{g.strip()}  (género general)", g.strip()))
        seen.add(g.strip().lower())
    for s in subs:
        s = str(s).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            opts.append((f"{g.strip()} › {s}" if g.strip() else s, s))
    return opts


class NoWheelScroll(QScrollArea):
    """Área con barras (solo se usa con la barra, no con la rueda: así nada se mueve sin querer)."""
    def wheelEvent(self, e):
        e.accept()


class AIBase(QThread):
    """Cliente común para Claude, ChatGPT y Gemini."""
    failed = pyqtSignal(str)

    def __init__(self, provider, model, key):
        super().__init__()
        self.provider, self.model, self.key = provider, model, key

    def post_with_retry(self, url, body, headers):
        """Reintenta solo cuando el servidor está saturado (429/5xx)."""
        for attempt in range(5):
            req = urllib.request.Request(url, json.dumps(body).encode(), headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise

    def ask(self, prompt):
        return self.chat([{"role": "user", "content": prompt}])

    def chat(self, messages, system=""):
        """messages = [{"role": "user"|"assistant", "content": "..."}, ...]"""
        if self.provider == "Claude":
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": self.key, "anthropic-version": "2023-06-01",
                       "content-type": "application/json"}
            body = {"model": self.model, "max_tokens": 4000, "messages": messages}
            if system:
                body["system"] = system
        elif self.provider == "Gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            headers = {"x-goog-api-key": self.key, "content-type": "application/json"}
            body = {"contents": [{"role": "model" if m["role"] == "assistant" else "user",
                                  "parts": [{"text": m["content"]}]} for m in messages]}
            if system:
                body["systemInstruction"] = {"parts": [{"text": system}]}
        else:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.key}", "content-type": "application/json"}
            msgs = ([{"role": "system", "content": system}] if system else []) + messages
            body = {"model": self.model, "messages": msgs}
        data = self.post_with_retry(url, body, headers)
        if self.provider == "Claude":
            return "".join(b.get("text", "") for b in data["content"])
        if self.provider == "Gemini":
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        return data["choices"][0]["message"]["content"]

    def error_text(self, e):
        hint = ""
        if e.code in (429, 503):
            hint = ("\n\nEl servicio está saturado o llegaste al límite. Ya se reintentó varias "
                    "veces: espera un minuto o prueba otro modelo.")
        elif e.code in (401, 403):
            hint = "\n\nRevisa que la API key sea correcta."
        return f"Error HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}{hint}"


class AIWorker(AIBase):
    """Pide género y subgéneros posibles para cada canción."""
    done = pyqtSignal(dict)

    def __init__(self, provider, model, key, items):
        super().__init__(provider, model, key)
        self.items = items

    def run(self):
        result = {}
        try:
            for i in range(0, len(self.items), 20):
                batch = self.items[i:i + 20]
                prompt = (
                    "Eres un experto en música. Para cada canción indica su género principal y entre "
                    "3 y 6 subgéneros posibles, del más al menos probable. Usa nombres estándar y "
                    "consistentes (Rock, Pop, Hip-Hop, Electrónica, Jazz, Clásica, Reggaetón, Salsa, "
                    "Cumbia, Folk, Metal, R&B, Latino, etc.). Responde SOLO con un objeto JSON de la "
                    'forma {"id": {"genero": "Electrónica", "subgeneros": ["Synthwave", "Darksynth"]}}, '
                    "sin texto adicional ni markdown. Si no puedes determinarlo usa \"\".\n"
                    + json.dumps(batch, ensure_ascii=False))
                text = self.ask(prompt)
                m = re.search(r"\{.*\}", text, re.S)
                result.update(json.loads(m.group(0)) if m else {})
            self.done.emit(result)
        except urllib.error.HTTPError as e:
            self.failed.emit(self.error_text(e))
        except Exception as e:
            self.failed.emit(str(e))


from changelog import CHANGELOG


def changelog_html(entries, current=None):
    out = []
    for v, items in entries:
        tag = " <small>(actual)</small>" if v == current else ""
        out.append(f"<h4>Versión {v}{tag}</h4><ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
    return "".join(out)


REPO = "PandxMax/MusicManager"


def ver_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")) or (0,)


class UpdateCheckWorker(QThread):
    """Consulta en GitHub si hay una versión más nueva (https://github.com/PandxMax/MusicManager/releases)."""
    result = pyqtSignal(dict)

    def run(self):
        info = {"ok": False}
        try:
            req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                         headers={"User-Agent": f"MusicManager/{APP_VERSION}", "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                d = json.loads(r.read().decode("utf-8"))
            asset = next((a for a in d.get("assets", []) if a.get("name", "").lower().endswith(".zip")), None)
            info = {"ok": True, "tag": d.get("tag_name", ""), "page": d.get("html_url", ""), "notes": d.get("body") or "",
                    "url": asset["browser_download_url"] if asset else "", "size": asset.get("size", 0) if asset else 0,
                    "digest": (asset.get("digest") or "") if asset else ""}
        except urllib.error.HTTPError as e:
            info = {"ok": e.code == 404, "none": e.code == 404, "error": f"GitHub respondió {e.code}"}
        except Exception as e:
            info = {"ok": False, "error": str(getattr(e, "reason", e))}
        self.result.emit(info)


class UpdateDownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, dest, digest=""):
        super().__init__()
        self.url, self.dest, self.digest = url, dest, digest or ""

    def run(self):
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": f"MusicManager/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as r, open(self.dest, "wb") as fh:
                total, got = int(r.headers.get("Content-Length") or 0), 0
                while True:
                    if self.isInterruptionRequested():
                        self.failed.emit("Cancelado")
                        return
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
            # antes de instalar: que la descarga esté completa y sea exactamente la que publicó GitHub
            import hashlib, zipfile
            if total and got != total:
                raise OSError("la descarga quedó incompleta")
            if self.digest.startswith("sha256:"):
                h = hashlib.sha256()
                with open(self.dest, "rb") as fh:
                    for blk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(blk)
                if h.hexdigest().lower() != self.digest[7:].lower():
                    raise OSError("el archivo descargado no coincide con el publicado (huella sha256 distinta)")
            with zipfile.ZipFile(self.dest) as z:
                bad = z.testzip()
                if bad:
                    raise OSError(f"el zip está dañado ({bad})")
            self.done.emit(self.dest)
        except Exception as e:
            self.failed.emit(str(getattr(e, "reason", e)))


class ChipLabel(QLabel):
    """Etiqueta técnica que recorta el texto con «…» si no cabe (nunca empuja a las demás)."""
    def __init__(self):
        super().__init__("")
        self._full = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(40)

    def set_full(self, text, tip=""):
        self._full = text
        self.setToolTip(tip or text)
        self._fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _fit(self):
        w = max(10, self.width() - 18)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, w))


class KeyWorker(QThread):
    """Estima la tonalidad en segundo plano (analizando el audio)."""
    done = pyqtSignal(str, int, bool, float)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            import keydetect
            pc, minor, conf = keydetect.detect_file(self.path)
            self.done.emit(self.path, pc, minor, conf)
        except Exception:
            self.done.emit(self.path, -1, False, 0.0)


class FlowLayout(QLayout):
    """Reparte los widgets en filas y pasa a otra línea cuando no caben (así no ensancha la ventana)."""
    def __init__(self, parent=None, hspacing=4, vspacing=4):
        super().__init__(parent)
        self._items, self.hs, self.vs = [], hspacing, vspacing

    def addItem(self, it):
        self._items.append(it)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, r):
        super().setGeometry(r)
        self._do(r, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        sz = QSize(0, 0)
        for it in self._items:
            if not it.isEmpty():
                sz = sz.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return QSize(sz.width() + m.left() + m.right(), sz.height() + m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, lh = r.x(), r.y(), 0
        for it in self._items:
            if it.isEmpty():
                continue
            sh = it.sizeHint()
            if x + sh.width() > r.right() + 1 and lh > 0:
                x, y, lh = r.x(), y + lh + self.vs, 0
            if not test:
                it.setGeometry(QRect(x, y, sh.width(), sh.height()))
            x += sh.width() + self.hs
            lh = max(lh, sh.height())
        return y + lh - rect.y() + m.bottom()


class CoverWorker(QThread):
    """Busca varias portadas candidatas en iTunes, Deezer y SoundCloud (gratis, sin clave) para cada álbum."""
    group_done = pyqtSignal(int, object)  # índice del grupo, lista de candidatos [{src,label,data,w,h}]
    finished_all = pyqtSignal()
    UA = "MusicManager/2.31 (https://github.com/PandxMax/MusicManager)"

    def __init__(self, groups, side):
        super().__init__()
        self.groups, self.side = groups, side  # groups: [(artista, título, álbum)]

    def get(self, url, raw=False):
        req = urllib.request.Request(url, headers={"User-Agent": self.UA})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    b = r.read()
                    return b if raw else json.loads(b.decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 502, 503, 504):
                    return None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                pass
            time.sleep(1 + attempt)
        return None

    @staticmethod
    def norm(t):
        return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()

    def score(self, artist, album, ra, ral):
        a, al, ra, ral = self.norm(artist), self.norm(album), self.norm(ra), self.norm(ral)
        return (2 if a and ra and (a in ra or ra in a) else 0) + (2 if al and ral and (al in ral or ral in al) else 0)

    def itunes(self, artist, title, album):
        out, seen = [], set()
        qs = ([(f"{artist} {album}".strip(), "album")] if album else []) + [(f"{artist} {title}".strip(), "song")]
        for q, ent in qs:
            d = self.get(f"https://itunes.apple.com/search?term={quote_plus(q)}&entity={ent}&limit=10")
            for r in (d or {}).get("results", []):
                u = r.get("artworkUrl100")
                key = r.get("collectionId") or u
                if not u or key in seen:
                    continue
                seen.add(key)
                big = re.sub(r"/\d+x\d+[a-z]*\.", f"/{self.side}x{self.side}bb.", u)
                out.append((self.score(artist, album, r.get("artistName"), r.get("collectionName")), "iTunes",
                            f"{r.get('collectionName', '')} — {r.get('artistName', '')}", [big, u.replace("100x100", "600x600")]))
        return out

    def deezer(self, artist, title, album):
        out, seen = [], set()
        q = quote_plus(f'artist:"{artist}" track:"{title}"') if artist else quote_plus(title)
        d = self.get(f"https://api.deezer.com/search?q={q}&limit=10")
        for r in (d or {}).get("data", []):
            alb = r.get("album") or {}
            key = alb.get("id")
            urls = [alb.get(k) for k in ("cover_xl", "cover_big") if alb.get(k)]
            if not urls or key in seen:
                continue
            seen.add(key)
            ar = (r.get("artist") or {}).get("name", "")
            out.append((self.score(artist, album, ar, alb.get("title")), "Deezer", f"{alb.get('title', '')} — {ar}", urls))
        return out

    def soundcloud(self, artist, title, album):
        """Portadas de SoundCloud usando yt-dlp (búsqueda sin clave de API)."""
        try:
            import yt_dlp
        except ImportError:
            return []
        q = f"{artist} {title}".strip()
        if not q:
            return []
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": False,
                "socket_timeout": 15, "logger": type("L", (), {"debug": lambda *a: 0, "info": lambda *a: 0,
                                                              "warning": lambda *a: 0, "error": lambda *a: 0})()}
        out = []
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(f"scsearch5:{q}", download=False) or {}
        for e in info.get("entries") or []:
            th = e.get("thumbnail") or next((t.get("url") for t in reversed(e.get("thumbnails") or []) if t.get("url")), None)
            if not th:
                continue
            urls = [re.sub(r"-(large|t\d+x\d+|original|crop|badge|small|tiny|mini)\.", "-t500x500.", th), th]
            ar = e.get("uploader") or e.get("artist") or ""
            out.append((self.score(artist, title, ar, e.get("title")), "SoundCloud",
                        f"{e.get('title', '')} — {ar}", urls))
        return out

    def download(self, cand):
        score, src, label, urls = cand
        for u in urls:
            b = self.get(u, raw=True)
            if b:
                img = QImage.fromData(b)
                if not img.isNull():
                    return {"src": src, "label": label, "data": b, "w": img.width(), "h": img.height(), "score": score}
        return None

    def run(self):
        from concurrent.futures import ThreadPoolExecutor
        for i, (artist, title, album) in enumerate(self.groups):
            if self.isInterruptionRequested():
                break
            cands = []
            for finder in (self.itunes, self.deezer, self.soundcloud):
                try:
                    cands += finder(artist, title, album)
                except Exception:
                    note_quiet()
            cands.sort(key=lambda c: -c[0])
            good = [c for c in cands if c[0] >= 1][:8]
            pick = good or cands[:4]
            with ThreadPoolExecutor(4) as ex:
                got = [g for g in ex.map(self.download, pick) if g]
            if not good:
                for g in got:
                    g["label"] += "  (coincidencia dudosa)"
            self.group_done.emit(i, got)
        self.finished_all.emit()


class CoverChooser(QDialog):
    """Muestra varias portadas candidatas para que elijas una."""
    def __init__(self, parent, title, cands, remaining=0):
        super().__init__(parent)
        self.setWindowTitle("✨ Elige una portada")
        self.resize(760, 520)
        self.choice, self.take_first = None, False
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Opciones para «{title}». Doble clic o selecciona una y pulsa «Usar esta»."))
        self.lw = QListWidget()
        self.lw.setViewMode(QListView.ViewMode.IconMode)
        self.lw.setIconSize(QSize(150, 150))
        self.lw.setGridSize(QSize(185, 235))
        self.lw.setResizeMode(QListView.ResizeMode.Adjust)
        self.lw.setMovement(QListView.Movement.Static)
        self.lw.setWordWrap(True)
        self.lw.setSpacing(6)
        for c in cands:
            pm = QPixmap()
            pm.loadFromData(c["data"])
            it = QListWidgetItem(QIcon(pm.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation)),
                                 f"{c['src']} · {c['w']}×{c['h']}\n{c['label']}")
            it.setData(Qt.ItemDataRole.UserRole, c["data"])
            it.setToolTip(c["label"])
            self.lw.addItem(it)
        self.lw.setCurrentRow(0)
        self.lw.itemDoubleClicked.connect(lambda _: self.use())
        v.addWidget(self.lw, 1)
        row = QHBoxLayout()
        ok = QPushButton("✔ Usar esta")
        ok.setObjectName("accent")
        ok.clicked.connect(self.use)
        skip = QPushButton("Omitir")
        skip.clicked.connect(self.reject)
        row.addStretch(1)
        if remaining:
            allb = QPushButton(f"Usar la primera opción en las {remaining} restantes")
            allb.clicked.connect(self.first_all)
            row.addWidget(allb)
        row.addWidget(skip)
        row.addWidget(ok)
        v.addLayout(row)

    def use(self):
        it = self.lw.currentItem()
        if it is not None:
            self.choice = it.data(Qt.ItemDataRole.UserRole)
            self.accept()

    def first_all(self):
        self.take_first = True
        self.lw.setCurrentRow(self.lw.currentRow() if self.lw.currentRow() >= 0 else 0)
        self.use()


class SpinDisc(QWidget):
    """Disco que gira con la portada de la canción que suena."""
    def __init__(self, size=40):
        super().__init__()
        self.setFixedSize(size, size)
        self.pm, self.angle, self.playing = None, 0.0, False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.tick)
        self.setToolTip("Disco: gira mientras suena la música")

    def set_cover(self, pm):
        self.pm = pm.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation) if pm is not None and not pm.isNull() else None
        self.update()

    def set_playing(self, on):
        self.playing = on
        if on:
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def tick(self):
        self.angle = (self.angle + 4) % 360
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.width() / 2
        p.translate(r, r)
        p.rotate(self.angle)
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), r - 1, r - 1)
        p.setClipPath(path)
        if self.pm is not None:
            p.drawPixmap(int(-self.pm.width() / 2), int(-self.pm.height() / 2), self.pm)
        else:
            p.fillRect(QRectF(-r, -r, 2 * r, 2 * r), QColor("#2a2c3a"))
            p.setPen(QColor("#555873"))
            p.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, "♪")
        p.setClipping(False)
        p.setPen(QPen(QColor(0, 0, 0, 120), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), r - 1, r - 1)
        p.setBrush(QColor("#111218"))
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.drawEllipse(QPointF(0, 0), r * 0.17, r * 0.17)


class VolBox(QWidget):
    """Botón de volumen; al pasar el ratón aparece hacia ARRIBA una barra vertical flotante (no mueve nada)."""
    def __init__(self, btn, slider):
        super().__init__()
        self.btn, self.slider = btn, slider
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(btn)
        self.pop = QFrame(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.pop.setObjectName("volpop")
        self.pop.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        pl = QVBoxLayout(self.pop)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.addWidget(slider, 0, Qt.AlignmentFlag.AlignHCenter)
        slider.setFixedHeight(110)
        slider.setFixedWidth(24)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.check)
        btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        btn.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.btn and ev.type() == QEvent.Type.Enter:
            self.open_it()
        return super().eventFilter(obj, ev)

    def open_it(self):
        self.pop.adjustSize()
        g = self.btn.mapToGlobal(QPoint(self.btn.width() // 2, 0))
        self.pop.move(g.x() - self.pop.width() // 2, g.y() - self.pop.height() - 2)
        self.pop.show()
        self.pop.raise_()
        self.timer.start()

    def check(self):
        pos = QCursor.pos()
        near = self.btn.rect().adjusted(-6, -6, 6, 6)
        over_btn = near.contains(self.btn.mapFromGlobal(pos))
        pr = self.pop.geometry().adjusted(-6, -10, 6, 14)
        if self.slider.isSliderDown() or over_btn or pr.contains(pos):
            return
        self.pop.hide()
        self.timer.stop()


class VizWorker(QThread):
    """Calcula (una vez por canción) la energía por bandas de frecuencia para animar los cuadritos al ritmo real."""
    ready = pyqtSignal(str, object, int)

    def __init__(self, path, bands=32):
        super().__init__()
        self.path, self.bands = path, bands

    def run(self):
        try:
            import numpy as np
            import spectro
            rate, n, fps = 11025, 1024, 25
            hop = rate // fps
            x = spectro.decode_mono(self.path, rate)
            frames = max(1, (len(x) - n) // hop)
            win = np.hanning(n).astype(np.float32)
            freqs = np.fft.rfftfreq(n, 1.0 / rate)
            edges = np.geomspace(40, 5000, self.bands + 1)
            idx = []
            for b in range(self.bands):
                lo = int(np.searchsorted(freqs, edges[b]))
                hi = max(int(np.searchsorted(freqs, edges[b + 1])), lo + 1)
                idx.append((lo, hi))
            view = np.lib.stride_tricks.sliding_window_view(x, n)
            out = np.zeros((frames, self.bands), np.float32)
            step = 400
            for a in range(0, frames, step):
                if self.isInterruptionRequested():
                    return
                b = min(frames, a + step)
                chunk = view[a * hop: (b - 1) * hop + 1: hop][: b - a] * win
                mag = np.abs(np.fft.rfft(chunk, axis=1))
                for k, (lo, hi) in enumerate(idx):
                    out[a:b, k] = mag[:, lo:hi].mean(axis=1)
            db = 20 * np.log10(out + 1e-5)
            lo = np.percentile(db, 8, axis=0)
            hi = np.percentile(db, 99, axis=0)
            norm = np.clip((db - lo) / np.maximum(hi - lo, 1e-3), 0, 1).astype(np.float32)
            self.ready.emit(self.path, norm, fps)
        except Exception:
            self.ready.emit(self.path, None, 25)


class VizBar(QWidget):
    """Cuadritos de fondo que bailan con la música; al parar, caen y desaparecen."""
    COLS, SQ, GAP = 32, 6, 2

    def __init__(self, pos_fn):
        super().__init__()
        cell = self.SQ + self.GAP
        self.cell = cell
        self.setFixedSize(self.COLS * cell + 4, 38)
        self.rows = (self.height() - 4) // cell
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.pos_fn, self.data, self.fps, self.state = pos_fn, None, 25, "stopped"
        self.lvl = [0.0] * self.COLS
        self.parts = []
        self.t = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)

    def set_data(self, arr, fps):
        self.data, self.fps = arr, fps

    def set_state(self, st):
        import random
        if st == self.state:
            return
        prev, self.state = self.state, st
        if st == "stopped":
            bottom = self.height() - 2
            for c, v in enumerate(self.lvl):
                for r in range(int(v + 0.5)):
                    self.parts.append([c * self.cell + 2, bottom - (r + 1) * self.cell + self.GAP,
                                       random.uniform(-10, 40), 1.0, random.uniform(-20, 20)])
                self.lvl[c] = 0.0
            self.data = None
        if st == "playing" or self.parts:
            self.timer.start()

    def tick(self):
        import math, random
        dt = 0.033
        self.t += dt
        if self.state == "playing":
            row = None
            if self.data is not None and len(self.data):
                i = min(len(self.data) - 1, max(0, int(self.pos_fn() / 1000.0 * self.fps)))
                row = self.data[i]
            for c in range(self.COLS):
                if row is not None:
                    tgt = float(row[c]) ** 1.4 * self.rows
                else:   # mientras se analiza la canción: movimiento suave
                    tgt = (0.25 + 0.2 * math.sin(self.t * 4 + c * 0.6) + 0.15 * math.sin(self.t * 7 + c)) * self.rows
                self.lvl[c] = tgt if tgt > self.lvl[c] else max(tgt, self.lvl[c] - 9 * dt)
        gone = []
        for p in self.parts:
            p[2] += 900 * dt
            p[1] += p[2] * dt
            p[0] += p[4] * dt
            p[3] -= 1.6 * dt
            if p[3] <= 0 or p[1] > self.height():
                gone.append(p)
        for p in gone:
            self.parts.remove(p)
        if self.state != "playing" and not self.parts:
            self.timer.stop()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.palette().color(QPalette.ColorRole.Highlight)
        bottom = self.height() - 2
        p.setPen(Qt.PenStyle.NoPen)
        for c, v in enumerate(self.lvl):
            for r in range(int(v + 0.5)):
                a = 70 + int(60 * r / max(1, self.rows - 1))
                p.setBrush(QColor(base.red(), base.green(), base.blue(), a))
                p.drawRoundedRect(QRectF(c * self.cell + 2, bottom - (r + 1) * self.cell + self.GAP, self.SQ, self.SQ), 1.5, 1.5)
        for x, y, _vy, al, _vx in self.parts:
            p.setBrush(QColor(base.red(), base.green(), base.blue(), int(110 * max(0, al))))
            p.drawRoundedRect(QRectF(x, y, self.SQ, self.SQ), 1.5, 1.5)


class WideViz(QWidget):
    """Barra inferior con cuadritos a todo lo ancho que bailan al ritmo de la canción (en espejo: graves al centro).
    Se dibuja detrás de los mensajes de la barra de estado, que se pintan encima para que se sigan leyendo."""
    SQ, GAP = 7, 3

    def __init__(self, status_bar, src_viz):
        super().__init__(status_bar)
        self.sb, self.src = status_bar, src_viz
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.lvl, self.peak, self.t = [], [], 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        status_bar.installEventFilter(self)
        status_bar.messageChanged.connect(lambda _m: self.update())
        self.hide()

    def eventFilter(self, obj, ev):
        if obj is self.sb and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setGeometry(self.sb.rect())
            self.lower()
        return False

    def cols(self):
        return max(8, (self.width() - 8) // (self.SQ + self.GAP))

    def rows(self):
        return max(2, (self.height() - 8) // (self.SQ + self.GAP))

    def start(self):
        if not self.timer.isActive():
            self.timer.start()

    def tick(self):
        import math
        dt = 0.033
        self.t += dt
        n, rows = self.cols(), self.rows()
        if len(self.lvl) != n:
            self.lvl, self.peak = [0.0] * n, [0.0] * n
        src = self.src
        playing = src.state == "playing"
        row = None
        if playing and src.data is not None and len(src.data):
            i = min(len(src.data) - 1, max(0, int(src.pos_fn() / 1000.0 * src.fps)))
            row = src.data[i]
        half = (n + 1) // 2
        for c in range(n):
            d = abs(c - (n - 1) / 2.0) / max(1.0, (n - 1) / 2.0)     # 0 en el centro, 1 en los bordes
            if row is not None:
                pos = d * (len(row) - 1)
                k = int(pos)
                f = pos - k
                v = float(row[k]) * (1 - f) + float(row[min(k + 1, len(row) - 1)]) * f
                tgt = (v ** 1.5) * rows * (1.0 - 0.25 * d)
            elif playing:   # mientras se analiza la canción: ola suave
                tgt = (0.3 + 0.22 * math.sin(self.t * 3 + c * 0.35) + 0.12 * math.sin(self.t * 5.3 + c * 0.9)) * rows * (1 - 0.4 * d)
            else:
                tgt = 0.0
            self.lvl[c] = tgt if tgt > self.lvl[c] else max(tgt, self.lvl[c] - 10 * dt)
            self.peak[c] = self.lvl[c] if self.lvl[c] > self.peak[c] else max(0.0, self.peak[c] - 3.2 * dt)
        if not playing and max(self.peak or [0]) <= 0.01:
            self.timer.stop()
        w = self.window()
        if w.isMinimized() or not self.isVisible():
            return   # con la ventana minimizada no se pinta nada
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.palette().color(QPalette.ColorRole.Highlight)
        hi = base.lighter(160)
        cell = self.SQ + self.GAP
        n, rows = self.cols(), self.rows()
        x0 = (self.width() - n * cell + self.GAP) / 2
        bottom = self.height() - 4
        p.setPen(Qt.PenStyle.NoPen)
        # «pantalla LED» apagada: se dibuja una sola vez en una imagen y luego solo se copia (mucho más ligero)
        bkey = (self.width(), self.height(), n, rows, base.rgba(), self.devicePixelRatioF())
        if getattr(self, "_bg_key", None) != bkey:
            dpr = self.devicePixelRatioF()
            bg = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            bg.setDevicePixelRatio(dpr)
            bg.fill(Qt.GlobalColor.transparent)
            bp = QPainter(bg)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.setPen(Qt.PenStyle.NoPen)
            bp.setBrush(QColor(base.red(), base.green(), base.blue(), 18))
            for c in range(n):
                for r in range(rows):
                    bp.drawRoundedRect(QRectF(x0 + c * cell, bottom - (r + 1) * cell + self.GAP, self.SQ, self.SQ), 2, 2)
            bp.end()
            self._bg, self._bg_key = bg, bkey
            self._cols_cache = {}
        p.drawPixmap(0, 0, self._bg)
        ccache = getattr(self, "_cols_cache", {})
        for c in range(n):
            v = self.lvl[c] if c < len(self.lvl) else 0.0
            pk = self.peak[c] if c < len(self.peak) else 0.0
            x = x0 + c * cell
            for r in range(min(rows, int(v + 0.5))):
                y = bottom - (r + 1) * cell + self.GAP
                col = ccache.get(r)
                if col is None:
                    t = r / max(1, rows - 1)
                    col = QColor(int(base.red() + (hi.red() - base.red()) * t), int(base.green() + (hi.green() - base.green()) * t),
                                 int(base.blue() + (hi.blue() - base.blue()) * t), 150 + int(80 * t))
                    ccache[r] = col
                p.setBrush(col)
                p.drawRoundedRect(QRectF(x, y, self.SQ, self.SQ), 2, 2)
            if pk > 0.6:   # tapita que cae despacio
                r = min(rows - 1, int(pk + 0.5))
                p.setBrush(QColor(255, 255, 255, 170))
                p.drawRoundedRect(QRectF(x, bottom - (r + 1) * cell + self.GAP + self.SQ - 2, self.SQ, 2), 1, 1)
        msg = self.sb.currentMessage()
        if msg:   # el mensaje, en una «pastilla» discreta con los colores del tema (rutas largas se recortan por el medio)
            f = QFont(p.font())
            f.setPointSizeF(max(8.0, f.pointSizeF() - 0.5))
            p.setFont(f)
            fm = QFontMetrics(f)
            text = fm.elidedText(msg, Qt.TextElideMode.ElideMiddle, max(80, int(self.width() * 0.45)))
            w = fm.horizontalAdvance(text) + 34
            h = fm.height() + 10
            r = QRectF(10, (self.height() - h) / 2, w, h)
            pal = self.palette()
            bg = QColor(pal.color(QPalette.ColorRole.Window))
            bg.setAlpha(225)
            p.setPen(QPen(QColor(base.red(), base.green(), base.blue(), 110), 1))
            p.setBrush(bg)
            p.drawRoundedRect(r, h / 2, h / 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(base)
            p.drawEllipse(QPointF(r.x() + 13, r.center().y()), 3, 3)
            p.setPen(pal.color(QPalette.ColorRole.WindowText))
            p.drawText(QRectF(r.x() + 23, r.y(), w - 28, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


class PlaylistList(QListWidget):
    """Lista de reproducción: acepta canciones arrastradas desde el explorador y se reordena arrastrando."""
    dropped = pyqtSignal(list)
    reordered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setObjectName("pl")
        self.setSpacing(3)
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.source() is self:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        e.acceptProposedAction()

    def dropEvent(self, e):
        if e.source() is self:
            super().dropEvent(e)
            self.reordered.emit()
        elif e.mimeData().hasUrls():
            self.dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()


def _clean_title(t):
    """Quita adornos que hacen fallar la búsqueda: (feat. …), [Official Video], - Remastered 2011, (Letra)…"""
    t = re.sub(r"\s*[\(\[][^\)\]]*(feat|ft\.|official|video|audio|lyric|letra|remaster|live|en vivo|version|versión|hd|hq)[^\)\]]*[\)\]]",
               "", t or "", flags=re.I)
    t = re.sub(r"\s+-\s+(remaster(ed)?|live|en vivo|radio edit|single version)\b.*$", "", t, flags=re.I)
    t = re.sub(r"\s+(feat\.?|ft\.?)\s+.*$", "", t, flags=re.I)
    return t.strip(" -_")


def _main_artist(a):
    return re.split(r"\s*(?:,|&|;|/| feat\.? | ft\.? | x | y )\s*", a or "", maxsplit=1, flags=re.I)[0].strip()


def _norm(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", (t or "").lower())
    return re.sub(r"[^a-z0-9]+", "", "".join(c for c in t if not unicodedata.combining(c)))


class LrclibWorker(QThread):
    """Busca letras: primero en LRCLIB (https://lrclib.net); si no está o el servicio falla, en NetEase (también
    sincronizada) y en lyrics.ovh (normal). Reintenta solo cuando hay errores de conexión."""
    got = pyqtSignal(str, str)  # ruta, letra ("" si no hubo)
    finished_all = pyqtSignal()
    failed = pyqtSignal(str)
    UA = "MusicManager/1.05 (https://github.com/PandxMax/MusicManager)"

    def __init__(self, jobs, prefer_synced=True):
        super().__init__()
        self.jobs, self.prefer_synced = jobs, prefer_synced  # jobs: [(ruta, artista, título, álbum, segundos)]
        self.sources = {}      # de dónde salió cada letra (para el mensaje final)
        self.errored = []      # rutas que fallaron por conexión incluso tras reintentar
        self.not_found = []    # rutas que ningún servicio tiene

    def fetch(self, url, name="LRCLIB", headers=None, tries=3):
        """Pide una dirección con reintentos (los servicios a veces responden 503 / 429 por saturación)."""
        h = {"User-Agent": self.UA}
        h.update(headers or {})
        req = urllib.request.Request(url, headers=h)
        last = ""
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=12) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                last = f"{name} respondió «{e.reason}» ({e.code})"
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                last = f"No hay conexión con {name} ({getattr(e, 'reason', e)})"
            time.sleep(1.2 * (attempt + 1))
        raise RuntimeError(last)

    def pick(self, d):
        if not d or d.get("instrumental"):
            return ""
        synced, plain = d.get("syncedLyrics") or "", d.get("plainLyrics") or ""
        return (synced or plain) if self.prefer_synced else (plain or synced)

    def lrclib(self, artist, title, album, dur):
        q = {"track_name": title}
        if artist:
            q["artist_name"] = artist
        if album:
            q["album_name"] = album
        if dur:
            q["duration"] = str(int(dur))
        text = self.pick(self.fetch("https://lrclib.net/api/get?" + urllib.parse.urlencode(q)))
        if text:
            return text
        sq = {"track_name": title}
        if artist:
            sq["artist_name"] = artist
        res = self.fetch("https://lrclib.net/api/search?" + urllib.parse.urlencode(sq)) or []
        res = [r for r in res if not r.get("instrumental")]
        if dur:   # la versión con la duración más parecida primero
            res.sort(key=lambda r: abs((r.get("duration") or 0) - dur))
        if self.prefer_synced:
            res.sort(key=lambda r: not r.get("syncedLyrics"))
        for r in res:
            text = self.pick(r)
            if text:
                return text
        return ""

    def netease(self, artist, title, dur):
        h = {"Referer": "https://music.163.com/", "User-Agent": "Mozilla/5.0"}
        q = urllib.parse.urlencode({"s": f"{title} {artist}".strip(), "type": 1, "limit": 8})
        d = self.fetch("https://music.163.com/api/search/get/web?" + q, "NetEase", h, tries=2) or {}
        songs = ((d.get("result") or {}).get("songs")) or []
        nt, na = _norm(title), _norm(artist)
        best = None
        for sg in songs:
            arts = " ".join(a.get("name", "") for a in sg.get("artists") or [])
            if nt and nt not in _norm(sg.get("name")) and _norm(sg.get("name")) not in nt:
                continue
            if na and na not in _norm(arts) and _norm(arts) not in na:
                continue   # sin coincidir el artista podría ser otra canción: mejor nada que una letra equivocada
            if dur and sg.get("duration") and abs(sg["duration"] / 1000 - dur) > 8:
                continue
            best = sg
            break
        if not best:
            return ""
        d = self.fetch(f"https://music.163.com/api/song/lyric?id={best['id']}&lv=1&kv=1&tv=-1", "NetEase", h, tries=2) or {}
        text = ((d.get("lrc") or {}).get("lyric") or "").strip()
        # quita las líneas de créditos de NetEase («作词 : …», «作曲 : …»)
        text = "\n".join(l for l in text.splitlines() if not re.search(r"\]\s*(作词|作曲|编曲|制作人|混音|母带)", l))
        if not self.prefer_synced and is_lrc(text):
            text = "\n".join(t for t, _ in parse_lrc(text))
        return text if len(text.strip()) > 20 else ""

    def lyrics_ovh(self, artist, title):
        if not artist:
            return ""
        d = self.fetch(f"https://api.lyrics.ovh/v1/{urllib.parse.quote(artist)}/{urllib.parse.quote(title)}",
                       "lyrics.ovh", tries=2) or {}
        text = (d.get("lyrics") or "").strip()
        return text if len(text) > 20 else ""

    def find(self, artist, title, album, dur):
        """Devuelve (letra, fuente). Lanza error solo si NINGÚN servicio respondió."""
        ca, ct = _main_artist(artist), _clean_title(title)
        tries = [("LRCLIB", lambda: self.lrclib(artist, title, album, dur))]
        if (ca, ct) != (artist, title):
            tries.append(("LRCLIB", lambda: self.lrclib(ca, ct, "", dur)))
        tries += [("NetEase", lambda: self.netease(ca, ct, dur)), ("lyrics.ovh", lambda: self.lyrics_ovh(ca, ct))]
        answered, last, plain = False, None, None
        for name, fn in tries:
            try:
                text = fn()
                answered = True
            except Exception as e:
                last = e
                continue
            if text and self.prefer_synced and not is_lrc(text):
                plain = plain or (text, name)   # hay letra normal: se sigue buscando una sincronizada
                continue
            if text:
                return text, name
        if plain:
            return plain
        if not answered and last is not None:
            raise last
        return "", ""

    def run(self):
        pending, last = list(self.jobs), ""
        for round_ in range(2):   # si hubo errores de conexión, se reintentan solos una vez más tras una pausa
            if round_:
                time.sleep(4)
            failed = []
            for job in pending:
                path, artist, title, album, dur = job
                try:
                    text, src = self.find(artist, title, album, dur)
                except Exception as e:
                    failed.append(job)
                    last = str(e)
                    continue
                if text:
                    self.sources[src] = self.sources.get(src, 0) + 1
                else:
                    self.not_found.append(path)
                self.got.emit(path, text)
            pending = failed
            if not pending:
                break
        self.errored = [j[0] for j in pending]
        if pending and len(pending) == len(self.jobs):
            self.failed.emit(last + ". Se reintentó automáticamente sin éxito.")
        else:
            self.finished_all.emit()


# ------------------------------------------------------------------ Widgets


class ClickSlider(QSlider):
    """Barra en la que un clic salta directamente a ese punto (y también se puede arrastrar).
    Muestra un globo con el valor al pasar el ratón y, si wheel_step > 0, se mueve con la rueda."""
    seekTo = pyqtSignal(int)

    def __init__(self, *a):
        super().__init__(*a)
        self.tip_fn, self.wheel_step = None, 0
        self.setMouseTracking(True)

    def _handle(self):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)

    def value_at(self, x, y=None):
        h = self._handle()
        if self.orientation() == Qt.Orientation.Vertical and y is not None:
            span = max(1, self.height() - h.height())
            py = max(0, min(span, int(y) - h.height() // 2))
            return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), py, span, True)
        span = max(1, self.width() - h.width())
        px = max(0, min(span, int(x) - h.width() // 2))
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), px, span)

    def show_tip(self, value, gpos):
        if self.tip_fn:
            QToolTip.showText(gpos, self.tip_fn(value), self)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._handle().contains(e.position().toPoint()):
            v = self.value_at(e.position().x(), e.position().y())
            self.setValue(v)
            self.seekTo.emit(v)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        self.show_tip(self.value_at(e.position().x(), e.position().y()), e.globalPosition().toPoint())

    def leaveEvent(self, e):
        QToolTip.hideText()
        super().leaveEvent(e)

    def wheelEvent(self, e):
        if self.wheel_step:
            d = e.angleDelta().y()
            if d:
                self.setValue(self.value() + (self.wheel_step if d > 0 else -self.wheel_step))
                self.show_tip(self.value(), e.globalPosition().toPoint())
            e.accept()
        else:
            super().wheelEvent(e)


class PlayButton(QPushButton):
    """Botón de reproducir/pausa dibujado a mano: círculo con degradado y brillo al pasar el ratón."""
    def __init__(self):
        super().__init__()
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setObjectName("playbtn2")
        self.setFlat(True)
        self.playing = False

    def set_playing(self, on):
        self.playing = bool(on)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.palette().color(QPalette.ColorRole.Highlight)
        full = QRectF(self.rect())
        if self.underMouse() and self.isEnabled():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(base.red(), base.green(), base.blue(), 70))
            p.drawEllipse(full)
        r = full.adjusted(3, 3, -3, -3)
        if self.isDown():
            r = r.adjusted(1, 1, -1, -1)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, base.lighter(135))
        g.setColorAt(1, base.darker(120))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g if self.isEnabled() else QColor(120, 120, 130)))
        p.drawEllipse(r)
        p.setBrush(QColor("white"))
        c = r.center()
        if self.playing:
            p.drawRoundedRect(QRectF(c.x() - 5.5, c.y() - 6, 4, 12), 1.5, 1.5)
            p.drawRoundedRect(QRectF(c.x() + 1.5, c.y() - 6, 4, 12), 1.5, 1.5)
        else:
            p.drawPolygon(QPolygonF([QPointF(c.x() - 4, c.y() - 7), QPointF(c.x() - 4, c.y() + 7),
                                     QPointF(c.x() + 7, c.y())]))


class GlyphButton(QPushButton):
    """Botones del reproductor dibujados a mano (anterior, siguiente, detener, lista) con el color del programa,
    para que cambien junto con el botón de reproducir."""
    def __init__(self, kind, size=30):
        super().__init__()
        self.kind = kind
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFlat(True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = self.palette().color(QPalette.ColorRole.Highlight)
        full = QRectF(self.rect())
        on = self.isEnabled()
        if self.underMouse() and on:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(base.red(), base.green(), base.blue(), 70))
            p.drawEllipse(full)
        col = base.lighter(125) if on else QColor(120, 120, 130)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        c = full.center()
        if self.isDown():
            c = QPointF(c.x() + 0.8, c.y() + 0.8)
        x, y = c.x(), c.y()
        k = self.kind
        if k == "prev":
            p.drawRoundedRect(QRectF(x - 7, y - 6, 2.6, 12), 1, 1)
            p.drawPolygon(QPolygonF([QPointF(x + 7, y - 6.5), QPointF(x + 7, y + 6.5), QPointF(x - 3.5, y)]))
        elif k == "next":
            p.drawRoundedRect(QRectF(x + 4.4, y - 6, 2.6, 12), 1, 1)
            p.drawPolygon(QPolygonF([QPointF(x - 7, y - 6.5), QPointF(x - 7, y + 6.5), QPointF(x + 3.5, y)]))
        elif k == "stop":
            p.drawRoundedRect(QRectF(x - 5.5, y - 5.5, 11, 11), 2, 2)
        elif k != "list":   # el resto de iconos vienen de icons.py (por ejemplo «fx»)
            p.save()
            icons.draw_glyph(p, k, full.adjusted(5, 5, -5, -5), col)
            p.restore()
        else:   # lista
            for dy in (-5, 0, 5):
                p.drawRoundedRect(QRectF(x - 7, y + dy - 1.3, 14, 2.6), 1.3, 1.3)


class TreeEditDelegate(QStyledItemDelegate):
    """Cuadro para renombrar carpetas en el árbol: del alto de la fila, con borde de color y el nombre seleccionado."""
    def paint(self, p, option, index):
        tree = self.parent()
        if index.data(PATH_ROLE) in getattr(tree, "cut_paths", ()):
            p.save()
            p.setOpacity(0.42)
            super().paint(p, option, index)
            p.restore()
            return
        super().paint(p, option, index)

    def createEditor(self, parent, option, index):
        ed = super().createEditor(parent, option, index)
        if isinstance(ed, QLineEdit):
            ed.setObjectName("treeedit")
        return ed

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            editor.selectAll()

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect
        vp = editor.parentWidget().rect() if editor.parentWidget() else r
        x = r.x() + option.decorationSize.width() + 6
        w = max(220, min(vp.width() - x - 4, r.width() + 120))
        editor.setGeometry(QRect(x, r.y() - 1, w, r.height() + 2))


class FolderTree(QTreeWidget):
    """Árbol de carpetas. Arrastra carpetas o canciones y suéltalas en otra carpeta,
    incluso desde un árbol hacia el otro."""
    dropped = pyqtSignal(list, str)

    def __init__(self, folder_icon):
        super().__init__()
        self.folder_icon = folder_icon
        self.setHeaderHidden(True)
        # barra horizontal: la columna crece con los nombres largos / carpetas muy anidadas
        self.header().setStretchLastSection(False)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setAutoScrollMargin(40)
        self.setIndentation(16)
        self._hl = None
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(False)   # en su lugar se resalta la carpeta destino
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setAutoExpandDelay(-1)   # no abre carpetas por sí solo al arrastrar
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.itemExpanded.connect(self.on_expand)
        self.setItemDelegate(TreeEditDelegate(self))

    # ---- sombrear varias carpetas (arrastrando hacia arriba/abajo desde una no elegida) o arrastrarlas
    def mousePressEvent(self, e):
        it = self.itemAt(e.position().toPoint())
        left = e.button() == Qt.MouseButton.LeftButton
        self._t_press = e.position().toPoint() if left else None
        self._t_item = it
        # Qt decide «arrastrar» ya en el primer movimiento: si pulsas una carpeta no elegida, de entrada se sombrea;
        # si luego mueves hacia un lado, la arrastramos nosotros
        self._t_free = left and it is not None and not it.isSelected() and not (
            e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        if self._t_free:
            self.setDragEnabled(False)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        pp = getattr(self, "_t_press", None)
        if pp is not None and getattr(self, "_t_free", False) and e.buttons() & Qt.MouseButton.LeftButton:
            d = e.position().toPoint() - pp
            if d.manhattanLength() >= QApplication.startDragDistance():
                self._t_free = False
                if abs(d.x()) > abs(d.y()) and self._t_item is not None:   # hacia un lado: arrastrar esa carpeta
                    it = self._t_item
                    self._t_press = None
                    self.setState(QAbstractItemView.State.NoState)
                    self.clearSelection()
                    it.setSelected(True)
                    self.setCurrentItem(it)
                    self.setDragEnabled(True)
                    self.startDrag(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
                    return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._t_press, self._t_free = None, False
        if not self.dragEnabled():
            self.setDragEnabled(True)

    # ---- arrastrar y soltar
    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(i.data(0, PATH_ROLE)) for i in items if i.data(0, PATH_ROLE)])
        return md

    def startDrag(self, supportedActions):
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.setPixmap(self.folder_icon.pixmap(QSize(32, 32)))
        DRAG_ACTIVE[0] = True
        try:
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)
        finally:
            DRAG_ACTIVE[0] = False

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def set_highlight(self, it):
        if it is self._hl:
            return
        if self._hl is not None:
            try:
                self._hl.setBackground(0, QBrush())
            except RuntimeError:
                pass
        self._hl = it
        if it is not None:
            c = QColor(self.palette().color(QPalette.ColorRole.Highlight))
            c.setAlpha(120)
            it.setBackground(0, QBrush(c))

    def dragMoveEvent(self, e):
        super().dragMoveEvent(e)
        it = self.itemAt(e.position().toPoint())
        self.set_highlight(it if it is not None and it.data(0, PATH_ROLE) else None)
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.set_highlight(None)
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self.set_highlight(None)
        it = self.itemAt(e.position().toPoint())
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        e.setDropAction(Qt.DropAction.CopyAction)  # evita que la vista borre nada por su cuenta
        e.accept()
        self.setState(QAbstractItemView.State.NoState)
        self.viewport().update()
        if it is not None and it.data(0, PATH_ROLE):
            self.dropped.emit(paths, it.data(0, PATH_ROLE))

    # ---- contenido (carga perezosa de subcarpetas)
    def make_item(self, path, text=None):
        it = QTreeWidgetItem([text or os.path.basename(path) or path])
        it.setData(0, PATH_ROLE, path)
        it.setIcon(0, self.folder_icon)
        return it

    def add_placeholder(self, item):
        if has_subdirs(item.data(0, PATH_ROLE)):
            ph = QTreeWidgetItem(["…"])
            ph.setFlags(Qt.ItemFlag.ItemIsEnabled)   # no se puede seleccionar ni marcar
            item.addChild(ph)

    def build(self, entries):
        self.clear()
        for name, p, kind in entries:
            it = self.make_item(p, name)
            it.setData(0, KIND_ROLE, kind)
            self.addTopLevelItem(it)
            self.add_placeholder(it)

    def on_expand(self, item):
        if item.childCount() == 1 and item.child(0).data(0, PATH_ROLE) is None:
            self.rebuild_children(item, set())

    def rebuild_children(self, item, exp):
        item.takeChildren()
        for name, p in subdirs(item.data(0, PATH_ROLE)):
            ch = self.make_item(p, name)
            item.addChild(ch)
            if p in exp:
                self.rebuild_children(ch, exp)
                ch.setExpanded(True)
            else:
                self.add_placeholder(ch)

    def all_items(self):
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            it = stack.pop()
            yield it
            stack.extend(it.child(i) for i in range(it.childCount()))

    def keep_scroll(self):
        """Devuelve una función que deja el árbol desplazado donde estaba (al refrescar no salta abajo)."""
        vs, hs = self.verticalScrollBar().value(), self.horizontalScrollBar().value()

        def back():
            self.verticalScrollBar().setValue(vs)
            self.horizontalScrollBar().setValue(hs)
        return back

    def refresh(self):
        back = self.keep_scroll()
        exp = {it.data(0, PATH_ROLE) for it in self.all_items() if it.isExpanded()}
        cur = self.currentItem()
        curp = cur.data(0, PATH_ROLE) if cur else None
        self.setUpdatesEnabled(False)
        auto = self.hasAutoScroll()
        self.setAutoScroll(False)   # elegir la carpeta actual no debe mover el árbol
        self.blockSignals(True)
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if top.isExpanded():
                self.rebuild_children(top, exp)
            else:
                top.takeChildren()
                self.add_placeholder(top)
        for it in self.all_items():
            if it.data(0, PATH_ROLE) == curp:
                self.setCurrentItem(it)
                break
        for it in self.all_items():          # al seleccionar, Qt abre las carpetas padre: deja cada una como estaba
            p = it.data(0, PATH_ROLE)
            if p is not None and it.isExpanded() != (p in exp) and it.childCount():
                it.setExpanded(p in exp)
        self.blockSignals(False)
        self.setAutoScroll(auto)
        back()
        self.setUpdatesEnabled(True)
        QTimer.singleShot(0, back)

    def reveal(self, path):
        """Expande el árbol hasta la carpeta indicada y la selecciona."""
        npath = norm(path)
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            tp = norm(item.data(0, PATH_ROLE))
            if not (npath == tp or npath.startswith(tp + os.sep)):
                continue
            while norm(item.data(0, PATH_ROLE)) != npath:
                item.setExpanded(True)  # carga sus subcarpetas
                nxt = None
                for j in range(item.childCount()):
                    cp = item.child(j).data(0, PATH_ROLE)
                    if cp and (npath == norm(cp) or npath.startswith(norm(cp) + os.sep)):
                        nxt = item.child(j)
                        break
                if nxt is None:
                    return False
                item = nxt
            self.setCurrentItem(item)
            self.scrollToItem(item)
            return True
        return False

    def selected_dirs(self):
        return [i.data(0, PATH_ROLE) for i in self.selectedItems() if i.data(0, PATH_ROLE)]


class ChatWorker(AIBase):
    """Una vuelta de conversación con la IA (con todo el historial)."""
    reply = pyqtSignal(str)

    def __init__(self, provider, model, key, messages, system):
        super().__init__(provider, model, key)
        self.messages, self.system = messages, system

    def run(self):
        try:
            self.reply.emit(self.chat(self.messages, self.system).strip())
        except urllib.error.HTTPError as e:
            self.failed.emit(self.error_text(e))
        except Exception as e:
            self.failed.emit(str(e))


class MetaAIWorker(AIBase):
    """Pide a la IA los metadatos de una canción a partir del título y el artista."""
    result = pyqtSignal(dict)

    def __init__(self, provider, model, key, title, artist, discogs_token=""):
        super().__init__(provider, model, key)
        self.title, self.artist = title, artist
        self.discogs_token = discogs_token or ""
        self.sources = []

    @staticmethod
    def _norm(t):
        t = re.sub(r"\(.*?\)|\[.*?\]|feat\..*|ft\..*", " ", (t or "").lower())
        return re.sub(r"[^0-9a-záéíóúñü]+", " ", t).strip()

    def _get(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": "MusicManager (https://github.com/PandxMax/MusicManager)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))

    def catalog(self):
        """Datos reales del catálogo de iTunes (y Deezer de respaldo): álbum, año, pista, disco, género."""
        t, a = self._norm(self.title), self._norm(self.artist)
        out = {}
        try:
            d = self._get("https://itunes.apple.com/search?entity=song&limit=25&term="
                          + quote_plus(f"{self.artist} {self.title}".strip()))
            best, best_sc, years = None, 0, []
            for r in d.get("results", []):
                rt, ra = self._norm(r.get("trackName")), self._norm(r.get("artistName"))
                sc = (3 if rt == t else 2 if t and (t in rt or rt in t) else 0)
                sc += (3 if a and (a in ra or ra in a) else 0 if a else 1)
                coll = r.get("collectionName") or ""
                if sc >= 3 and not coll.endswith((" - Single", " - EP")):
                    sc += 1   # mejor el álbum original que el sencillo
                if sc >= 4 and (r.get("releaseDate") or "")[:4].isdigit():
                    years.append(r["releaseDate"][:4])   # año del primer lanzamiento (sencillo o álbum)
                if sc > best_sc:
                    best, best_sc = r, sc
            if best and best_sc >= 4:
                coll = re.sub(r" - (Single|EP)$", "", best.get("collectionName") or "")
                out = {"title": best.get("trackName", ""), "artist": best.get("artistName", ""),
                       "album": coll, "albumartist": best.get("collectionArtistName") or best.get("artistName", ""),
                       "genre": best.get("primaryGenreName", ""), "date": min(years) if years else (best.get("releaseDate") or "")[:4],
                       "tracknumber": str(best.get("trackNumber") or ""), "discnumber": str(best.get("discNumber") or "")}
                self.sources.append(("iTunes", dict(out)))
        except Exception:
            note_quiet()
        if True:   # Deezer siempre: aporta otra opción para elegir
            try:
                q = quote_plus(f'artist:"{self.artist}" track:"{self.title}"' if self.artist else self.title)
                d = self._get(f"https://api.deezer.com/search?q={q}&limit=5")
                hit = None
                for h in d.get("data") or []:   # solo si de verdad es la misma canción
                    ht, ha = self._norm(h.get("title")), self._norm((h.get("artist") or {}).get("name"))
                    if (ht == t or (t and (t in ht or ht in t))) and (not a or a in ha or ha in a):
                        hit = h
                        break
                if hit:
                    tr = self._get(f"https://api.deezer.com/track/{hit['id']}")
                    dz = {"title": tr.get("title", ""), "artist": (tr.get("artist") or {}).get("name", ""),
                          "album": (tr.get("album") or {}).get("title", ""),
                          "albumartist": (tr.get("artist") or {}).get("name", ""),
                          "date": (tr.get("release_date") or "")[:4],
                          "tracknumber": str(tr.get("track_position") or ""),
                          "discnumber": str(tr.get("disk_number") or "")}
                    dz = {k: v for k, v in dz.items() if v}
                    self.sources.append(("Deezer", dz))
                    out.update({k: v for k, v in dz.items() if not out.get(k)})
            except Exception:
                note_quiet()
        return {k: v for k, v in out.items() if v}

    def more_sources(self, found):
        """MusicBrainz (gratis) y Discogs (si tienes token): más opciones para elegir campo por campo."""
        try:
            import tagsource
        except Exception:
            return
        t, a = self._norm(self.title), self._norm(self.artist)
        try:
            hits = 0
            for r in tagsource.musicbrainz(self.artist, self.title, ""):   # varios lanzamientos = varias opciones
                if self._norm(r.get("title")) == t and (not a or a in self._norm(r.get("artist")) or self._norm(r.get("artist")) in a):
                    self.sources.append(("MusicBrainz", {k: v for k, v in r.items() if k in EASY_KEYS and v}))
                    hits += 1
                    if hits >= 4:
                        break
        except Exception:
            note_quiet()
        if self.discogs_token:
            try:
                hits = 0
                for r in tagsource.discogs(self.artist, self.title, found.get("album", ""), self.discogs_token):
                    if not a or a in self._norm(r.get("artist")) or self._norm(r.get("artist")) in a:
                        d = {k: v for k, v in r.items() if k in EASY_KEYS and v}
                        d.pop("title", None)
                        self.sources.append(("Discogs", d))
                        hits += 1
                        if hits >= 3:
                            break
            except Exception:
                note_quiet()

    def run(self):
        self.sources = []
        found = self.catalog()
        self.more_sources(found)
        for _src, d in self.sources:   # lo que falte en iTunes/Deezer se completa con MusicBrainz o Discogs
            for k, v in d.items():
                if v and not found.get(k):
                    found[k] = v
        system = ("Eres un asistente experto en metadatos musicales. Respondes SOLO con un objeto JSON válido, sin texto "
                  "extra ni bloques de código. Tu trabajo es RELLENAR TODOS LOS CAMPOS con los datos oficiales de la "
                  "canción. Solo deja un campo vacío si ese dato de verdad no existe o no lo conoces en absoluto.")
        known = json.dumps(found, ensure_ascii=False) if found else "ninguno"
        prompt = (f"Canción: «{self.title}». Artista: «{self.artist}».\n"
                  f"Datos ya comprobados en el catálogo de iTunes/Deezer (respétalos): {known}\n\n"
                  "Devuelve el JSON con TODAS estas claves (todos los valores como texto):\n"
                  "- title: título oficial\n- artist: intérprete principal (con «feat.» si corresponde)\n"
                  "- album: álbum original donde salió (si solo fue sencillo, el nombre del sencillo)\n"
                  "- albumartist: intérprete del álbum (normalmente el mismo artista; «Varios artistas» si es recopilatorio)\n"
                  "- composer: compositores/autores de la canción, separados por «; »\n"
                  "- genre: género principal y, si aplica, subgénero (ej. «Reguetón», «Rock alternativo», «Pop latino»)\n"
                  "- date: año de lanzamiento (4 dígitos)\n- tracknumber: número de pista en ese álbum (1 si es sencillo)\n"
                  "- discnumber: número de disco (1 si el álbum tiene un solo disco)\n"
                  "- comment: una nota breve y útil, por ejemplo «Sello: Sony Music · Productor: Tainy» (sin opiniones)")
        ai, err = {}, None
        try:
            txt = self.chat([{"role": "user", "content": prompt}], system)
            m = re.search(r"\{.*\}", txt, re.S)
            raw = json.loads(m.group(0)) if m else {}
            alias = {"track": "tracknumber", "disc": "discnumber", "year": "date", "album_artist": "albumartist",
                     "comments": "comment"}
            for k, v in raw.items():
                k = alias.get(k, k)
                if k in EASY_KEYS and v not in (None, "") and str(v).strip().lower() not in ("desconocido", "unknown", "n/a"):
                    ai[k] = str(v).strip()
        except urllib.error.HTTPError as e:
            err = self.error_text(e)
        except Exception as e:
            err = f"No pude leer la respuesta de la IA: {e}"
        # lo comprobado en el catálogo manda en los datos objetivos; la IA completa el resto
        data = dict(ai)
        for k in ("title", "artist", "album", "albumartist", "date", "tracknumber", "discnumber"):
            if found.get(k):
                data[k] = found[k]
        if not data.get("genre") and found.get("genre"):
            data["genre"] = found["genre"]
        if data.get("artist") and not data.get("albumartist"):
            data["albumartist"] = data["artist"]
        if data.get("album") and not data.get("discnumber"):
            data["discnumber"] = "1"
        m = re.match(r"\d{4}", data.get("date", ""))
        if data.get("date") and m:
            data["date"] = m.group(0)
        for k in ("tracknumber", "discnumber"):
            m = re.match(r"\d+", data.get(k, ""))
            if data.get(k):
                data[k] = m.group(0) if m else ""
        data = {k: v for k, v in data.items() if v}
        if ai:
            self.sources.append(("IA", ai))
        opts = {}
        for src, d in self.sources:   # todas las respuestas, campo por campo; si coinciden, se juntan sus fuentes
            for k, v in d.items():
                v = str(v).strip()
                if k not in EASY_KEYS or not v:
                    continue
                lst = opts.setdefault(k, [])
                for entry in lst:
                    if entry[0].lower() == v.lower():
                        if src not in entry[1]:
                            entry[1].append(src)
                        break
                else:
                    lst.append([v, [src]])
        if not data and err:
            self.failed.emit(err)
        else:
            data["_options"] = opts
            self.result.emit(data)


class MetaAIDialog(QDialog):
    def __init__(self, main, path, settings):
        super().__init__(main)
        self.main, self.path, self.settings, self.worker = main, path, settings, None
        self.setWindowTitle("✨ Rellenar metadatos con IA")
        self.resize(520, 520)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Escribe el nombre de la canción y el artista. La IA buscará los datos y podrás revisarlos "
                           "antes de aplicarlos. Puede equivocarse: comprueba lo importante."))
        v.itemAt(0).widget().setWordWrap(True)
        base = os.path.splitext(os.path.basename(path))[0]
        title, artist = main.val(path, "title"), main.val(path, "artist")
        if not title and " - " in base:
            artist, title = [x.strip() for x in base.split(" - ", 1)]
        if not title:
            title = base
        f = QFormLayout()
        self.t_le, self.a_le = QLineEdit(title), QLineEdit(artist)
        f.addRow("Canción", self.t_le)
        f.addRow("Artista", self.a_le)
        v.addLayout(f)
        self.go = QPushButton("🔎 Buscar con IA")
        self.go.setObjectName("accent")
        self.go.clicked.connect(self.search)
        v.addWidget(self.go)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.res_box = QGroupBox("Resultado (puedes corregirlo)")
        rf = QFormLayout(self.res_box)
        self.res = {}
        for k, n in FIELDS:
            cb = QComboBox()
            cb.setEditable(True)            # se puede elegir una opción o escribir otra
            cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            cb.setMinimumContentsLength(18)
            self.res[k] = cb
            rf.addRow(n, cb)
        self.res_box.setEnabled(False)
        v.addWidget(self.res_box, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.apply_btn = QPushButton("✔ Aplicar a la canción")
        self.apply_btn.setObjectName("accent")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        cl = QPushButton("Cerrar")
        cl.clicked.connect(self.reject)
        row.addWidget(self.apply_btn)
        row.addWidget(cl)
        v.addLayout(row)

    def search(self):
        t, a = self.t_le.text().strip(), self.a_le.text().strip()
        if not t:
            self.status.setText("Escribe el nombre de la canción.")
            return
        self.go.setEnabled(False)
        self.status.setText("Buscando en iTunes, Deezer, MusicBrainz, Discogs y con la IA…")
        prov, model, key = self.settings
        tok = secret.get(self.main.cfg, "discogs_token")
        self.worker = MetaAIWorker(prov, model, key, t, a, tok)
        self.worker.result.connect(self.on_result)
        self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def on_fail(self, msg):
        self.go.setEnabled(True)
        self.status.setText("No se pudo: " + msg)

    def on_result(self, data):
        self.go.setEnabled(True)
        if not data:
            self.status.setText("La IA no encontró datos fiables de esa canción. Prueba a escribir mejor el título o el artista.")
            return
        opts = data.pop("_options", {})
        for k, cb in self.res.items():
            try:
                cb.activated.disconnect()
            except TypeError:
                pass
            cb.clear()
            best = data.get(k, "")
            choices = [(v_, list(srcs_)) for v_, srcs_ in opts.get(k, [])]
            if best and all(best.lower() != v_.lower() for v_, _ in choices):
                choices.insert(0, (best, ["IA"]))
            for v_, srcs_ in choices:   # cada opción dice de dónde salió
                cb.addItem(f"{v_}     ←  {', '.join(T(x) for x in srcs_)}", v_)
                cb.setItemData(cb.count() - 1, T("Fuente: ") + ", ".join(T(x) for x in srcs_), Qt.ItemDataRole.ToolTipRole)
            # al elegir una opción, en el cuadro queda solo el valor (sin el nombre de la fuente)
            cb.activated.connect(lambda i, cb=cb: cb.setEditText(str(cb.itemData(i) or "")))
            cb.setEditText(best)
            n_ = len(choices)
            cb.setToolTip(T(f"{n_} opciones: ") + " · ".join(f"{v_} ({', '.join(srcs_)})" for v_, srcs_ in choices) if n_ else "")
            cb.setStyleSheet("QComboBox { border: 1px solid palette(highlight); }" if n_ > 1 else "")
        srcs = sorted({src for lst in opts.values() for _, srcs_ in lst for src in srcs_})
        self.res_box.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.status.setText(T("Fuentes: ") + (", ".join(srcs) or "IA") + ". " +
                            T("Los campos con borde de color tienen varias opciones: ábrelos para elegir. Solo se aplican los campos que no estén vacíos."))

    def apply(self):
        vals = {k: cb.currentText().strip() for k, cb in self.res.items() if cb.currentText().strip()}
        self.main.apply_ai_meta(self.path, vals)
        self.accept()


class GenreChat(QDialog):
    """Ventana para conversar con la IA y cuestionar/repensar el género de una canción."""
    QUICK = ["¿Estás seguro de esa decisión?",
             "Compara las opciones y dime cuál encaja mejor",
             "Dame más subgéneros posibles"]

    def __init__(self, main, path, settings):
        super().__init__(main)
        self.main, self.path, self.settings = main, path, settings
        self.history = main.chats.setdefault(path, [])
        self.worker, self.last_text = None, ""
        name = os.path.splitext(os.path.basename(path))[0]
        self.setWindowTitle(f"Hablar con la IA — {name}")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(580, 580)
        lay = QVBoxLayout(self)
        self.view = QTextBrowser()
        lay.addWidget(self.view, 1)
        qrow = QHBoxLayout()
        for t in self.QUICK:
            b = QPushButton(t)
            b.clicked.connect(lambda _=False, t=t: self.send(t))
            qrow.addWidget(b)
        lay.addLayout(qrow)
        irow = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Escribe tu duda o tu opinión… (Enter para enviar)")
        self.input.returnPressed.connect(self.send)
        self.btn_send = QPushButton("Enviar")
        self.btn_send.clicked.connect(self.send)
        irow.addWidget(self.input, 1)
        irow.addWidget(self.btn_send)
        lay.addLayout(irow)
        arow = QHBoxLayout()
        arow.addWidget(QLabel("Género a aplicar:"))
        self.apply_le = QLineEdit(main.val(path, "genre"))
        btn_apply = QPushButton("✔ Aplicar a la canción")
        btn_apply.clicked.connect(self.apply)
        arow.addWidget(self.apply_le, 1)
        arow.addWidget(btn_apply)
        lay.addLayout(arow)
        self.render()

    def system_prompt(self):
        m, p = self.main, self.path
        opts = ", ".join(v for _, v in m.suggestions.get(p, [])) or "(ninguna todavía)"
        return (
            "Eres un experto en música que ayuda a elegir el género o subgénero correcto para "
            "etiquetar una canción. "
            f"Canción: «{m.val(p, 'title') or os.path.splitext(os.path.basename(p))[0]}» · "
            f"artista: {m.val(p, 'artist') or 'desconocido'} · álbum: {m.val(p, 'album') or 'desconocido'} · "
            f"año: {m.val(p, 'date') or 'desconocido'}. Género actual: {m.val(p, 'genre') or 'ninguno'}. "
            f"Opciones sugeridas antes: {opts}. "
            "Responde en español, breve y razonado. Si la persona cuestiona la decisión, evalúala con "
            "honestidad: reconoce si te equivocaste y, si no, explica por qué la mantienes. No inventes "
            "datos: si no estás seguro, dilo. Cuando tengas una recomendación final, termina con una "
            "línea exacta: GÉNERO_SUGERIDO: <género o subgénero>")

    def render(self, thinking=False):
        parts = []
        if not self.history:
            parts.append("<p><i>Pregúntale lo que quieras sobre el género de esta canción: si está bien "
                         "elegido, por qué ese subgénero, o pídele alternativas.</i></p>")
        for m in self.history:
            if m["role"] == "user":
                parts.append("<p><b>Tú:</b> " + html.escape(m["content"]).replace("\n", "<br>") + "</p>")
            else:
                txt = re.sub(r"\n?GÉNERO_SUGERIDO:.*", "", m["content"]).strip()
                parts.append("<p><b>IA:</b> " + html.escape(txt).replace("\n", "<br>") + "</p>")
        if thinking:
            parts.append("<p><i>La IA está pensando…</i></p>")
        self.view.setHtml("".join(parts))
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send(self, text=None):
        text = (text if isinstance(text, str) else self.input.text()).strip()
        if not text or self.worker is not None:
            return
        self.last_text = text
        self.input.clear()
        self.history.append({"role": "user", "content": text})
        self.render(thinking=True)
        self.btn_send.setEnabled(False)
        prov, model, key = self.settings
        self.worker = ChatWorker(prov, model, key, list(self.history), self.system_prompt())
        self.worker.reply.connect(self.on_reply)
        self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def on_reply(self, text):
        self.worker = None
        self.btn_send.setEnabled(True)
        self.history.append({"role": "assistant", "content": text})
        m = re.search(r"GÉNERO_SUGERIDO:\s*(.+)", text)
        if m:
            self.apply_le.setText(m.group(1).strip().strip("«»\"'*. "))
        self.render()

    def on_fail(self, msg):
        self.worker = None
        self.btn_send.setEnabled(True)
        if self.history and self.history[-1]["role"] == "user":
            self.history.pop()
        self.input.setText(self.last_text)  # para reintentar sin volver a escribir
        self.render()
        QMessageBox.warning(self, "Error de IA", msg)

    def apply(self):
        self.main.apply_genre(self.path, self.apply_le.text().strip())


class RenameBox(QPlainTextEdit):
    """Cuadro para renombrar en modo iconos, como el Explorador de Windows: del ancho del icono, el nombre se parte
    en varias líneas y el cuadro crece hacia abajo. Enter guarda, Esc cancela."""
    done = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("renamebox")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.setTabChangesFocus(True)
        self.document().setDocumentMargin(2)
        opt = self.document().defaultTextOption()
        opt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.document().setDefaultTextOption(opt)
        self.textChanged.connect(self.fit)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.done.emit()
            return
        super().keyPressEvent(e)

    def insertFromMimeData(self, src):
        self.insertPlainText(src.text().replace("\r", " ").replace("\n", " "))

    def fit(self):
        """Mismo ancho que la tarjeta y alto según las líneas del nombre: si no cabe en la tarjeta, la tarjeta
        «crece» hacia abajo (el borde del cuadro es del mismo color que la tarjeta)."""
        fm = self.fontMetrics()
        b = 2 * self.frameWidth() + int(2 * self.document().documentMargin())
        inner = max(20, self.width() - b - 6)
        br = fm.boundingRect(QRect(0, 0, inner, 10000),
                             int(Qt.TextFlag.TextWrapAnywhere.value | Qt.AlignmentFlag.AlignHCenter.value),
                             self.toPlainText() or " ")
        h = max(getattr(self, "min_h", 30), br.height() + b + 6)
        if h != self.height():
            self.resize(self.width(), h)
        self.ensureCursorVisible()

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.fit)


class SongDelegate(QStyledItemDelegate):
    """Delegado de la lista en modo iconos/lista: los nombres largos se ven en varias líneas (no se cortan con «…»
    a la primera) y el cuadro para renombrar es ancho y se ve entero."""
    def __init__(self, lst):
        super().__init__(lst)
        self.lst = lst

    def _icons(self):
        return self.lst.viewMode() == QListView.ViewMode.IconMode and self.lst.gridSize().isValid()

    def sizeHint(self, option, index):
        if self._icons():   # todas del mismo tamaño que la cuadrícula: caben 3 líneas de nombre
            g = self.lst.gridSize()
            return QSize(g.width() - 6, g.height() - 6)
        return super().sizeHint(option, index)

    def paint(self, p, option, index):
        if index.data(PATH_ROLE) in getattr(self.lst, "cut_paths", ()):
            p.save()
            p.setOpacity(0.42)   # cortado (Ctrl+X): se ve medio transparente, como en el Explorador
            self._paint(p, option, index)
            p.restore()
            return
        self._paint(p, option, index)

    def _paint(self, p, option, index):
        ed = getattr(self, "editing", None)
        if ed is not None and ed.isValid() and ed == QPersistentModelIndex(index):
            # renombrando: la tarjeta de color se queda igual (mismo tamaño); solo se oculta el nombre, que se
            # escribe en el cuadro fijo que va dentro de la tarjeta, en el mismo sitio
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            opt.text = ""
            st = opt.widget.style() if opt.widget else QApplication.style()
            st.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        else:
            super().paint(p, option, index)
        if option.state & QStyle.StateFlag.State_Selected:
            # la portada de la canción elegida se ve con sus colores reales (sin el tinte de color encima)
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            if not opt.icon.isNull():
                st = (opt.widget.style() if opt.widget else QApplication.style())
                r = st.subElementRect(QStyle.SubElement.SE_ItemViewItemDecoration, opt, opt.widget)
                pm = opt.icon.pixmap(opt.decorationSize, QIcon.Mode.Normal)
                if not pm.isNull() and r.isValid():
                    sz = pm.deviceIndependentSize().toSize()
                    x = r.x() + (r.width() - sz.width()) // 2
                    y = r.y() + (r.height() - sz.height()) // 2
                    p.drawPixmap(x, y, pm)

    def createEditor(self, parent, option, index):
        if self._icons():
            ed = RenameBox(parent)
            ed.done.connect(lambda ed=ed: (self.commitData.emit(ed),
                                           self.closeEditor.emit(ed, QAbstractItemDelegate.EndEditHint.NoHint)))
            self.editing = QPersistentModelIndex(index)
            ed.destroyed.connect(self._edit_done)
            return ed
        ed = super().createEditor(parent, option, index)
        if isinstance(ed, QLineEdit):
            ed.setObjectName("renameedit")
            if self._icons():
                ed.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.editing = QPersistentModelIndex(index)   # mientras se escribe, el nombre de debajo no se pinta
            ed.destroyed.connect(self._edit_done)
        return ed

    def _edit_done(self, *_):
        self.editing = None
        try:
            self.lst.viewport().update()
        except RuntimeError:
            pass

    def setEditorData(self, editor, index):
        if isinstance(editor, RenameBox):
            editor.setPlainText(str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
            editor.selectAll()
            editor.fit()
            return
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            editor.selectAll()

    def setModelData(self, editor, model, index):
        if isinstance(editor, RenameBox):
            model.setData(index, " ".join(editor.toPlainText().split()), Qt.ItemDataRole.EditRole)
            return
        super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, option, index):
        r = option.rect
        vp = self.lst.viewport().rect()
        isz = self.lst.iconSize()
        if isinstance(editor, RenameBox):   # parte de abajo de la tarjeta: mismo ancho; crece si el nombre es largo
            y = r.top() + isz.height() + 2
            editor.min_h = max(30, r.bottom() - y + 1)
            editor.setGeometry(QRect(r.x(), y, r.width(), max(editor.min_h, editor.height())))
            editor.fit()
            return
        if self._icons():
            # cuadro compacto justo donde va el nombre (el nombre viejo se oculta mientras escribes)
            w = min(max(r.width() + 24, 190), vp.width() - 8)
            x = max(4, min(r.center().x() - w // 2, vp.width() - w - 4))
            h = 28
            y = min(r.top() + isz.height() + 8, vp.height() - h - 2)
            editor.setGeometry(QRect(x, y, w, h))
        else:
            x = r.x() + isz.width() + 10
            w = max(min(vp.width() - x - 6, 520), 220)
            h = max(r.height(), 28)
            editor.setGeometry(QRect(x, r.y() + (r.height() - h) // 2, w, h))


class SongList(QListWidget):
    """Canciones (y subcarpetas) como en un explorador. El arrastre se maneja a mano para
    que funcione siempre: se puede soltar sobre una carpeta de esta lista o de los árboles."""
    dropped = pyqtSignal(list, str)
    selection_done = pyqtSignal()  # el usuario soltó el botón: ya terminó de seleccionar

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragEnabled(False)  # el arrastre lo iniciamos nosotros (más fiable en modo iconos)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self._press, self._press_item, self._hover = None, None, None
        self._selecting = False
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(48)
        self.overlay = QLabel(self.viewport())
        self.overlay.setObjectName("hint")
        self.overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay.setWordWrap(True)
        self.overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.overlay.hide()
        self._auto = QTimer(self)
        self._auto.setInterval(30)
        self._auto.timeout.connect(self._auto_tick)

    def _auto_tick(self):
        """Al sombrear y llevar el ratón por debajo (o encima) de la lista, se desplaza rápido: más lejos = más rápido."""
        if not self.selecting:
            self._auto.stop()
            return
        lp = self.viewport().mapFromGlobal(QCursor.pos())
        h = self.viewport().height()
        edge = 28
        if lp.y() > h - edge:
            dist = lp.y() - (h - edge)
        elif lp.y() < edge:
            dist = lp.y() - edge
        else:
            return
        step = int(max(10, min(140, abs(dist) * 0.9))) * (1 if dist > 0 else -1)
        sb = self.verticalScrollBar()
        old = sb.value()
        sb.setValue(old + step)
        if sb.value() != old:
            self._nudge()   # que la selección siga al ratón

    @property
    def selecting(self):
        """True mientras se mantiene apretado el botón izquierdo (arrastrando el recuadro de selección)."""
        return self._selecting and bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)

    def wheelEvent(self, e):
        super().wheelEvent(e)
        if self.selecting:  # sigue seleccionando mientras bajas con la rueda
            QTimer.singleShot(0, self._nudge)

    def _nudge(self):
        if not self.selecting:
            return
        try:
            gp = QCursor.pos()
            lp = self.viewport().mapFromGlobal(gp)
            ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(lp), QPointF(gp), Qt.MouseButton.NoButton,
                             QApplication.mouseButtons(), QApplication.keyboardModifiers())
            QApplication.sendEvent(self.viewport(), ev)  # hace que el recuadro y la selección se actualicen
        except Exception:
            note_quiet()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.overlay.setGeometry(self.viewport().rect())

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(i.data(PATH_ROLE)) for i in items])
        return md

    def _clear_band(self):
        """El arrastre se «come» el soltar del ratón y la lista se quedaba con el recuadro de selección pintado.
        Se le envía un «soltar» de mentira para que lo borre."""
        try:
            lp = self.viewport().mapFromGlobal(QCursor.pos())
            ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(lp), QPointF(QCursor.pos()), Qt.MouseButton.LeftButton,
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            sel = [self.item(r) for r in range(self.count()) if self.item(r).isSelected()]
            self.blockSignals(True)
            QListWidget.mouseReleaseEvent(self, ev)
            for it in sel:   # que el «soltar» falso no cambie lo que estaba elegido
                it.setSelected(True)
            self.blockSignals(False)
            self.viewport().update()
        except Exception:
            self.blockSignals(False)

    def reset_state(self):
        """Tras un arrastre propio, Qt puede quedarse «seleccionando» (recuadro fantasma y selección pegada). Lo limpia."""
        try:
            self.setState(QAbstractItemView.State.NoState)
        except Exception:
            note_quiet()
        for rb in self.findChildren(QRubberBand):
            rb.hide()
        self._selecting = False
        self.viewport().update()

    # ---- iniciar el arrastre
    def mousePressEvent(self, e):
        if not (QApplication.mouseButtons() & ~Qt.MouseButton.LeftButton) and self.state() != QAbstractItemView.State.NoState:
            self.reset_state()
        self._keep_multi = None
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            self._press_item = self.itemAt(self._press)
            self._press_unsel = self._press_item is not None and not self._press_item.isSelected()
            self._selecting = True
            self._auto.start()
            it = self._press_item
            if it is not None and it.isSelected() and len(self.selectedItems()) > 1:
                # pulsas sobre una de varias ya elegidas (aunque tengas Shift o Ctrl apretado): la selección no se toca
                # hasta saber si es un clic o un arrastre; así se arrastran TODAS las elegidas
                self._keep_multi = it
                self._keep_sel = list(self.selectedItems())
                self._keep_ev = e.clone() if hasattr(e, "clone") else None
                self._selecting = False
                return
        else:
            self._press, self._press_item = None, None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press is not None and self._press_item is not None
                and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            d = e.position().toPoint() - self._press
            if (self.viewMode() == QListView.ViewMode.ListMode and getattr(self, "_press_unsel", False)
                    and abs(d.y()) >= abs(d.x())):
                # modo lista/detalles: arrastrar hacia arriba/abajo desde una canción no elegida = sombrear varias
                # (para mover archivos: arrastra una ya elegida, o hacia un lado)
                self._press, self._press_item = None, None
                super().mouseMoveEvent(e)
                return
            item, self._press, self._press_item = self._press_item, None, None
            snap = getattr(self, "_keep_sel", None) if self._keep_multi is not None else None
            self._keep_multi, self._keep_sel, self._keep_ev = None, None, None
            if snap:   # por si algo cambió la selección entre el clic y el arrastre: se vuelven a marcar todas
                for x in snap:
                    try:
                        x.setSelected(True)
                    except RuntimeError:
                        pass
            self.begin_drag(item)
            return
        super().mouseMoveEvent(e)

    def mouseDoubleClickEvent(self, e):
        # el doble clic siempre abre/reproduce lo que está bajo el cursor (aunque antes hubiera varias elegidas)
        it = self.itemAt(e.position().toPoint())
        if e.button() == Qt.MouseButton.LeftButton and it is not None:
            self._keep_multi = None
            self.clearSelection()
            it.setSelected(True)
            self.setCurrentItem(it)
            self.itemDoubleClicked.emit(it)
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def mouseReleaseEvent(self, e):
        self._press, self._press_item = None, None
        keep = getattr(self, "_keep_multi", None)
        self._keep_multi = None
        if keep is not None and e.button() == Qt.MouseButton.LeftButton:
            # fue un clic (no un arrastre)
            pe = getattr(self, "_keep_ev", None)
            self._keep_ev = None
            if pe is not None and pe.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                super().mousePressEvent(pe)   # con Ctrl/Shift: se comporta como siempre (quitar / ampliar)
                super().mouseReleaseEvent(e)
            else:   # sin teclas: ahora sí queda elegida solo esa
                self.clearSelection()
                keep.setSelected(True)
                self.setCurrentItem(keep)
            self.selection_done.emit()
            return
        super().mouseReleaseEvent(e)
        if e.button() == Qt.MouseButton.LeftButton:
            self._selecting = False
            self.reset_state()
            self.selection_done.emit()

    def begin_drag(self, item):
        if not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
        items = self.selectedItems()
        if not items:
            return
        drag = QDrag(self)
        drag.setMimeData(self.mimeData(items))
        drag.setPixmap(item.icon().pixmap(QSize(72, 72)))
        paths = [i.data(PATH_ROLE) for i in items]
        # resalta la carpeta de esta lista que está bajo el cursor mientras arrastras (no depende de los eventos de Qt)
        hover_timer = QTimer(self)
        hover_timer.setInterval(50)

        def hover_tick():
            lp = self.viewport().mapFromGlobal(QCursor.pos())
            it = self._dir_at(lp) if self.viewport().rect().contains(lp) else None
            if it is not None and it.data(PATH_ROLE) in paths:
                it = None
            self._set_hover(it)
        hover_timer.timeout.connect(hover_tick)
        hover_timer.start()
        result = Qt.DropAction.IgnoreAction
        try:
            DRAG_ACTIVE[0] = True
            result = drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
            DRAG_ACTIVE[0] = False
            hover_timer.stop()
            if result == Qt.DropAction.IgnoreAction:   # Qt no aceptó el soltar: lo resolvemos nosotros
                lp = self.viewport().mapFromGlobal(QCursor.pos())
                it = self._dir_at(lp) if self.viewport().rect().contains(lp) else None
                if it is not None and it.data(PATH_ROLE) not in paths:
                    self.dropped.emit(paths, it.data(PATH_ROLE))
        finally:
            DRAG_ACTIVE[0] = False
            hover_timer.stop()
            self._selecting = False
            self._clear_band()
            self._set_hover(None)
            self.reset_state()
            QTimer.singleShot(0, self.reset_state)   # y otra vez cuando termina el evento, por si Qt lo vuelve a activar

    # ---- recibir: solo se puede soltar sobre una carpeta de la lista
    def _dir_at(self, pos):
        it = self.itemAt(pos)
        return it if it is not None and it.data(KIND_ROLE) == "dir" else None

    def _set_hover(self, it):
        if self._hover is not it:
            self._hover = it
            self.viewport().update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._hover is not None:   # resalta la carpeta de destino (se dibuja a mano: no depende de los estilos)
            try:
                r = QRectF(self.visualItemRect(self._hover)).adjusted(1, 1, -1, -1)
                p = QPainter(self.viewport())
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                base = self.palette().color(QPalette.ColorRole.Highlight)
                p.setBrush(QColor(base.red(), base.green(), base.blue(), 95))
                p.setPen(QPen(base, 2))
                p.drawRoundedRect(r, 10, 10)
                p.end()
            except RuntimeError:
                self._hover = None

    def _cursor_dir(self):
        lp = self.viewport().mapFromGlobal(QCursor.pos())
        return self._dir_at(lp) if self.viewport().rect().contains(lp) else None

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        # se acepta siempre (así no sale el signo de «prohibido»); solo se resalta y se suelta sobre las carpetas
        self._set_hover(self._cursor_dir())
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._set_hover(None)
        e.accept()

    def dropEvent(self, e):
        it = self._cursor_dir()
        self._set_hover(None)
        e.acceptProposedAction()
        if it is None:
            return
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if it.data(PATH_ROLE) in paths:
            return
        self.dropped.emit(paths, it.data(PATH_ROLE))


# ------------------------------------------------------------- Ventana principal
_QUIET_SEEN = set()


def note_quiet():
    """Fallos que el programa tolera y sigue (antes no dejaban rastro): se anotan una vez por sitio en
    «errores_menores.txt», junto a errores.txt, para poder revisarlos si algo raro pasa."""
    try:
        import traceback
        tb = sys.exc_info()[2]
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        site = (tb.tb_frame.f_code.co_filename, tb.tb_lineno) if tb is not None else None
        if site in _QUIET_SEEN or len(_QUIET_SEEN) > 150:
            return
        _QUIET_SEEN.add(site)
        path = os.path.join(os.path.dirname(error_log_path()), "errores_menores.txt")
        if os.path.exists(path) and os.path.getsize(path) > 300000:
            os.remove(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + f"  v{APP_VERSION}\n" + traceback.format_exc() + "\n")
    except Exception:
        pass


class BatchWorker(QThread):
    """Hace un trabajo por cada elemento (guardar, mover…) fuera del hilo de la ventana, para que no se congele."""
    step = pyqtSignal(int)

    def __init__(self, items, fn):
        super().__init__()
        self.items, self.fn, self.results = list(items), fn, []

    def run(self):
        for i, it in enumerate(self.items):
            try:
                self.results.append((it, self.fn(it), None))
            except Exception as e:
                self.results.append((it, None, e))
            self.step.emit(i + 1)


HOTKEYS = (("hk_next", "PgDown", "Siguiente canción"), ("hk_prev", "PgUp", "Canción anterior"),
           ("hk_pause", "Pause", "Reproducir / pausa"))


class MusicKeys(QObject):
    """Atajos de música que funcionan en todas las ventanas del programa (editor, reproductor y ventanita):
    siguiente, anterior y pausa. Se configuran en Ajustes → Atajos de música. No actúan mientras se escribe."""

    VK = {Qt.Key.Key_PageUp: 0x21, Qt.Key.Key_PageDown: 0x22, Qt.Key.Key_End: 0x23, Qt.Key.Key_Home: 0x24,
          Qt.Key.Key_Left: 0x25, Qt.Key.Key_Up: 0x26, Qt.Key.Key_Right: 0x27, Qt.Key.Key_Down: 0x28,
          Qt.Key.Key_Insert: 0x2D, Qt.Key.Key_Delete: 0x2E, Qt.Key.Key_Space: 0x20, Qt.Key.Key_Pause: 0x13,
          Qt.Key.Key_MediaNext: 0xB0, Qt.Key.Key_MediaPrevious: 0xB1, Qt.Key.Key_MediaStop: 0xB2,
          Qt.Key.Key_MediaPlay: 0xB3, Qt.Key.Key_MediaTogglePlayPause: 0xB3}
    IDS = {"hk_next": 0xB101, "hk_prev": 0xB102, "hk_pause": 0xB103}

    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.registered = {}     # atajos activos en todo Windows: {acción: (modificadores, tecla)}
        self.failed = []         # los que Windows no dejó registrar (ya los usa otro programa)
        self.native = None
        self.load()

    def load(self):
        self.map = {}
        for key, default, _lab in HOTKEYS:
            seq = str(self.main.cfg.value(key, default) or "").strip()
            if seq:
                self.map[QKeySequence(seq).toString(QKeySequence.SequenceFormat.PortableText)] = key
        self.refresh_global()

    # ---- atajos en todo Windows (funcionan aunque estés en otro programa o jugando)
    def to_native(self, seq):
        ks = QKeySequence(seq)
        if ks.isEmpty():
            return None
        kc = ks[0]
        key, mods = kc.key(), kc.keyboardModifiers()
        kv = key.value if hasattr(key, "value") else int(key)
        vk = self.VK.get(key)
        if vk is None and Qt.Key.Key_F1.value <= kv <= Qt.Key.Key_F24.value:
            vk = 0x70 + kv - Qt.Key.Key_F1.value
        if vk is None and (0x30 <= kv <= 0x39 or 0x41 <= kv <= 0x5A):
            vk = kv
        if vk is None:
            return None
        m = 0x4000   # sin repetición al dejar pulsada
        if mods & Qt.KeyboardModifier.AltModifier:
            m |= 1
        if mods & Qt.KeyboardModifier.ControlModifier:
            m |= 2
        if mods & Qt.KeyboardModifier.ShiftModifier:
            m |= 4
        if mods & Qt.KeyboardModifier.MetaModifier:
            m |= 8
        return m, vk

    def want_global(self):
        """Solo mientras hay una canción puesta (sonando o en pausa): sin música, las teclas quedan libres."""
        if sys.platform != "win32" or not int(self.main.cfg.value("hk_global", 1) or 0):
            return {}
        pl = getattr(self.main, "player", None)
        if pl is None or pl.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
            return {}
        out = {}
        for seq, act in self.map.items():
            nat = self.to_native(seq)
            if nat:
                out[act] = nat
        return out

    def refresh_global(self):
        if sys.platform != "win32":
            return
        want = self.want_global()
        self.watch = want
        self.start_poll(bool(want))
        if want == self.registered:
            return
        try:
            import ctypes
            u32 = ctypes.windll.user32
            hwnd = int(self.main.winId())
            for act in self.registered:
                u32.UnregisterHotKey(hwnd, self.IDS[act])
            self.registered, self.failed = {}, []
            if want and self.native is None:
                self.native = HotkeyFilter(self)
                QApplication.instance().installNativeEventFilter(self.native)
            for act, (m, vk) in want.items():
                if u32.RegisterHotKey(hwnd, self.IDS[act], m, vk):
                    self.registered[act] = (m, vk)
                else:
                    self.failed.append(act)
        except Exception:
            note_quiet()

    # ---- segunda vía: mirar el teclado directamente. Algunos juegos a pantalla completa (League of Legends y
    # otros) le piden a Windows que no avise de los atajos de los demás programas; ahí el registro normal no
    # llega, pero el estado de la tecla sí se puede leer. Si las dos vías ven la misma pulsación, cuenta una vez.
    def start_poll(self, on):
        if getattr(self, "poll", None) is None:
            self.poll = QTimer(self)
            self.poll.setInterval(35)
            self.poll.timeout.connect(self.poll_keys)
            self.down, self.last_fire = {}, {}
        if on and not self.poll.isActive():
            self.down = {}
            self.poll.start()
        elif not on and self.poll.isActive():
            self.poll.stop()

    def poll_keys(self):
        try:
            import ctypes
            gk = ctypes.windll.user32.GetAsyncKeyState
            held = lambda vk: bool(gk(vk) & 0x8000)
            mods_now = (1 if held(0x12) else 0) | (2 if held(0x11) else 0) | (4 if held(0x10) else 0) | \
                       (8 if (held(0x5B) or held(0x5C)) else 0)
            for act, (m, vk) in getattr(self, "watch", {}).items():
                is_down = held(vk) and (m & 0xF) == mods_now
                was = self.down.get(act, False)
                self.down[act] = is_down
                if is_down and not was:
                    self.fire(act)
        except Exception:
            note_quiet()

    def fire(self, act):
        """Una pulsación = una acción, venga por el registro de Windows, por la lectura directa o por las dos."""
        now = time.monotonic()
        if now - self.last_fire.get(act, 0) < 0.30:
            return
        self.last_fire[act] = now
        self.run_action(act)

    def release_global(self):
        if getattr(self, "poll", None) is not None:
            self.poll.stop()
        try:
            import ctypes
            hwnd = int(self.main.winId())
            for act in self.registered:
                ctypes.windll.user32.UnregisterHotKey(hwnd, self.IDS[act])
        except Exception:
            note_quiet()
        self.registered = {}

    def run_action(self, act):
        if self.main.player is None:
            return
        if act == "hk_next":
            self.main.step_play(1)
        elif act == "hk_prev":
            self.main.step_play(-1)
        else:
            self.main.toggle_play()

    def eventFilter(self, obj, ev):
        if ev.type() != QEvent.Type.KeyPress or not self.map or not isinstance(obj, QWidget):
            return False
        k = ev.key()
        if k in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_unknown, 0):
            return False
        fw = QApplication.focusWidget()
        if isinstance(fw, (QLineEdit, QTextEdit, QPlainTextEdit, QKeySequenceEdit, QAbstractSpinBox)) or \
                (isinstance(fw, QComboBox) and fw.isEditable()):
            return False   # se está escribiendo: la tecla es para el texto
        try:
            seq = QKeySequence(ev.keyCombination()).toString(QKeySequence.SequenceFormat.PortableText)
        except Exception:
            return False
        act = self.map.get(seq)
        if act is None or self.main.player is None:
            return False
        if not ev.isAutoRepeat():
            if getattr(self, "poll", None) is not None and self.poll.isActive():
                self.fire(act)   # también la ve la lectura directa: que cuente una sola vez
            else:
                self.run_action(act)
        return True


class HotkeyFilter(QAbstractNativeEventFilter):
    """Recibe de Windows el aviso de que se pulsó un atajo de música registrado en todo el sistema."""

    def __init__(self, keys):
        super().__init__()
        self.keys = keys

    def nativeEventFilter(self, etype, message):
        try:
            if bytes(etype) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0312:   # WM_HOTKEY
                    for act, hid in MusicKeys.IDS.items():
                        if msg.wParam == hid:
                            QTimer.singleShot(0, lambda a=act: self.keys.fire(a))
                            return True, 0
        except Exception:
            note_quiet()
        return False, 0


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Music Manager {APP_VERSION}")
        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1500, scr.width() - 30), min(840, scr.height() - 30))   # nunca más grande que la pantalla
        self.setMinimumSize(min(1000, scr.width() - 30), min(620, scr.height() - 30))
        self.cfg = QSettings("MusicManager", "MusicManager")
        self.pending, self.edited, self.lyrics_edited, self._loading = {}, set(), False, False
        self.cur_paths, self.current_dir = [], ""
        self.gen, self.thumb_queue = 0, []
        self.meta, self.tags_cache = {}, {}
        # miniaturas en segundo plano + caché en disco (se limpia cada hora)
        self.thumbs = thumbs.ThumbWorker(THUMB_GEN, inspect_file, read_tags, find_folder_image, tech_compute)
        self.thumbs.ready.connect(self.on_thumb)
        self.thumbs.start()
        self.thumb_clean = QTimer(self)
        self.thumb_clean.setInterval(3600 * 1000)
        self.thumb_clean.timeout.connect(self.clean_thumbs)
        self.thumb_clean.start()
        QTimer.singleShot(15000, self.clean_thumbs)
        self.suggestions, self.chosen, self.ai_rows = {}, set(), []
        self.protected, self.worker, self.icons_mode = set(), None, True
        self.icon_px = max(40, min(160, int(self.cfg.value("icon_px", THUMB) or THUMB)))
        self.list_px = max(20, min(80, int(self.cfg.value("list_px", 44) or 44)))
        self.row_index = {}
        self.playing_path, self.lyr_worker, self.player = None, None, None
        self.playlist, self.pl_active, self.pl_lists, self.pl_name = [], False, {}, "Cola actual"
        self.pl_load()
        self.lyr_ok = self.lyr_total = 0
        self.chats = {}
        self.default_icon = note_icon()
        self.folder_icon = QFileIconProvider().icon(QFileIconProvider.IconType.Folder)
        self.clip = None
        self.back_stack, self.fwd_stack, self._nav_busy = [], [], False
        self.field_widgets = {}
        self.cover_max = parse_side(str(self.cfg.value("cover_size", "1200")))
        self.cover_clip, self.cover_clip_img = None, None
        self.theme = str(self.cfg.value("theme", "dark"))
        self.accent = str(self.cfg.value("accent", "") or "")
        apply_theme(QApplication.instance(), self.theme, self.accent or None)
        self.logo_pm = load_logo()
        self.setWindowIcon(QIcon(self.logo_pm))
        QApplication.instance().setWindowIcon(QIcon(self.logo_pm))
        self.build_ui()
        self.build_trees()
        g = self.cfg.value("geometry")
        if g:
            try:
                self.restoreGeometry(g)
            except Exception:
                note_quiet()
        self.fit_to_screen()
        self.apply_field_visibility()
        if not int(self.cfg.value("welcomed", 0) or 0) or int(self.cfg.value("guide_every", 0) or 0):
            self.cfg.setValue("welcomed", 1)  # primera vez (o si lo activas): muestra la guía rápida
            QTimer.singleShot(700, self.show_guide)
        last = str(self.cfg.value("last_dir", "") or "")
        if int(self.cfg.value("open_last", 1) or 0) and last and os.path.isdir(last):
            QTimer.singleShot(0, lambda: None if self.tree.reveal(last) else self.load_folder(last))

    # ---------------------------------------------------------------- UI
    def act(self, text, fn, tip="", checkable=False):
        a = QAction(text, self)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        if checkable:
            a.setCheckable(True)
            a.toggled.connect(fn)
        else:
            a.triggered.connect(lambda _=False: fn())
        return a

    def bind(self, widget, seq, fn):
        sc = QShortcut(QKeySequence(seq), widget)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(fn)

    def build_ui(self):
        # ---------- sin barra de herramientas: todo vive en los menús (ahorra espacio)
        self.act_view = self.act("☰ Lista", self.toggle_view, "Cambiar entre iconos y lista")
        self.act_tree2 = self.act("🗂 2.º árbol", self.toggle_tree2, "Mostrar un segundo árbol de carpetas", True)
        self.act_orient = self.act("⇄ Árboles lado a lado", self.toggle_orient, "Colocar los árboles en vertical u horizontal")
        self.act_lyr = self.act("📝 Letra", self.toggle_lyr, "Cambiar el panel derecho entre géneros y letra", True)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍 Buscar canción…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(210)
        self._search_timer = QTimer(self)   # se busca un instante después de dejar de escribir (no letra por letra)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(lambda: self.apply_filter(self.search.text()))
        self.search.textChanged.connect(lambda t: self._search_timer.start() if t else self.apply_filter(""))
        self.chk_sub = QCheckBox("Incluir subcarpetas")
        self.chk_sub.toggled.connect(lambda: self.load_folder(self.current_dir))
        self._corner = QWidget()
        cwl = QHBoxLayout(self._corner)
        cwl.setContentsMargins(0, 0, 6, 0)
        # selector de idioma con banderitas, siempre a la vista
        self.lang_btn = QToolButton()
        self.lang_btn.setObjectName("langbtn")
        self.lang_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.lang_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.lang_btn.setIconSize(QSize(22, 15))
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_btn.setToolTip("Cambiar idioma")
        lm = QMenu(self.lang_btn)
        for code, name in i18n.LANGS:
            a = lm.addAction(icons.flag_icon(code), name)
            a.triggered.connect(lambda _=False, c=code: self.set_language(c))
        self.lang_btn.setMenu(lm)
        cwl.addWidget(self.lang_btn)
        self.kofi_btn = self.make_kofi_button("Apoyar")   # ☕ apoyar el programa en Ko-fi
        cwl.addWidget(self.kofi_btn)
        cwl.addWidget(self.search)
        cwl.addWidget(self.chk_sub)

        self.pend_lbl = QLabel("")
        # los mensajes de la barra de estado también se traducen
        self._sb = self.statusBar()
        _show_msg = self._sb.showMessage
        self._sb.showMessage = lambda m, t=0: _show_msg(T(m), t)
        self.statusBar().addPermanentWidget(self.pend_lbl)
        self._pend_added = True

        # ---------- árboles de carpetas (el segundo se activa desde la barra)
        self.tree = FolderTree(self.folder_icon)
        self.tree2 = FolderTree(self.folder_icon)
        for t in (self.tree, self.tree2):
            t.customContextMenuRequested.connect(lambda pos, t=t: self.tree_menu(t, pos))
            t.currentItemChanged.connect(lambda cur, _, t=t: self.on_tree_current(t, cur))
            t.itemClicked.connect(lambda item, _c, t=t: self.on_tree_click(t, item))
            t.dropped.connect(self.defer_move)
            self.bind(t, "F2", lambda t=t: self.rename_tree_current(t))
            self.bind(t, "Ctrl+C", lambda t=t: self.clip_set("copy"))
            self.bind(t, "Ctrl+X", lambda t=t: self.clip_set("cut"))
            self.bind(t, "Ctrl+V", self.paste_here)
            self.bind(t, "Delete", lambda t=t: (setattr(self, "active_tree", t), self.delete_selected()))
        self.active_tree = self.tree
        self.tree2_box = self.pane("📁 Árbol 2", self.tree2)
        self.left_split = QSplitter(Qt.Orientation.Vertical)
        self.left_split.addWidget(self.pane("📁 Carpetas", self.tree))
        self.left_split.addWidget(self.tree2_box)
        self.tree2_box.hide()

        # ---------- lista de canciones y carpetas (estilo explorador)
        self.list = SongList()
        self.list.setItemDelegate(SongDelegate(self.list))
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setUniformItemSizes(True)
        self.list.setLayoutMode(QListView.LayoutMode.Batched)   # carpetas grandes: se coloca por partes, sin trabarse
        self.list.setBatchSize(200)
        self.sel_timer = QTimer(self)
        self.sel_timer.setSingleShot(True)
        self.sel_timer.setInterval(150)
        self._sel_retry = QTimer(self)
        self._sel_retry.setSingleShot(True)
        self._sel_retry.setInterval(1500)
        self._sel_retry.timeout.connect(lambda: self.cur_paths and self.selected_paths() == self.cur_paths
                                        and not (self.edited or self.lyrics_edited) and self.on_select())
        self.sel_timer.timeout.connect(self.on_select)
        self.list.itemSelectionChanged.connect(self.schedule_select)
        self.list.itemSelectionChanged.connect(lambda: getattr(self, "xfer_timer", None) and self.xfer_timer.start())
        self.list.selection_done.connect(self.on_select)
        self.list.dropped.connect(self.defer_move)
        self.sort_key = str(self.cfg.value("sort_key", "file") or "file")
        self.sort_desc = bool(int(self.cfg.value("sort_desc", 0) or 0))
        import details
        self.details = details.DetailsView(self, self.list, tech_info)
        self.view_mode = "icons"
        self.set_view(True)
        self.list.itemDoubleClicked.connect(self.on_list_double)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.list_menu)
        self.bind(self.list, "F2", self.rename_selected)
        self.bind(self.list, "Ctrl+C", lambda: self.clip_set("copy"))
        self.bind(self.list, "Ctrl+X", lambda: self.clip_set("cut"))
        self.bind(self.list, "Ctrl+V", self.paste_here)
        self.bind(self.list, "Delete", lambda: self.delete_paths(self.selected_all_paths()))
        self.bind(self.list, "Return", self.play_current)
        self.bind(self.list, "Space", self.toggle_play)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.save_all)
        self.player_bar = self.build_player_bar()

        # ---------- metadatos
        meta_box = QGroupBox()
        meta_box.setStyleSheet("QGroupBox { margin-top: 0px; padding-top: 10px; }")
        grid = QGridLayout(meta_box)
        self.inputs = {}
        for i, (k, n) in enumerate(FIELDS):
            r, c = divmod(i, 2)
            le = QLineEdit()
            le.textEdited.connect(lambda _, key=k: (self.edited.add(key), self.update_dirty()))
            self.inputs[k] = le
            le.setPlaceholderText("-")     # sin canción seleccionada: solo una línea, se rellena al elegir una
            le.setEnabled(False)
            lb = QLabel(n)
            self.field_widgets[k] = (lb, le)
            grid.addWidget(lb, r + 1, c * 2)
            grid.addWidget(le, r + 1, c * 2 + 1)
            if k in ('artist', 'albumartist', 'composer'):
                le.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                le.customContextMenuRequested.connect(lambda pos, le=le: self.person_menu(le, pos))
        # información técnica: etiquetas de solo lectura (chips) en la cabecera del cuadro
        self.tech = {}
        self.tech_bar = QWidget()
        tb_l = QHBoxLayout(self.tech_bar)
        tb_l.setContentsMargins(0, 0, 0, 4)
        tb_l.setSpacing(8)
        chips_w = QWidget()
        tbl = QGridLayout(chips_w)          # dos filas iguales: cada etiqueta tiene su sitio fijo
        tbl.setContentsMargins(0, 0, 0, 0)
        tbl.setHorizontalSpacing(6)
        tbl.setVerticalSpacing(6)
        order = (("codec", "enc", "tag", "bitrate", "freq"), ("ch", "dur", "mode", "size", "key"))
        for r_, row_keys in enumerate(order):
            for c_, k in enumerate(row_keys):
                chip = ChipLabel()
                chip.setObjectName("techchip")
                chip.setFixedHeight(28)
                self.tech[k] = chip
                tbl.addWidget(chip, r_, c_)
        for c_ in range(5):
            tbl.setColumnStretch(c_, 1)
        self.key_cache, self.key_worker = {}, None
        self.fill_tech([])
        tb_l.addWidget(chips_w, 1)
        self.save_btn = QPushButton("💾")
        self.save_btn.setObjectName("accent")
        self.save_btn.setToolTip("Guardar cambios (Ctrl+S)")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setFixedSize(44, 62)
        self.save_btn.setIconSize(QSize(20, 20))
        self.save_btn.clicked.connect(self.save_all)
        self.save_btn.setEnabled(False)
        tb_l.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.tech_bar.setFixedHeight(68)      # dos filas fijas de etiquetas: nada de lo de abajo sube ni baja
        grid.addWidget(self.tech_bar, 0, 0, 1, 4)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(10, 8, 10, 8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.dir_le = QLineEdit()
        self.dir_le.setReadOnly(True)
        self.dir_le.setPlaceholderText("-")
        dl = QLabel("Directorio")
        self.field_widgets["dir"] = (dl, self.dir_le)
        grid.addWidget(dl, 6, 0)
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        dir_row.addWidget(self.dir_le, 1)
        self.btn_ai_meta = QPushButton("✨ Rellenar con IA…")
        self.btn_ai_meta.setToolTip("Escribe el nombre y el artista y la IA busca y rellena los datos")
        self.btn_ai_meta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ai_meta.clicked.connect(self.open_meta_ai)
        dir_row.addWidget(self.btn_ai_meta)
        grid.addLayout(dir_row, 6, 1, 1, 3)
        grid.setRowStretch(7, 1)          # el espacio que sobra va abajo, no entre las etiquetas y los campos

        # ---------- letra (oculta; se muestra con el botón «📝 Letra»)
        self.lyr_box = QGroupBox("Letra")
        lv = QVBoxLayout(self.lyr_box)
        self.lyr_status = QLabel("")
        self.lyrics = QPlainTextEdit()
        self.lyrics.textChanged.connect(self.on_lyrics_edit)
        lv.addWidget(self.lyr_status)
        lv.addWidget(self.lyrics)
        self.btn_lyr = QPushButton("🔎 Buscar letra (sincronizada)")
        self.btn_lyr.setToolTip("Busca en LRCLIB; si no está, en NetEase y lyrics.ovh. Reintenta solo si falla la conexión.")
        self.btn_lyr.clicked.connect(self.run_lyrics)
        lv.addWidget(self.btn_lyr)
        lyr_row = QHBoxLayout()
        lyr_row.setSpacing(6)
        self.btn_lyr_web = QPushButton("🌐 Buscar en musica.com")
        self.btn_lyr_web.setToolTip("Abre la letra de esta canción en musica.com (copia la letra y pulsa «Pegar letra»)")
        self.btn_lyr_web.clicked.connect(lambda: self.lyrics_web("musica"))
        self.btn_lyr_paste = QPushButton("📋 Pegar letra")
        self.btn_lyr_paste.setToolTip("Pone como letra lo que copiaste (limpia espacios y líneas sobrantes)")
        self.btn_lyr_paste.clicked.connect(self.paste_lyrics)
        for b_ in (self.btn_lyr_web, self.btn_lyr_paste):
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
            lyr_row.addWidget(b_, 1)
        lv.addLayout(lyr_row)

        def make_fold_btn():
            fb = QToolButton()
            fb.setObjectName("foldbar")
            fb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            fb.setCursor(Qt.CursorShape.PointingHandCursor)
            fb.setIconSize(QSize(14, 14))
            fb.setFixedHeight(24)
            fb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            fb.clicked.connect(lambda: self.set_meta_open(not self.meta_open))
            return fb
        self.fold_btn = make_fold_btn()    # encima de los metadatos: «Ocultar metadatos»
        self.fold_btn2 = make_fold_btn()   # debajo de la lista cuando están ocultos: «Mostrar metadatos»
        bottom = QWidget()
        self.bottom_w = bottom
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(meta_box)

        self.list_pane = QWidget()
        lpv = QVBoxLayout(self.list_pane)
        lpv.setContentsMargins(0, 0, 0, 0)
        lpv.setSpacing(4)
        navbar = QHBoxLayout()
        navbar.setSpacing(2)
        self.btn_back, self.btn_fwd, self.btn_up = QPushButton(), QPushButton(), QPushButton()
        self.btn_refresh = QPushButton()
        for b, ic in ((self.btn_back, "arrow_l"), (self.btn_fwd, "arrow_r"), (self.btn_up, "arrow_u"),
                      (self.btn_refresh, "refresh")):
            b.setIcon(icons.vicon(ic))
        for b, tip, fn in ((self.btn_back, "Atrás (Alt+←)", self.nav_back), (self.btn_fwd, "Adelante (Alt+→)", self.nav_fwd),
                           (self.btn_up, "Subir a la carpeta superior (Alt+↑)", self.nav_up),
                           (self.btn_refresh, "Actualizar la carpeta (F5)", self.refresh_dir)):
            b.setObjectName("tbtn")
            b.setFixedWidth(36)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            navbar.addWidget(b)
        self.path_lbl = QLabel("")
        self.path_lbl.setObjectName("hint")
        self.path_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        navbar.addWidget(self.path_lbl, 1)
        navbar.addSpacing(8)
        self.btn_spec = None
        for src, text, tip in (("spec", "📊 Espectro", "Espectrograma y análisis de calidad de las canciones seleccionadas"),):
            # MusicBrainz y Discogs están ahora en Herramientas → Etiquetas y portadas
            b_ = QPushButton(text)
            b_.setObjectName("chipbtn")
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
            b_.setToolTip(tip)
            if src == "spec":
                self.btn_spec = b_
                b_.clicked.connect(self.open_spectrum)
            else:
                b_.clicked.connect(lambda _=False, s_=src: self.open_tag_source(s_))
            navbar.addWidget(b_)
        navbar.addSpacing(8)
        self.view_btns = {}
        for mode, ic, tip in (("icons", "grid", "Ver como iconos"), ("list", "menu", "Ver como lista"),
                              ("details", "table", "Ver como lista con detalles (columnas que se pueden ordenar)")):
            vb = QToolButton()
            vb.setObjectName("viewbtn")
            vb.setCheckable(True)
            vb.setIcon(icons.vicon(ic, ctx="check"))
            vb.setIconSize(QSize(18, 18))
            vb.setToolTip(tip)
            vb.setCursor(Qt.CursorShape.PointingHandCursor)
            vb.clicked.connect(lambda _=False, m_=mode: self.set_view_mode(m_))
            self.view_btns[mode] = vb
            navbar.addWidget(vb)
        navbar.addSpacing(6)
        lpv.addLayout(navbar)
        # aviso cuando hay una búsqueda activa (si no, parece que las canciones desaparecieron)
        self.filter_bar = QFrame()
        self.filter_bar.setObjectName("keyok")
        fb_l = QHBoxLayout(self.filter_bar)
        fb_l.setContentsMargins(10, 3, 6, 3)
        self.filter_lbl = QLabel("")
        fb_l.addWidget(self.filter_lbl, 1)
        fb_clear = QPushButton(T("Quitar búsqueda"))
        fb_clear.setObjectName("link")
        fb_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        fb_clear.clicked.connect(self.search.clear)
        fb_l.addWidget(fb_clear)
        self.filter_bar.hide()
        lpv.addWidget(self.filter_bar)
        lpv.addWidget(self.list, 1)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.nav_back)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.nav_fwd)
        QShortcut(QKeySequence("Alt+Up"), self, activated=self.nav_up)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh_dir)
        self.list.viewport().installEventFilter(self)

        # ---------- columna derecha: portada + IA
        cover_box = QGroupBox()
        cover_box.setStyleSheet("QGroupBox { margin-top: 0px; padding: 6px 4px 4px 4px; }")
        cv = QVBoxLayout(cover_box)
        self.cover_lbl = QLabel("Selecciona una canción")
        self.cover_lbl.setObjectName("cover")
        self.cover_lbl.setFixedSize(COVER, COVER)
        self.cover_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_lbl = QLabel("")
        self.info_lbl.setWordWrap(True)
        self.status_lbl = QLabel("")
        self.status_lbl.setWordWrap(True)
        self.cover_lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cover_lbl.customContextMenuRequested.connect(self.cover_menu)
        self.cover_lbl.setToolTip("Clic derecho: cambiar, quitar, copiar, pegar, guardar o redimensionar")
        ch = QHBoxLayout()
        ch.setSpacing(8)
        left = QVBoxLayout()
        left.setSpacing(4)
        for text, tip, fn in (("🖼", "Cambiar portada…", self.set_cover), ("✨", "Buscar portada automáticamente (alta calidad)", self.auto_cover), ("💾", "Guardar portada como imagen…", self.save_cover_as),
                              ("🗑", "Quitar portada", self.remove_cover), ("🔍", "Ver la portada en grande", self.view_cover)):
            b = QPushButton(text)
            b.setObjectName("iconbtn")
            b.setFixedSize(32, 32)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, f=fn: f())
            left.addWidget(b)
        left.addStretch(1)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 140))
        self.cover_lbl.setGraphicsEffect(shadow)
        self.info_lbl.setObjectName("chip")
        self.info_lbl.setWordWrap(False)
        self.info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_lbl.hide()
        # la etiqueta (JPEG · 1000×1000 px · 190 KB) va en su propia fila, centrada justo debajo de la portada
        # y con espacio para la sombra: nunca se monta encima de la imagen
        self.info_lbl.setFixedHeight(22)
        self.info_lbl.setMaximumWidth(COVER + 24)
        sp_i = self.info_lbl.sizePolicy()
        sp_i.setRetainSizeWhenHidden(True)      # su sitio queda reservado: la portada no se mueve ni se tapa
        self.info_lbl.setSizePolicy(sp_i)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self.cover_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addSpacing(14)
        col.addWidget(self.info_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        ch.addStretch(1)
        ch.addLayout(left)
        ch.addLayout(col)
        ch.addStretch(1)
        cv.setContentsMargins(6, 4, 6, 6)
        cv.setSpacing(3)
        cv.addLayout(ch)
        self.status_lbl.hide()
        cover_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        cover_box.setMinimumHeight(COVER + 14 + 22 + 22)   # no se puede encoger hasta tapar la portada

        ai_box = QGroupBox("Reconocer géneros con IA")
        av = QVBoxLayout(ai_box)
        self.ai_cfg = QWidget()
        ai = QFormLayout(self.ai_cfg)
        ai.setContentsMargins(0, 0, 0, 0)
        self.provider = QComboBox()
        self.provider.addItems(["Claude", "ChatGPT", "Gemini"])
        self.model_cb = QComboBox()
        self.model_cb.setEditable(True)
        self.provider.currentTextChanged.connect(self.on_provider)
        self.key_le = QLineEdit()
        self.key_le.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_le.setPlaceholderText("API key")
        ai.addRow("Proveedor", self.provider)
        ai.addRow("Modelo", self.model_cb)
        ai.addRow("API key", self.key_le)
        self.btn_ai = QPushButton("✨ Sugerir género (selección o todas)")
        self.btn_ai.setObjectName("accent")
        self.btn_ai.clicked.connect(self.run_ai)
        self.sug_label = QLabel("Pulsa «Sugerir género» para ver opciones.")
        self.sug_label.setWordWrap(True)
        self.sug_list = QListWidget()
        self.sug_list.setFixedHeight(130)
        self.sug_list.itemClicked.connect(self.pick_suggestion)
        # poner a mano un género a la canción o a todas las seleccionadas
        man = QHBoxLayout()
        self.genre_pick = QComboBox()
        self.genre_pick.setEditable(True)
        try:
            import genres as _g
            self.genre_pick.addItems(_g.COMMON)
        except Exception:
            note_quiet()
        self.genre_pick.setCurrentText("")
        self.genre_pick.lineEdit().setPlaceholderText("Otro género (escribe o elige)…")
        self.genre_pick.lineEdit().returnPressed.connect(self.put_manual_genre)
        self.btn_put_genre = QPushButton("✔ Poner")
        self.btn_put_genre.setToolTip("Pone este género a la canción o a todas las seleccionadas")
        self.btn_put_genre.clicked.connect(self.put_manual_genre)
        man.addWidget(self.genre_pick, 1)
        man.addWidget(self.btn_put_genre)
        self.btn_chat = QPushButton("💬 Hablar con la IA sobre este género")
        self.btn_chat.clicked.connect(self.open_chat)
        for w in (self.btn_ai, self.sug_label, self.sug_list):
            av.addWidget(w)
        av.addLayout(man)
        av.addWidget(self.btn_chat)
        self.provider.setCurrentText(self.cfg.value("provider", "Claude"))
        self.on_provider(self.provider.currentText())

        ai_scroll = QScrollArea()
        ai_scroll.setWidgetResizable(True)
        ai_scroll.setFrameShape(QFrame.Shape.NoFrame)
        ai_scroll.setMinimumHeight(180)
        ai_scroll.setWidget(ai_box)
        # parte baja de la columna derecha: pestañas Géneros / Letra
        rightlow = QWidget()
        rv = QVBoxLayout(rightlow)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(4)
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(6)
        self.btn_tab_gen, self.btn_tab_lyr = QPushButton("🎼 Géneros"), QPushButton("📝 Letra")
        for i, b in enumerate((self.btn_tab_gen, self.btn_tab_lyr)):
            b.setCheckable(True)
            b.setObjectName("tabbtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=i: self.show_right_tab(i))
            tabs_row.addWidget(b, 1)
        self.btn_tab_gen.setChecked(True)
        self.btn_tab_gen.setToolTip("Sugerir géneros y subgéneros con IA")
        self.btn_tab_lyr.setToolTip("Ver, editar o buscar la letra de la canción")
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(ai_scroll)     # 0: géneros (se desplaza)
        self.right_stack.addWidget(self.lyr_box)  # 1: letra
        rv.addLayout(tabs_row)
        rv.addWidget(self.right_stack, 1)
        rightlow.setMinimumWidth(330)

        # la portada queda arriba a la derecha, siempre de su tamaño (no se estira)
        coverw = QWidget()
        cvw = QVBoxLayout(coverw)
        cvw.setContentsMargins(4, 0, 0, 0)
        cvw.setSpacing(0)
        cvw.addWidget(cover_box)
        # un solo botón con menú para buscar la canción fuera: nunca se monta sobre la portada ni se amontona
        self.web_btn = QToolButton()
        self.web_btn.setObjectName("webbtn")
        self.web_btn.setText("🌐 Buscar la canción en…")
        self.web_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.web_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.web_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        wm = QMenu(self.web_btn)
        for kind, label, tip in (("youtube", "▶ YouTube", "Buscar esta canción en YouTube"),
                                 ("spotify", "🎵 Spotify", "Buscar esta canción en Spotify"),
                                 ("tidal", "🎧 Tidal", "Buscar esta canción en Tidal"),
                                 ("qobuz", "💿 Qobuz", "Buscar esta canción en Qobuz"),
                                 ("wiki", "📖 Wikipedia", "Buscar esta canción o artista en Wikipedia")):
            a = wm.addAction(label)
            a.setToolTip(tip)
            a.triggered.connect(lambda _=False, k=kind: self.web_song(k))
        self.web_btn.setMenu(wm)
        web_row = QHBoxLayout()
        web_row.setContentsMargins(0, 6, 0, 0)
        web_row.addStretch(1)
        web_row.addWidget(self.web_btn)
        web_row.addStretch(1)
        cvw.addLayout(web_row)
        cvw.addStretch(1)
        coverw.setMinimumWidth(330)
        coverw.setMinimumHeight(cover_box.minimumHeight() + 46)   # la fila de arriba no puede aplastar la portada
        self.cover_col = coverw

        top_split = QSplitter(Qt.Orientation.Horizontal)       # fila de arriba: lista | portada
        top_split.addWidget(self.list_pane)
        top_split.addWidget(coverw)
        bottom_split = QSplitter(Qt.Orientation.Horizontal)    # fila de abajo: metadatos | géneros/letra
        meta_col = QWidget()
        mc_l = QVBoxLayout(meta_col)
        mc_l.setContentsMargins(0, 0, 0, 0)
        mc_l.setSpacing(0)
        mc_l.addWidget(bottom, 1)
        # el botón de ocultar va dentro de la fila de etiquetas técnicas: no quita altura a los campos
        self.fold_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.fold_btn.setObjectName("foldmini")
        self.fold_btn.setFixedSize(26, 62)
        self.fold_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.tech_bar.layout().insertWidget(0, self.fold_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        bottom_split.addWidget(meta_col)
        bottom_split.addWidget(rightlow)
        self.rightlow, self.cover_w = rightlow, coverw
        for sp in (top_split, bottom_split):
            sp.setStretchFactor(0, 1)
            sp.setStretchFactor(1, 0)
            sp.setCollapsible(0, False)
            sp.setCollapsible(1, False)
            sp.setSizes([900, 330])
        self._cols_sync = False

        def sync_cols(src, dst):
            if not self._cols_sync:
                self._cols_sync = True
                dst.setSizes(src.sizes())
                self._cols_sync = False
        top_split.splitterMoved.connect(lambda *a: (sync_cols(top_split, bottom_split), self.layout_overlay()))
        bottom_split.splitterMoved.connect(lambda *a: (sync_cols(bottom_split, top_split), self.layout_overlay()))
        self.top_split, self.bottom_split = top_split, bottom_split
        self.bottom_stack = QStackedWidget()                   # página 0: metadatos…; página 1: espectrograma a todo el ancho
        self.bottom_stack.addWidget(bottom_split)
        self.meta_open = True
        middle = QSplitter(Qt.Orientation.Vertical)
        middle.addWidget(top_split)
        middle.addWidget(self.bottom_stack)
        middle.setCollapsible(0, False)
        middle.setCollapsible(1, False)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 1)
        middle.setSizes([430, 300])

        main = QSplitter()
        left_box = QWidget()
        lb_l = QVBoxLayout(left_box)
        lb_l.setContentsMargins(0, 0, 0, 0)
        lb_l.setSpacing(4)
        lb_l.addWidget(self.left_split, 1)
        lb_l.addWidget(self.build_xfer_bar())
        main.addWidget(left_box)
        self.left_box = left_box
        # metadatos plegados: la lista llega hasta abajo; la portada y Géneros/Letra siguen a la derecha
        self.fold_split = QSplitter(Qt.Orientation.Horizontal)
        self.fold_left = QWidget()
        fl_l = QVBoxLayout(self.fold_left)
        fl_l.setContentsMargins(0, 0, 0, 0)
        fl_l.setSpacing(0)
        fl_l.addWidget(self.fold_btn2)
        self.fold_right = QWidget()
        fr_l = QVBoxLayout(self.fold_right)
        fr_l.setContentsMargins(0, 0, 0, 0)
        fr_l.setSpacing(0)
        self.fold_split.addWidget(self.fold_left)
        self.fold_split.addWidget(self.fold_right)
        self.fold_split.setStretchFactor(0, 1)
        self.fold_split.setStretchFactor(1, 0)
        self.fold_split.setCollapsible(0, False)
        self.fold_split.setCollapsible(1, False)
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(middle)
        self.center_stack.addWidget(self.fold_split)
        main.addWidget(self.center_stack)
        main.setStretchFactor(1, 1)
        self.left_split.setMinimumWidth(210)
        for i in range(2):
            main.setCollapsible(i, False)
        main.setSizes([280, 1230])
        self.main_split, self.mid_split = main, middle
        for sp in (main, middle, top_split, bottom_split, self.left_split, self.fold_split):
            self.style_splitter(sp)
        self.set_rows_locked(True)
        self.meta_fold = bool(int(self.cfg.value("meta_fold", 1) or 0))
        self.set_meta_open(True)   # textos/iconos de las barritas
        QTimer.singleShot(0, lambda: self.set_meta_open(bool(int(self.cfg.value("meta_open", 1) or 0))))
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(main, 1)   # sin barra general: el programa entero no se desplaza
        self._central_lay = cl
        import drawer
        self.tree_drawer = drawer.TreeDrawer(self, central, self.left_box, main)
        QTimer.singleShot(0, lambda: self.set_trees_mode(str(self.cfg.value("trees_mode", "normal"))))
        self.setup_watch()
        self.setCentralWidget(central)
        self.build_pl_panel(central)
        self.shuffle = bool(int(self.cfg.value("shuffle", 0) or 0))
        self.repeat = str(self.cfg.value("repeat", "off") or "off")
        self._shuffle_hist = []
        self.mobile = None
        self.mini = None   # modo reproductor (ventanita aparte; se crea la primera vez)
        self.mini_detached = False   # reproductor separado con el editor también abierto
        self.fs_undo = []  # últimos movimientos / renombrados, para poder deshacerlos
        self.music_keys = MusicKeys(self)
        QApplication.instance().installEventFilter(self.music_keys)
        self.media = None
        if self.player is not None:   # Windows (y Wallpaper Engine, pantalla de bloqueo…) sabe qué canción suena
            try:
                import smtc
                self.media = smtc.MediaSession(self)
                self.media.pressed.connect(self.on_media_button)
                self.player.playbackStateChanged.connect(self.media_state)
            except Exception:
                note_quiet()
        if self.player is not None:   # los atajos de todo Windows solo están activos mientras hay música puesta
            self.player.playbackStateChanged.connect(lambda _st: self.music_keys.refresh_global())
        if self.player is not None:
            import mobile
            self.mobile = mobile.MobilePlayer(self, central, inspect_file)
            try:   # el panel usa el mismo diseño que el modo reproductor
                import miniplayer
                self.mobile.attach_inner(miniplayer.MiniPlayer(self, inspect_file, tech_info, read_tags, AUDIO_EXT,
                                                               find_folder_image, parent=self.mobile))
            except Exception:
                import traceback
                traceback.print_exc()
            QTimer.singleShot(300, lambda: self.set_player_style("classic", first=True))
        self.statusBar().addPermanentWidget(self.player_bar)   # reproductor en la línea de estado, a la derecha
        self.statusBar().setSizeGripEnabled(False)
        self.wide_viz = WideViz(self.statusBar(), self.viz)
        self.statusBar().showMessage("Arrastra carpetas o canciones sobre otra carpeta. Doble clic en una canción para reproducirla.")
        self.build_menus()
        if int(self.cfg.value("tree2", 0) or 0):
            self.act_tree2.setChecked(True)
        if int(self.cfg.value("show_lyr", 0) or 0):
            self.act_lyr.setChecked(True)
        if int(self.cfg.value("trees_h", 0) or 0):
            self.toggle_orient()
        try:
            for key, sp in (("split_main2", self.main_split), ("split_rows2", self.mid_split), ("split_cols2", self.top_split)):
                st = self.cfg.value(key)
                if st:
                    sp.restoreState(st)
            self.bottom_split.setSizes(self.top_split.sizes())
            sz = self.main_split.sizes()  # si una sesión anterior dejó el árbol aplastado, lo restaura
            if sz and sz[0] < 210:
                self.main_split.setSizes([290, max(600, sz[1] - 290 + sz[0])])
        except Exception:
            note_quiet()

    # ------------------------------------------------------------ Árboles
    def pane(self, title, tree):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        lbl = QLabel(title)
        f = lbl.font()
        f.setBold(True)
        lbl.setFont(f)
        v.addWidget(lbl)
        v.addWidget(tree)
        if not hasattr(self, "pane_titles"):
            self.pane_titles = {}
        self.pane_titles[tree] = lbl
        return w

    def pinned(self):
        try:
            return json.loads(self.cfg.value("pinned", "[]"))
        except Exception:
            return []

    def on_media_button(self, name):
        """Botones del panel multimedia de Windows o teclas multimedia del teclado."""
        if self.player is None:
            return
        st = self.player.playbackState()
        if name == "next":
            self.step_play(1)
        elif name == "prev":
            self.step_play(-1)
        elif name == "stop":
            self.player.stop()
        elif (name == "play") != (st == QMediaPlayer.PlaybackState.PlayingState):
            self.toggle_play()

    def media_state(self, st=None):
        if self.media is None or self.player is None:
            return
        st = self.player.playbackState()
        self.media.set_state("playing" if st == QMediaPlayer.PlaybackState.PlayingState else
                             "paused" if st == QMediaPlayer.PlaybackState.PausedState else "stopped")

    def media_track(self, path):
        if self.media is None or not path:
            return
        try:
            cover = self.cover_data_of(path)
        except Exception:
            cover = None
        self.media.set_track(self.val(path, "title") or os.path.splitext(os.path.basename(path))[0],
                             self.val(path, "artist"), self.val(path, "album"), bytes(cover) if cover else b"")

    def tree_roots(self):
        """Las carpetas principales del árbol (Música y las que agregaste), tal como se ven a la izquierda."""
        ents = [(n, p) for n, p in main_folders()]
        ents += [("📌 " + (os.path.basename(p) or p), p) for p in self.pinned() if os.path.isdir(p)]
        return ents

    def build_trees(self):
        ents = [(n, p, "main") for n, p in main_folders()]
        ents += [("📌 " + (os.path.basename(p) or p), p, "pinned")
                 for p in self.pinned() if os.path.isdir(p)]
        self.protected = {os.path.normcase(os.path.normpath(p)) for _, p, _ in ents}
        self.tree2.build(ents)
        self.tree.build(ents)
        self.active_tree = self.tree
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def refresh_trees(self):
        self.tree.refresh()
        self.tree2.refresh()
        self.update_watch()

    @staticmethod
    def dir_signature(path):
        """Qué hay en una carpeta (subcarpetas y canciones): para saber si de verdad cambió algo."""
        try:
            with os.scandir(path) as it:
                return frozenset((e.name, e.is_dir(follow_symlinks=False)) for e in it
                                 if e.is_dir(follow_symlinks=False) or os.path.splitext(e.name)[1].lower() in AUDIO_EXT)
        except OSError:
            return None

    def setup_watch(self):
        """Vigila las carpetas abiertas en los árboles y la carpeta actual: si se crea, borra o renombra algo
        (aquí o desde el Explorador de Windows), los árboles y la lista se actualizan solos."""
        from PyQt6.QtCore import QFileSystemWatcher
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.on_dir_changed)
        self._watch_changed = set()
        self._watch_timer = QTimer(self)
        self._watch_timer.setSingleShot(True)
        self._watch_timer.setInterval(450)
        self._watch_timer.timeout.connect(self.apply_dir_changes)
        self._tree_sigs = {}
        for t in (self.tree, self.tree2):
            t.itemExpanded.connect(lambda *_: QTimer.singleShot(0, self.update_watch))
            t.itemCollapsed.connect(lambda *_: QTimer.singleShot(0, self.update_watch))
        QTimer.singleShot(500, self.update_watch)

    def update_watch(self):
        w = getattr(self, "watcher", None)
        if w is None or time.monotonic() < getattr(self, "_watch_paused_until", 0):
            return
        want = set()
        for t in (self.tree, self.tree2):
            for i in range(t.topLevelItemCount()):
                p = t.topLevelItem(i).data(0, PATH_ROLE)
                if p:
                    want.add(p)
            for it in t.all_items():
                p = it.data(0, PATH_ROLE)
                if p and it.isExpanded():
                    want.add(p)
                    for j in range(min(it.childCount(), 200)):   # las carpetas visibles también (para su flechita)
                        cp = it.child(j).data(0, PATH_ROLE)
                        if cp:
                            want.add(cp)
        want = set(sorted(want, key=len)[:400])
        if self.current_dir:
            want.add(self.current_dir)
        want = {p for p in want if os.path.isdir(p)}
        have = set(w.directories())
        if have - want:
            w.removePaths(list(have - want))
        if want - have:
            w.addPaths(list(want - have))
        for p in want:
            if p not in self._tree_sigs:
                self._tree_sigs[p] = self.dir_signature(p)

    def unwatch(self, paths):
        w = getattr(self, "watcher", None)
        if w is None or not paths:
            return
        roots = [os.path.normcase(os.path.normpath(p)) for p in paths if p]
        drop = []
        for d in w.directories():
            nd = os.path.normcase(os.path.normpath(d))
            if any(nd == r or nd.startswith(r + os.sep) for r in roots):
                drop.append(d)
                self._tree_sigs.pop(d, None)
        if drop:
            w.removePaths(drop)
        self._watch_paused_until = time.monotonic() + 3   # mientras se trabaja con los archivos no se vigila de nuevo
        QTimer.singleShot(3200, self.update_watch)

    def on_dir_changed(self, path):
        self._watch_changed.add(path)
        self._watch_timer.start()

    def apply_dir_changes(self):
        if DRAG_ACTIVE[0] or QApplication.mouseButtons() != Qt.MouseButton.NoButton or QApplication.activeModalWidget():
            self._watch_timer.start()   # estás arrastrando o en una ventana: se actualiza en cuanto termines
            return
        changed, self._watch_changed = self._watch_changed, set()
        trees_dirty = False
        for p in changed:
            sig = self.dir_signature(p)
            if sig != self._tree_sigs.get(p):   # solo si cambiaron carpetas o canciones (no al guardar etiquetas)
                old = self._tree_sigs.get(p) or frozenset()
                self._tree_sigs[p] = sig
                if {n for n, d in (sig or ()) if d} != {n for n, d in old if d}:
                    trees_dirty = True
        if trees_dirty:
            self.refresh_trees()
        cd = self.current_dir
        if cd and any(os.path.normcase(os.path.normpath(p)) == os.path.normcase(os.path.normpath(cd)) for p in changed):
            snap = getattr(self, "dir_snapshot", None)
            if snap and snap[0] == cd and self.dir_signature(cd) != snap[1] and not self.list.selecting \
                    and QApplication.mouseButtons() == Qt.MouseButton.NoButton and not DRAG_ACTIVE[0]:
                self.load_folder(cd, select=self.selected_paths() or None)
        self.update_watch()

    # ---------------------------------------------- pasar entre árboles sin arrastrar (como Kodi)
    def build_xfer_bar(self):
        """Con dos árboles: el de «De» es el origen y el de «A» el destino. Abajo: qué se envía, «Enviar» e «Invertir»."""
        self.xfer_src = self.tree   # árbol de origen («De»); el otro es el destino («A»)
        bar = QFrame()
        bar.setObjectName("xfer")
        v = QVBoxLayout(bar)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(5)
        self.xfer_lbl = QLabel("")
        self.xfer_lbl.setWordWrap(True)
        self.xfer_lbl.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.xfer_lbl)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.xfer_swap = QPushButton("⇄ Invertir")
        self.xfer_swap.setToolTip("Cambia el sentido: el árbol de «De» pasa a ser «A» y al revés")
        self.xfer_swap.clicked.connect(self.xfer_invert)
        self.xfer_copy = QPushButton("📋 Copiar")
        self.xfer_copy.setToolTip("Copia lo elegido en «De» a la carpeta elegida en «A» (F7)")
        self.xfer_copy.clicked.connect(lambda: self.xfer(False))
        self.xfer_move = QPushButton("➡ Enviar")
        self.xfer_move.setObjectName("accent")
        self.xfer_move.setToolTip("Mueve lo elegido en «De» a la carpeta elegida en «A» (F6)")
        self.xfer_move.clicked.connect(lambda: self.xfer(True))
        for b_ in (self.xfer_swap, self.xfer_copy, self.xfer_move):
            b_.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.xfer_swap)
        row.addWidget(self.xfer_copy)
        row.addWidget(self.xfer_move, 1)
        v.addLayout(row)
        bar.hide()
        self.xfer_bar = bar
        QShortcut(QKeySequence("F6"), self, activated=lambda: self.xfer(True))
        QShortcut(QKeySequence("F7"), self, activated=lambda: self.xfer(False))
        self.xfer_timer = QTimer(self)
        self.xfer_timer.setSingleShot(True)
        self.xfer_timer.setInterval(120)
        self.xfer_timer.timeout.connect(self.update_xfer)
        return bar

    def xfer_dst_tree(self):
        return self.tree2 if self.xfer_src is self.tree else self.tree

    def update_tree_titles(self):
        titles = getattr(self, "pane_titles", {})
        two = self.tree2_box.isVisible()
        for t, lbl in titles.items():
            if not two:
                txt = "📁 Carpetas" if t is self.tree else "📁 Árbol 2"
            elif t is self.xfer_src:
                txt = "📤 De:  elige lo que vas a enviar"
            else:
                txt = "📥 A:  elige a dónde se envía"
            lbl.setText(txt)
            lbl.setStyleSheet("" if not two else ("color: palette(highlight);" if t is self.xfer_src else ""))

    def xfer_invert(self):
        self.xfer_src = self.xfer_dst_tree()
        self.update_tree_titles()
        self.update_xfer()

    def xfer_plan(self):
        """(qué se envía, a dónde, descripción). De = canciones elegidas en la lista (si la lista muestra la carpeta
        de «De») o la carpeta elegida en el árbol «De». A = carpeta elegida en el árbol «A»."""
        if not self.tree2_box.isVisible():
            return [], None, ""
        src_tree, dst_tree = self.xfer_src, self.xfer_dst_tree()
        dc = dst_tree.currentItem()
        dst = dc.data(0, PATH_ROLE) if dc is not None else None
        sc = src_tree.currentItem()
        src_dir = sc.data(0, PATH_ROLE) if sc is not None else None
        files = [p for p in self.selected_paths() if p and os.path.isfile(p)]
        if files and src_dir and self.current_dir and \
                os.path.normcase(os.path.normpath(self.current_dir)) == os.path.normcase(os.path.normpath(src_dir)):
            what = T(f"{len(files)} canción(es)") if len(files) > 1 else f"«{os.path.basename(files[0])}»"
            return files, dst, what
        dirs = [d for d in src_tree.selected_dirs() if d]
        if dirs:
            what = f"📁 «{os.path.basename(dirs[0].rstrip(os.sep)) or dirs[0]}»" if len(dirs) == 1 else T(f"{len(dirs)} carpetas")
            return dirs, dst, what
        return [], dst, ""

    def update_xfer(self):
        if not getattr(self, "xfer_bar", None):
            return
        on = self.tree2_box.isVisible()
        self.xfer_bar.setVisible(on)
        self.update_tree_titles()
        if not on:
            return
        srcs, dst, what = self.xfer_plan()
        dname = (os.path.basename(dst.rstrip(os.sep)) or dst) if dst else ""
        de = what or f"<i>{html.escape(T('elige en «De»'))}</i>"
        a = f"<b>{html.escape(dname)}</b>" if dname else f"<i>{html.escape(T('elige en «A»'))}</i>"
        self.xfer_lbl.setText(f"<b>{html.escape(T('De'))}:</b> {de}<br><b>{html.escape(T('A'))}:</b> {a}")
        ok = bool(srcs and dst)
        self.xfer_copy.setEnabled(ok)
        self.xfer_move.setEnabled(ok)

    def xfer(self, move):
        srcs, dst, what = self.xfer_plan()
        if not srcs or not dst:
            self.update_xfer()
            return
        dn = os.path.normcase(os.path.normpath(dst))
        srcs = [p for p in srcs if os.path.normcase(os.path.dirname(os.path.normpath(p))) != dn]
        if not srcs:
            self.statusBar().showMessage(T("Ya está en esa carpeta."))
            return
        (self.move_items if move else self.copy_items)(srcs, dst)
        self.update_xfer()

    def toggle_tree2(self, on):
        self.tree2_box.setVisible(on)
        if getattr(self, "tree_drawer", None):
            QTimer.singleShot(0, self.tree_drawer.place)
        QTimer.singleShot(0, self.update_xfer)
        self.cfg.setValue("tree2", 1 if on else 0)
        if on:
            self.left_split.setSizes([400, 400])
        elif self.active_tree is self.tree2:
            self.active_tree = self.tree
        self.statusBar().showMessage(
            "Segundo árbol activado: arrastra carpetas de un árbol al otro." if on else "Segundo árbol oculto.")

    def on_tree_current(self, tree, cur):
        """Se abre la carpeta un momento después (y solo al soltar el ratón): al sombrear varias carpetas o bajar
        con las flechas no se carga cada carpeta por la que pasas."""
        if getattr(self, "xfer_timer", None):
            self.xfer_timer.start()
        if cur is None:
            return
        self.active_tree = tree
        self._tree_pending = cur.data(0, PATH_ROLE)
        t = getattr(self, "_tree_timer", None)
        if t is None:
            t = self._tree_timer = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(180)
            t.timeout.connect(self.tree_load_pending)
        t.start()

    def tree_load_pending(self):
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self._tree_timer.start()   # todavía estás sombreando o arrastrando
            return
        p = getattr(self, "_tree_pending", None)
        if p and p != self.current_dir:
            self.load_folder(p)

    def on_tree_click(self, tree, item):
        self.active_tree = tree
        if getattr(self, "xfer_timer", None):
            self.xfer_timer.start()
        p = item.data(0, PATH_ROLE)
        if p and p != self.current_dir:
            self.load_folder(p)

    def is_protected(self, p):
        return os.path.normcase(os.path.normpath(p)) in self.protected

    def pin_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Agregar carpeta al árbol")
        if p:
            lst = self.pinned()
            if os.path.normpath(p) not in lst:
                lst.append(os.path.normpath(p))
                self.cfg.setValue("pinned", json.dumps(lst))
                self.build_trees()

    def unpin(self, p):
        lst = [x for x in self.pinned() if os.path.normpath(x) != os.path.normpath(p)]
        self.cfg.setValue("pinned", json.dumps(lst))
        self.build_trees()

    def new_folder(self, base=None):
        sel = self.active_tree.selected_dirs()
        base = base or (sel[0] if sel else (self.current_dir or ""))
        if not base:
            return
        name, ok = QInputDialog.getText(self, "Nueva carpeta", f"Nombre (dentro de {os.path.basename(base) or base}):")
        if ok and name.strip():
            new = os.path.join(base, safe_filename(name.strip()) or name.strip())
            try:
                os.makedirs(new, exist_ok=False)
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))
                return
            self.refresh_trees()
            for t in (self.tree, self.tree2):   # se ve enseguida: se abre la carpeta de arriba y se marca la nueva
                if t.isVisible():
                    t.blockSignals(True)
                    t.reveal(new)
                    t.blockSignals(False)
            if self.current_dir and os.path.normcase(os.path.normpath(base)) == os.path.normcase(os.path.normpath(self.current_dir)):
                self.load_folder(self.current_dir, select=self.selected_paths() or None)
            self.update_watch()

    def rename_folder(self, path, tree=None):
        """Renombrar una carpeta escribiendo directamente sobre su nombre (en el árbol o en la lista)."""
        if self.is_protected(path):
            QMessageBox.information(self, "Carpeta principal", "Las carpetas principales no se pueden renombrar.")
            return
        np_ = os.path.normcase(os.path.normpath(path))
        for t in ([tree] if tree is not None else [getattr(self, "active_tree", self.tree), self.tree, self.tree2]):
            if t is None or not t.isVisible():
                continue
            for it in t.all_items():
                p_ = it.data(0, PATH_ROLE)
                if p_ and it.parent() is not None and os.path.normcase(os.path.normpath(p_)) == np_:
                    self.start_tree_rename(t, it, path)
                    return
        r = self.row_index.get(path)
        if r is not None and self.list.item(r) is not None:
            self.start_inline_rename(self.list.item(r), path)
            return
        name, ok = QInputDialog.getText(self, "Renombrar carpeta", "Nuevo nombre:", text=os.path.basename(path))
        name = safe_filename(name)
        if ok and name and name != os.path.basename(path):
            try:
                self.release_if([path])
                os.rename(path, os.path.join(os.path.dirname(path), name))
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))
                return
            self.after_fs_change()

    def start_tree_rename(self, t, it, path):
        if not getattr(t, "_ren_hooked", False):
            t._ren_hooked = True
            t.itemChanged.connect(lambda item, col, t=t: self.tree_rename_changed(t, item))
            t.itemDelegate().closeEditor.connect(lambda *_, t=t: QTimer.singleShot(0, lambda: self.tree_rename_end(t)))
        t._ren = (it, path, it.text(0))
        t.blockSignals(True)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        t.blockSignals(False)
        t.scrollToItem(it)
        t.editItem(it, 0)

    def tree_rename_changed(self, t, it):
        info = getattr(t, "_ren", None)
        if not info or it is not info[0] or it.text(0) == info[2]:
            return
        t._ren = None
        old_text = info[2]
        new = safe_filename(it.text(0).strip())
        t.blockSignals(True)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        if not new:
            it.setText(0, old_text)
        t.blockSignals(False)
        if new:
            QTimer.singleShot(0, lambda: self.do_rename_folder(info[1], new))

    def tree_rename_end(self, t):
        info = getattr(t, "_ren", None)
        if info:   # Esc o sin cambios
            t._ren = None
            try:
                t.blockSignals(True)
                info[0].setFlags(info[0].flags() & ~Qt.ItemFlag.ItemIsEditable)
                t.blockSignals(False)
            except RuntimeError:
                t.blockSignals(False)

    def do_rename_folder(self, path, name):
        if name == os.path.basename(path):
            return
        new = os.path.join(os.path.dirname(path), name)
        if os.path.exists(new):
            QMessageBox.warning(self, T("Renombrar carpeta"), T(f"Ya existe una carpeta llamada «{name}»."))
            self.refresh_trees()
            return
        try:
            self.release_if([path])
            self.fs_retry(os.rename, path, new)
            self.push_undo(T("renombrar carpeta"), [(new, path)])
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))
            self.refresh_trees()
            return
        cd = self.current_dir or ""
        ncd, npath = os.path.normcase(os.path.normpath(cd)), os.path.normcase(os.path.normpath(path))
        if ncd == npath or ncd.startswith(npath + os.sep):   # estabas dentro: se sigue en la carpeta renombrada
            self.current_dir = new + cd[len(path):]
        self.after_fs_change()
        self.statusBar().showMessage(T(f"Carpeta renombrada a «{name}»."))

    def rename_tree_current(self, tree):
        it = tree.currentItem()
        if it is not None and it.data(0, PATH_ROLE):
            self.rename_folder(it.data(0, PATH_ROLE), tree)

    def after_fs_change(self, _=None):
        while self.current_dir and not os.path.isdir(self.current_dir):
            self.current_dir = os.path.dirname(self.current_dir)
        self.refresh_trees()
        self.load_folder(self.current_dir, keep=False)

    def retarget(self, old, new):
        """Cuando un archivo cambia de ruta, conserva sus cambios pendientes y cachés."""
        for d in (self.pending, self.meta, self.tags_cache, self.suggestions):
            if old in d:
                d[new] = d.pop(old)
        if old in self.chosen:
            self.chosen.discard(old)
            self.chosen.add(new)

    def release_if(self, paths):
        """Windows bloquea el archivo que se está reproduciendo: lo suelta antes de tocarlo. También deja de vigilar
        las carpetas que se van a borrar, mover o renombrar (vigilar una carpeta la deja «en uso» y Windows no
        puede llevarla a la papelera: el programa se quedaba colgado)."""
        self.unwatch(paths)
        if self.player is None or not self.playing_path:
            return
        pp = os.path.normcase(os.path.normpath(self.playing_path))
        for p in paths:
            q = os.path.normcase(os.path.normpath(p))
            if pp == q or pp.startswith(q + os.sep):
                self.player.stop()
                self.player.setSource(QUrl())
                self.playing_path = None
                self.now_lbl.setText("Reproducción detenida para modificar el archivo.")
                self.mark_items()
                return

    def fs_retry(self, fn, *args):
        """Windows deja un archivo «en uso» un instante si algo lo está leyendo (miniatura, tonalidad, antivirus…):
        se reintenta durante unos 3 segundos antes de darlo por fallido."""
        for attempt in range(20):
            try:
                return fn(*args)
            except PermissionError:
                if attempt == 19:
                    raise
                QApplication.processEvents()
                time.sleep(0.15)

    def run_batch(self, title, items, fn):
        """Ejecuta fn(elemento) para cada uno en segundo plano, con una barra de progreso. La ventana sigue viva
        (no sale «No responde») pero no deja tocar nada más hasta terminar. Devuelve [(elemento, resultado, error)]."""
        items = list(items)
        w = BatchWorker(items, fn)
        dlg = QProgressDialog(T(title), None, 0, len(items), self)
        dlg.setWindowTitle(T(title))
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.setMinimumDuration(400)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        w.step.connect(dlg.setValue)
        loop = QEventLoop()
        w.finished.connect(loop.quit)
        w.start()
        if w.isRunning():
            loop.exec()
        w.wait()
        dlg.close()
        dlg.deleteLater()
        return w.results

    def push_undo(self, label, pairs):
        """Guarda (dónde está ahora, dónde estaba) de lo último que se movió o renombró."""
        pairs = [(a, b) for a, b in pairs if a != b]
        if pairs:
            self.fs_undo.append((label, pairs))
            del self.fs_undo[:-20]

    def undo_fs(self):
        if not self.fs_undo:
            self.statusBar().showMessage(T("No hay nada que deshacer (solo se pueden deshacer movimientos y renombrados)."))
            return
        label, pairs = self.fs_undo.pop()
        self.release_if([a for a, _ in pairs])
        ok, errors = 0, []
        for now, before in reversed(pairs):
            try:
                if not os.path.exists(now):
                    errors.append(T(f"«{os.path.basename(now)}» ya no está donde quedó."))
                    continue
                if os.path.exists(before):
                    errors.append(T(f"Ya hay otro «{os.path.basename(before)}» en el lugar original."))
                    continue
                os.makedirs(os.path.dirname(before), exist_ok=True)
                self.fs_retry(shutil.move, now, before)
                if os.path.isfile(before):
                    self.retarget(now, before)
                ok += 1
            except Exception as e:
                errors.append(f"{os.path.basename(now)}: {e}")
        cd = self.current_dir
        while cd and not os.path.isdir(cd):
            cd = os.path.dirname(cd)
        self.current_dir = cd
        self.after_fs_change()
        self.statusBar().showMessage(T(f"Deshecho: {label} ({ok} elemento(s) devueltos a su sitio)."))
        if errors:
            QMessageBox.warning(self, T("No se pudo deshacer todo"), "\n".join(errors[:20]))

    def move_items(self, paths, target):
        target = os.path.normpath(target)
        moved, errors, failed = 0, [], []
        undo = []
        if len(paths) >= 12:   # muchos: en segundo plano con barra de progreso
            return self.move_items_bg(paths, target)
        try:
            self.thumbs.request(self.gen, [])   # que las miniaturas no estén leyendo estos archivos mientras se mueven
        except Exception:
            note_quiet()
        self.release_if(list(paths))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        for i, src in enumerate(paths):
            if i % 10 == 0:
                self.statusBar().showMessage(T(f"Moviendo {i + 1} de {len(paths)}…"))
                QApplication.processEvents()
            src = os.path.normpath(src)
            if not os.path.exists(src):
                continue
            name = os.path.basename(src)
            if os.path.isdir(src) and self.is_protected(src):
                errors.append(f"«{name}» es una carpeta principal y no se puede mover.")
                continue
            if os.path.normpath(os.path.dirname(src)) == target:
                continue  # ya está ahí
            if os.path.isdir(src) and (target == src or target.startswith(src + os.sep)):
                errors.append(f"No puedes mover «{name}» dentro de sí misma.")
                continue
            dst = os.path.join(target, name)
            if os.path.exists(dst):  # nunca sobrescribe: crea "nombre (2)"
                root, ext = os.path.splitext(dst) if os.path.isfile(src) else (dst, "")
                n = 2
                while os.path.exists(f"{root} ({n}){ext}"):
                    n += 1
                dst = f"{root} ({n}){ext}"
            try:
                self.fs_retry(shutil.move, src, dst)
                moved += 1
                undo.append((dst, src))
                if os.path.isfile(dst):
                    self.retarget(src, dst)
            except Exception as e:
                errors.append(f"{name}: {e}")
                failed.append(src)
        QApplication.restoreOverrideCursor()
        self.push_undo(T("mover"), undo)
        self.statusBar().showMessage(f"{moved} elemento(s) movido(s) a {target}")
        if errors:
            QMessageBox.warning(self, "Algunos elementos no se movieron", "\n".join(errors[:20]))
        QApplication.processEvents()
        self.after_fs_change()
        if failed:   # solo quedan marcadas las que no se pudieron mover
            self.load_folder(self.current_dir, select=failed)

    def move_items_bg(self, paths, target):
        """Mover muchos elementos: mismo comportamiento (nunca sobrescribe, reintenta si está en uso) pero en segundo
        plano, con barra de progreso y sin dejar la ventana congelada."""
        try:
            self.thumbs.request(self.gen, [])
        except Exception:
            note_quiet()
        self.release_if(list(paths))
        errors, jobs = [], []
        for src in paths:
            src = os.path.normpath(src)
            if not os.path.exists(src):
                continue
            name = os.path.basename(src)
            if os.path.isdir(src) and self.is_protected(src):
                errors.append(f"«{name}» es una carpeta principal y no se puede mover.")
            elif os.path.normpath(os.path.dirname(src)) == target:
                continue
            elif os.path.isdir(src) and (target == src or target.startswith(src + os.sep)):
                errors.append(f"No puedes mover «{name}» dentro de sí misma.")
            else:
                jobs.append(src)

        def one(src):
            dst = os.path.join(target, os.path.basename(src))
            if os.path.exists(dst):   # nunca sobrescribe: crea "nombre (2)"
                root, ext = os.path.splitext(dst) if os.path.isfile(src) else (dst, "")
                n = 2
                while os.path.exists(f"{root} ({n}){ext}"):
                    n += 1
                dst = f"{root} ({n}){ext}"
            for attempt in range(20):   # «en uso» un instante (miniatura, antivirus…): se reintenta ~3 s
                try:
                    shutil.move(src, dst)
                    return dst
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.15)

        res = self.run_batch(f"Moviendo {len(jobs)} elementos…", jobs, one) if jobs else []
        moved, failed, undo = 0, [], []
        for src, dst, err in res:
            if err is not None or not dst:
                errors.append(f"{os.path.basename(src)}: {err}")
                failed.append(src)
                continue
            moved += 1
            undo.append((dst, src))
            if os.path.isfile(dst):
                self.retarget(src, dst)
        self.push_undo(T("mover"), undo)
        self.statusBar().showMessage(f"{moved} elemento(s) movido(s) a {target}")
        if errors:
            QMessageBox.warning(self, "Algunos elementos no se movieron", "\n".join(errors[:20]))
        self.after_fs_change()
        if failed:
            self.load_folder(self.current_dir, select=failed)

    def reload_all(self):
        find_folder_image.cache_clear()
        self.meta.clear()
        self.tags_cache.clear()
        TECH_MEM.clear()
        self.refresh_trees()
        self.load_folder(self.current_dir)

    # ---------------------------------------------------- Lista de canciones
    def toggle_view(self):
        self.set_view_mode({"icons": "list", "list": "details", "details": "icons"}[getattr(self, "view_mode", "icons")])

    def set_view(self, icons):
        self.set_view_mode("icons" if icons else "list", save=False)

    def set_view_mode(self, mode, save=True):
        """«icons» = iconos grandes · «list» = lista · «details» = lista con columnas (ordenables)."""
        mode = mode if mode in ("icons", "list", "details") else "icons"
        self.view_mode = mode
        self.icons_mode = mode == "icons"
        if mode == "icons":
            self.list.setViewMode(QListView.ViewMode.IconMode)
            self.list.setIconSize(QSize(self.icon_px, self.icon_px))
            self.list.setGridSize(QSize(self.icon_px + 44, self.icon_px + 74))   # 3 líneas para el nombre
            self.list.setSpacing(6)
            self.list.setWordWrap(True)
        else:
            self.list.setViewMode(QListView.ViewMode.ListMode)
            self.list.setIconSize(QSize(20, 20) if mode == "details" else QSize(self.list_px, self.list_px))
            self.list.setGridSize(QSize())
            self.list.setSpacing(0 if mode == "details" else 2)
            self.list.setWordWrap(False)
        if getattr(self, "details", None) is not None:
            self.details.set_enabled(mode == "details")
        nxt = {"icons": "☰ Lista", "list": "▤ Detalles", "details": "🔳 Iconos"}[mode]
        self.act_view.setText(nxt)
        i18n.deco(self.act_view)
        for m_, b_ in getattr(self, "view_btns", {}).items():
            b_.setChecked(m_ == mode)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(ROW_STEP if mode == "details" else 48)
        if save:
            self.cfg.setValue("view_mode", mode)

    def set_sort(self, key, desc=False):
        self.sort_key, self.sort_desc = key, bool(desc)
        self.cfg.setValue("sort_key", key)
        self.cfg.setValue("sort_desc", 1 if desc else 0)
        if getattr(self, "details", None) is not None:
            self.details.update_indicator()
        if self.current_dir:
            self.load_folder(self.current_dir, select=self.selected_paths() or None)

    def sort_files(self, files):
        import details
        key = getattr(self, "sort_key", "file")
        if key == "file":
            out = sorted(files, key=lambda f: os.path.basename(f).lower())
        else:
            need_tags = key in details.TAG_KEYS or key in ("date", "tracknumber", "discnumber")
            if key == "mtime":
                missing = 0
            elif need_tags:
                missing = sum(1 for f in files if f not in self.tags_cache)
            else:
                missing = sum(1 for f in files if tech_cached(f) is None)
            if missing > 150:
                # carpeta grande sin leer: se ordena por nombre ya y se reordena sola cuando terminen de leerse
                self._resort_pending = True
                out = sorted(files, key=lambda f: os.path.basename(f).lower())
            else:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    out = sorted(files, key=lambda f: (details.sort_value(self, f, key, tech_info), os.path.basename(f).lower()))
                finally:
                    QApplication.restoreOverrideCursor()
        return list(reversed(out)) if getattr(self, "sort_desc", False) else out

    def add_view_menus(self, m):
        vm = m.addMenu(icons.vicon("eye", ctx="menu"), T("Vista y orden"))
        for mode, label in (("icons", "Iconos"), ("list", "Lista"), ("details", "Lista con detalles")):
            a = vm.addAction(T(label))
            a.setCheckable(True)
            a.setChecked(self.view_mode == mode)
            a.triggered.connect(lambda _=False, m_=mode: self.set_view_mode(m_))
        vm.addSeparator()
        import details
        sm = vm.addMenu(icons.vicon("sort", ctx="menu"), T("Ordenar por"))
        for key, label in details.SORTS:
            a = sm.addAction(T(label))
            a.setCheckable(True)
            a.setChecked(self.sort_key == key)
            a.triggered.connect(lambda _=False, k=key: self.set_sort(k, self.sort_desc))
        sm.addSeparator()
        for desc, label in ((False, "Ascendente (A → Z, menor → mayor)"), (True, "Descendente (Z → A, mayor → menor)")):
            a = sm.addAction(T(label))
            a.setCheckable(True)
            a.setChecked(self.sort_desc == desc)
            a.triggered.connect(lambda _=False, d=desc: self.set_sort(self.sort_key, d))

    def eventFilter(self, obj, ev):
        # botones laterales del ratón = atrás / adelante, como en el Explorador
        if obj is self.centralWidget() and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.layout_overlay()
        if obj is self.list.viewport() and ev.type() == QEvent.Type.Wheel and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier) \
                and getattr(self, "view_mode", "icons") != "details":
            d = ev.angleDelta().y()
            if d:
                step = 12 if self.icons_mode else 4
                if self.icons_mode:
                    self.icon_px = max(40, min(160, self.icon_px + (step if d > 0 else -step)))
                    self.cfg.setValue("icon_px", self.icon_px)
                else:
                    self.list_px = max(20, min(80, self.list_px + (step if d > 0 else -step)))
                    self.cfg.setValue("list_px", self.list_px)
                self.set_view_mode(self.view_mode)
                self.statusBar().showMessage(f"Tamaño de los archivos: {self.icon_px if self.icons_mode else self.list_px} px (Ctrl + rueda)", 2500)
            return True
        if obj is self.btn_mute and ev.type() == QEvent.Type.Wheel:
            self.vol.wheelEvent(ev)   # rueda sobre el altavoz = subir/bajar volumen
            return True
        if obj is self.list.viewport() and ev.type() == QEvent.Type.MouseButtonPress:
            if ev.button() == Qt.MouseButton.BackButton:
                self.nav_back()
                return True
            if ev.button() == Qt.MouseButton.ForwardButton:
                self.nav_fwd()
                return True
        return super().eventFilter(obj, ev)

    def update_nav(self):
        self.btn_back.setEnabled(bool(self.back_stack))
        self.btn_fwd.setEnabled(bool(self.fwd_stack))
        self.btn_up.setEnabled(bool(self.current_dir) and os.path.dirname(self.current_dir) != self.current_dir)
        self.path_lbl.setText(self.path_lbl.fontMetrics().elidedText(
            self.current_dir or "", Qt.TextElideMode.ElideMiddle, max(200, self.path_lbl.width())))
        self.path_lbl.setToolTip(self.current_dir or "")

    def nav_to(self, path):
        self._nav_busy = True
        try:
            if not self.active_tree.reveal(path) or self.current_dir != path:
                self.load_folder(path)
        finally:
            self._nav_busy = False
        self.update_nav()

    def nav_back(self):
        while self.back_stack:
            p = self.back_stack.pop()
            if os.path.isdir(p):
                if self.current_dir:
                    self.fwd_stack.append(self.current_dir)
                self.nav_to(p)
                return
        self.update_nav()

    def nav_fwd(self):
        while self.fwd_stack:
            p = self.fwd_stack.pop()
            if os.path.isdir(p):
                if self.current_dir:
                    self.back_stack.append(self.current_dir)
                self.nav_to(p)
                return
        self.update_nav()

    def refresh_dir(self):
        """Vuelve a leer la carpeta (para ver archivos añadidos desde fuera) y los árboles."""
        if not self.current_dir or not os.path.isdir(self.current_dir):
            return
        for p in [p for p in list(self.meta) if os.path.dirname(p) == self.current_dir and not os.path.exists(p)]:
            self.meta.pop(p, None)
        find_folder_image.cache_clear()
        self.load_folder(self.current_dir, select=self.selected_paths() or None)
        self.statusBar().showMessage("Carpeta actualizada.")

    def nav_up(self):
        par = os.path.dirname(self.current_dir.rstrip("\\/")) if self.current_dir else ""
        if par and par != self.current_dir and os.path.isdir(par):
            self.open_dir(par)

    def load_folder(self, path, keep=True, select=None):
        if not path or not os.path.isdir(path):
            return
        if self.current_dir and os.path.normpath(path) != os.path.normpath(self.current_dir):
            if any(self.pending.values()) or self.edited or self.lyrics_edited:
                if not self.ask_unsaved():
                    return
        if not self._nav_busy and self.current_dir and os.path.normpath(path) != os.path.normpath(self.current_dir):
            if not self.back_stack or self.back_stack[-1] != self.current_dir:
                self.back_stack.append(self.current_dir)
            self.fwd_stack.clear()
            del self.back_stack[:-100]
        self.cfg.setValue("last_dir", path)
        if self.current_dir and os.path.normcase(os.path.normpath(path)) != os.path.normcase(os.path.normpath(self.current_dir)) \
                and self.search.text():
            # como en el Explorador: al cambiar de carpeta se quita la búsqueda (si no, la carpeta nueva sale casi vacía)
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        keep_paths = set(select) if select else (
            set(self.selected_paths()) if keep and path == self.current_dir else set())
        self.current_dir = path
        self._resort_pending = False
        if self.chk_sub.isChecked():
            files = [os.path.join(dp, f) for dp, _, fn in os.walk(path) for f in fn
                     if os.path.splitext(f)[1].lower() in AUDIO_EXT]
        else:
            files = []
            try:   # scandir ya sabe si es archivo (sin preguntar al disco por cada uno: mucho más rápido en Windows)
                with os.scandir(path) as it_:
                    for e in it_:
                        if os.path.splitext(e.name)[1].lower() in AUDIO_EXT and e.is_file():
                            files.append(e.path)
            except OSError:
                files = []
        self.dir_snapshot = (path, self.dir_signature(path))
        files = self.sort_files(files)
        self.gen += 1
        self.thumb_queue = []
        same_dir = bool(self.current_dir) and getattr(self, "_listed_dir", None) == path
        keep_v = self.list.verticalScrollBar().value() if same_dir else 0
        self._listed_dir = path
        self._loading_dir = True
        # la búsqueda no oculta filas (con miles de canciones Qt se vuelve lentísimo y la lista parpadea):
        # la lista se llena solo con lo que coincide
        self._all_dirs = [] if self.chk_sub.isChecked() else list(subdirs(path))
        self._all_files = files
        self.thumb_queue = [f for f in files if self.meta.get(f) is None]
        self._filter_t = (self.search.text() or "").strip().lower()
        self.fill_list()
        self._loading_dir = False
        self._thumb_left = len(self.thumb_queue)
        if keep_v:   # misma carpeta (tras borrar, mover, renombrar…): la lista se queda donde estaba
            sb = self.list.verticalScrollBar()
            for ms in (0, 60, 200):
                QTimer.singleShot(ms, lambda v=keep_v: sb.setValue(min(v, sb.maximum())))
        self.update_nav()
        if keep_paths:
            self.list.blockSignals(True)
            for p in keep_paths:
                if p in self.row_index:
                    self.list.item(self.row_index[p]).setSelected(True)
            self.list.blockSignals(False)
            self.on_select()
        self.mark_items()
        self.list.overlay.setText("Aquí no hay música todavía.\n\nElige otra carpeta a la izquierda o pega archivos con Ctrl+V.")
        self.list.overlay.setGeometry(self.list.viewport().rect())
        self.list.overlay.setVisible(self.list.count() == 0)
        self.thumbs.request(self.gen, self.thumb_queue)
        self.apply_filter(self.search.text())
        self.statusBar().showMessage(f"{os.path.basename(os.path.normpath(path)) or path} · {len(files)} canciones")
        if self._resort_pending and not self._thumb_left:
            self._resort_pending = False
        self.update_watch()

    def on_thumb(self, gen, f, img, lyrics, tags):
        """Las miniaturas llegan muy seguidas (cientos por segundo desde la caché): se juntan y se ponen por tandas,
        así la lista no se repinta cientos de veces."""
        buf = getattr(self, "_thumb_buf", None)
        if buf is None:
            buf = self._thumb_buf = []
            self._thumb_flush = QTimer(self)
            self._thumb_flush.setSingleShot(True)
            self._thumb_flush.setInterval(120)
            self._thumb_flush.timeout.connect(self.flush_thumbs)
        buf.append((gen, f, img, lyrics, tags))
        if not self._thumb_flush.isActive():
            self._thumb_flush.start()

    def flush_thumbs(self):
        buf, self._thumb_buf = self._thumb_buf, []
        if not buf:
            return
        self.list.setUpdatesEnabled(False)
        try:
            for args in buf:
                self.apply_thumb(*args)
        finally:
            self.list.setUpdatesEnabled(True)
        if getattr(self, "_resort_pending", False) and getattr(self, "_thumb_left", 1) <= 0 and self.current_dir:
            self._resort_pending = False   # ya se leyó todo: ahora sí se ordena por la columna elegida
            self.load_folder(self.current_dir, select=self.selected_paths() or None)

    def apply_thumb(self, gen, f, img, lyrics, tags):
        """Llega una miniatura generada (o leída de la caché) en segundo plano."""
        if gen == self.gen:
            self._thumb_left = getattr(self, "_thumb_left", 1) - 1
        icon = QIcon(QPixmap.fromImage(img)) if img is not None and not img.isNull() else None
        self.meta[f] = {"icon": icon, "has_lyrics": bool(lyrics)}
        if tags and "_tech" in tags:
            tags = dict(tags)
            tech = tags.pop("_tech")
            if isinstance(tech, (list, tuple)) and len(tech) == 2 and isinstance(tech[1], dict) and f not in TECH_MEM:
                TECH_MEM[f] = (tech[0], tech[1], 0)   # la primera vez que se use solo se comprueba la fecha
        if tags and f not in self.tags_cache:
            self.tags_cache[f] = tags
        if gen != self.gen:
            return
        r = self.row_index.get(f)
        if icon is not None and r is not None and r < self.list.count():
            it = self.list.item(r)
            if it is not None and it.data(PATH_ROLE) == f:
                it.setIcon(icon)

    def clean_thumbs(self):
        """Borra (en segundo plano) las miniaturas guardadas que no se usaron en la última hora."""
        import threading
        threading.Thread(target=thumbs.cleanup, daemon=True).start()

    def selected_paths(self):
        return [i.data(PATH_ROLE) for i in self.list.selectedItems() if i.data(KIND_ROLE) != "dir"]

    def current_path(self):
        it = self.list.currentItem()
        if it is not None and it.isSelected() and it.data(KIND_ROLE) != "dir":
            return it.data(PATH_ROLE)
        return self.cur_paths[0] if self.cur_paths else None

    def mark_items(self):
        for r in range(self.list.count()):
            it = self.list.item(r)
            p = it.data(PATH_ROLE)
            st = (bool(self.pending.get(p)), p == self.playing_path)
            if it.data(MARK_ROLE) == st or (it.data(MARK_ROLE) is None and st == (False, False)):
                continue   # nada cambió: no se repinta ni se recoloca la lista
            it.setData(MARK_ROLE, st)
            f = it.font()
            if self.pending.get(p):
                it.setForeground(QBrush(QColor("#e67e00")))
                f.setBold(True)
            else:
                it.setData(Qt.ItemDataRole.ForegroundRole, None)
                f.setBold(False)
            it.setFont(f)
            if p == self.playing_path:
                it.setBackground(QBrush(QColor(70, 130, 220, 70)))
            else:
                it.setData(Qt.ItemDataRole.BackgroundRole, None)
        self.update_dirty()
        n = sum(1 for v in self.pending.values() if v)
        self.pend_lbl.setText(f"●  {n} archivo(s) con cambios sin guardar · Ctrl+S" if n else "")
        self.pend_lbl.setStyleSheet("color: #e67e00; padding-right: 10px; font-weight: 600;")

    # ------------------------------------------------------------ Reproductor
    def set_now(self, title, sub=""):
        fm = self.now_lbl.fontMetrics()
        self.now_lbl.setText(fm.elidedText(title, Qt.TextElideMode.ElideRight, 235))
        self.now_lbl.setToolTip(title)
        self.now_sub.setText(self.now_sub.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, 235))

    def build_player_bar(self):
        """Reproductor a lo ancho en la parte de abajo de la ventana (ahorra espacio)."""
        bar = QFrame()
        bar.setObjectName("playerbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 4, 0)
        h.setSpacing(6)
        self.now_cover = QLabel()
        self.now_cover.setObjectName("nowcover")
        self.now_cover.setFixedSize(52, 52)
        self.now_cover.setScaledContents(True)
        self.now_cover.setPixmap(self.default_icon.pixmap(52, 52))
        self.now_lbl = QLabel("Doble clic en una canción para reproducirla")
        self.now_lbl.setObjectName("nowtitle")
        self.now_sub = QLabel("")
        self.now_sub.setObjectName("hint")
        info = QVBoxLayout()
        info.setSpacing(1)
        info.addWidget(self.now_lbl)
        info.addWidget(self.now_sub)
        infow = QWidget()
        infow.setLayout(info)
        infow.setFixedWidth(245)
        self.btn_prev, self.btn_play = GlyphButton("prev"), PlayButton()
        self.btn_stop, self.btn_next = GlyphButton("stop"), GlyphButton("next")
        for b, tip in ((self.btn_prev, "Anterior"), (self.btn_play, "Reproducir / pausa (Espacio)"),
                       (self.btn_stop, "Detener"), (self.btn_next, "Siguiente")):
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek = ClickSlider(Qt.Orientation.Horizontal)
        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setObjectName("hint")
        self.btn_mute = QPushButton()
        self.btn_mute.setIcon(icons.vicon("vol3"))
        self.btn_mute.setObjectName("tbtn")
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mute.setToolTip("Silenciar")
        self.btn_mute.installEventFilter(self)
        self.vol = ClickSlider(Qt.Orientation.Vertical)
        self.vol.setRange(0, 100)
        self.vol.setValue(50)          # cada vez que se abre el programa empieza a la mitad
        self.vol.wheel_step = 5
        self.vol.tip_fn = lambda v: f"Volumen: {v}%"
        self.seek.tip_fn = lambda v: f"{fmt_ms(v)} / {fmt_ms(self.seek.maximum())}"
        for w in (self.now_cover, infow):
            w.setParent(bar)   # siguen existiendo para el resto del código, pero ocultos
            w.hide()
        self.btn_list = GlyphButton("list")
        self.btn_list.setToolTip("Lista de reproducción")
        self.btn_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_list.clicked.connect(self.toggle_library)
        self.btn_list.setToolTip("Todas las canciones, carpetas, artistas y géneros (para elegir qué reproducir)")
        self.btn_fx = GlyphButton("fx")
        self.btn_fx.setToolTip("Ajustes de la canción: graves, agudos, tempo, tono, velocidad, bucle, eco…")
        self.btn_fx.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fx.clicked.connect(self.open_fx)
        self.btn_list.setParent(bar)   # ya no va en la barra (lo hace el botón redondo ☰); se conserva escondido
        self.btn_list.hide()
        h.addWidget(self.btn_prev)
        h.addWidget(self.btn_play)
        h.addWidget(self.btn_next)
        h.addWidget(self.btn_stop)
        self.viz = VizBar(lambda: self.player.position() if self.player is not None else 0)
        self.seek.setFixedWidth(self.viz.width())
        seekbox = QWidget()
        sg = QGridLayout(seekbox)
        sg.setContentsMargins(0, 0, 0, 0)
        sg.addWidget(self.viz, 0, 0)
        sg.addWidget(self.seek, 0, 0)
        h.addWidget(seekbox)
        h.addWidget(self.time_lbl)
        h.addWidget(self.btn_fx)
        self.btn_phone = GlyphButton("phone")
        self.btn_phone.setToolTip("Modo celular: abre o cierra el reproductor grande (a la derecha)")
        self.btn_phone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_phone.clicked.connect(self.toggle_phone)
        h.addWidget(self.btn_phone)
        self.btn_mini = GlyphButton("mini")
        self.btn_mini.setToolTip("Modo ventana: una ventanita con solo la portada y los botones (se puede mover y agrandar)")
        self.btn_mini.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mini.clicked.connect(self.open_cover_window)
        h.addWidget(self.btn_mini)
        self.volbox = VolBox(self.btn_mute, self.vol)
        h.addWidget(self.volbox)
        self.disc = SpinDisc(40)
        h.addWidget(self.disc)
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop.clicked.connect(self.stop_play)
        self.btn_prev.clicked.connect(lambda: self.step_play(-1))
        self.btn_next.clicked.connect(lambda: self.step_play(1))
        if HAS_AUDIO:
            self.player = QMediaPlayer()
            self.audio = QAudioOutput()
            self.player.setAudioOutput(self.audio)
            self.audio.setVolume(vol_curve(50))
            self.player.positionChanged.connect(self.on_pos)
            self.player.durationChanged.connect(self.on_dur)
            self.player.playbackStateChanged.connect(self.on_state)
            self.player.mediaStatusChanged.connect(self.on_media_status)
            self.player.errorOccurred.connect(self.on_player_error)
            self.seek.sliderReleased.connect(lambda: self.player.setPosition(self.seek.value()))
            self.seek.seekTo.connect(self.player.setPosition)
            self.vol.valueChanged.connect(self.on_vol)
            self.btn_mute.clicked.connect(self.toggle_mute)
        else:
            self.set_now("Sin reproductor integrado", "El doble clic abrirá tu reproductor predeterminado")
            for w in (self.btn_prev, self.btn_play, self.btn_stop, self.btn_next, self.btn_list, self.seek, self.vol, self.btn_fx):
                w.setEnabled(False)
        return bar

    def play_item(self, item, user=True):
        path = item.data(PATH_ROLE) if item is not None else None
        if not path:
            return
        self.pl_active = False   # reproducir desde la carpeta: sigue el orden de la carpeta
        self.mini_seq = None
        self.play_file(path)
        if user:
            self.expand_player()

    def toggle_library(self):
        """Botón ☰ de la barra: abre a la derecha la lista para elegir qué reproducir (todas las canciones, carpetas,
        artistas y géneros); otro clic la cierra. La lista de reproducción propia sigue en el botón redondo ☰."""
        inner = getattr(self.mobile, "inner", None) if self.mobile is not None else None
        if inner is None:
            self.show_playlist()
            return
        if getattr(self, "mini", None) is not None and self.mini.in_use():
            self.exit_mini()
        if self.mobile.isVisible() and inner.lib.isVisible() and not getattr(self.mobile, "_closing", False):
            self.mobile.close_panel()
            return
        if not self.mobile.isVisible():
            self.mobile.open_panel()
        if not inner.lib.isVisible():
            inner.open_library()

    def toggle_phone(self):
        """Botón de celular de la barra: muestra u oculta el reproductor grande del borde derecho."""
        if self.mobile is None:
            return
        if getattr(self, "mini", None) is not None and self.mini.in_use():
            self.exit_mini()   # estaba en su ventana aparte: vuelve al editor
        inner = getattr(self.mobile, "inner", None)
        if self.mobile.isVisible() and not getattr(self.mobile, "_closing", False):
            if inner is not None and inner.lib.isVisible():
                inner.close_library()   # estaba mostrando la lista: pasa al reproductor
            else:
                self.mobile.close_panel()
        else:
            if inner is not None and inner.lib.isVisible():
                inner.close_library()
            self.mobile.open_panel()

    def open_cover_window(self):
        """Botón de ventanita de la barra: la ventanita «solo la portada», con el editor abierto."""
        if self.player is None:
            return
        if self.mini is not None and self.mini.in_use() and self.mini.compact.isVisible():
            self.exit_mini()   # ya estaba: se cierra (el botón la abre y la cierra)
            return
        self.enter_mini(True, compact=True)

    def expand_player(self):
        """Con el estilo celular, al reproducir (doble clic, «Reproducir»…) se despliega el reproductor grande."""
        if getattr(self, "mini", None) is not None and self.mini.in_use():
            return   # en modo reproductor el editor está escondido
        if (getattr(self, "player_style", "classic") == "mobile" and self.mobile is not None
                and not self.mobile.isVisible() and int(self.cfg.value("auto_expand", 1) or 0)):
            self.mobile.open_panel()

    def play_file(self, path):
        if self.player is None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        self.playing_path = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        if getattr(self, "mobile", None) is not None and self.mobile.isVisible():
            self.mobile.track_changed(path)
        if getattr(self, "mini", None) is not None and self.mini.in_use():
            self.mini.track_changed(path)
        self.media_track(path)
        artist, album = self.val(path, "artist"), self.val(path, "album")
        self.set_now(self.val(path, "title") or os.path.splitext(os.path.basename(path))[0],
                     " · ".join(x for x in (artist, album) if x))
        pm = QPixmap()
        data = self.cover_data_of(path)
        if data and pm.loadFromData(data) and not pm.isNull():
            self.now_cover.setPixmap(pm)
            self.disc.set_cover(pm)
        else:
            self.now_cover.setPixmap(self.default_icon.pixmap(52, 52))
            self.disc.set_cover(None)
        self.apply_cover_colors(data)
        self.start_viz(path)
        self.pl_refresh()
        self.mark_items()

    def toggle_play(self):
        if self.player is None:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.player.source().isEmpty():
            it = next((self.list.item(r) for r in range(self.list.count())
                       if self.list.item(r).data(KIND_ROLE) != "dir"), None)
            self.play_item(it)
        else:
            self.player.play()
            self.expand_player()

    def stop_play(self):
        if self.player is not None:
            self.player.stop()
            self.apply_cover_colors(None)

    def apply_cover_colors(self, data):
        """Tiñe el programa con el color de la portada que suena (si la opción está activa)."""
        if not int(self.cfg.value("cover_colors", 1) or 0):
            data = None
        col = dominant_color(data, self.theme == "dark") if data else None
        col = col or (self.accent or None)
        if col == getattr(self, "_cur_tint", "x"):
            return
        self._cur_tint = col
        apply_theme(QApplication.instance(), self.theme, col)

    def toggle_cover_colors(self, on):
        self.cfg.setValue("cover_colors", 1 if on else 0)
        self._cur_tint = "x"
        p = self.playing_path
        self.apply_cover_colors(self.cover_data_of(p) if p and on else None)

    # ------------------------------------------------- Visualizador
    def start_viz(self, path):
        self.viz.set_data(None, 25)
        if not hasattr(self, "_viz_workers"):
            self._viz_workers = set()
        for old in self._viz_workers:
            old.requestInterruption()
        w = VizWorker(path, VizBar.COLS)
        self._viz_workers.add(w)   # se conserva hasta que termine (evita destruir un hilo en marcha)
        w.ready.connect(self.viz_ready)
        w.finished.connect(lambda w=w: self._viz_workers.discard(w))
        w.start()

    def viz_ready(self, path, arr, fps):
        if path == self.playing_path:
            self.viz.set_data(arr, fps)
            if getattr(self, "mini", None) is not None:
                self.mini.set_viz(path, arr)
            inner = getattr(getattr(self, "mobile", None), "inner", None)
            if inner is not None:
                inner.set_viz(path, arr)

    # ------------------------------------------------- Modo reproductor
    def enter_mini(self, detached=False, compact=False):
        """Modo reproductor: una ventana aparte con el reproductor. detached=True: el editor sigue abierto (dos
        ventanas, cada una en la barra de tareas); False: el editor se esconde y queda solo el reproductor."""
        if self.player is None:
            self.statusBar().showMessage(T("El reproductor integrado no está disponible."))
            return
        import miniplayer
        if self.mini is None:
            self.mini = miniplayer.MiniPlayer(self, inspect_file, tech_info, read_tags, AUDIO_EXT, find_folder_image)
        # compact=True: la ventanita «solo la portada»; False: el reproductor completo (estilo celular)
        self.cfg.setValue("mini_compact", 1 if compact else 0)
        if self.mini.in_use():
            self.set_mini_detached(detached)
            if compact and not self.mini.compact.isVisible():
                self.mini.enter_compact()
            elif not compact and self.mini.compact.isVisible():
                self.mini.leave_compact()
            return
        self._mini_was_max = self.isMaximized()
        self.mini_detached = bool(detached)
        self.mini.track_changed(self.playing_path)
        self.mini.place_initial(self.frameGeometry())
        self.mini.open_window()
        if detached:
            if getattr(self, "mobile", None) is not None and self.mobile.isVisible():
                self.mobile.close_panel()   # el reproductor ya está en su ventana: no hace falta el panel
        else:
            self.hide()

    def set_mini_detached(self, on):
        """Con el reproductor ya abierto: mostrar también el editor (dos ventanas) o esconderlo."""
        if self.mini is None or not self.mini.in_use():
            return
        self.mini_detached = bool(on)
        self.mini.sync_mode()
        if on:
            if getattr(self, "_mini_was_max", False):
                self.showMaximized()
            else:
                self.showNormal()
            if getattr(self, "mobile", None) is not None and self.mobile.isVisible():
                self.mobile.close_panel()
            for w_ in (self.mini, self.mini.compact):   # el reproductor queda delante
                if w_.isVisible():
                    w_.raise_()
        else:
            self._mini_was_max = self.isMaximized()
            self.hide()

    def exit_mini(self):
        was_detached = getattr(self, "mini_detached", False)
        self.mini_detached = False
        if self.mini is not None:
            self.mini.leave()
        if not was_detached or not self.isVisible():
            if getattr(self, "_mini_was_max", False):
                self.showMaximized()
            else:
                self.showNormal()
        self.raise_()
        self.activateWindow()
        if getattr(self, "mobile", None) is not None and self.mobile.isVisible():
            self.mobile.track_changed(self.playing_path)

    def quit_from_mini(self):
        self.exit_mini()
        QTimer.singleShot(0, self.close)

    # ------------------------------------------------- Lista de reproducción
    QUEUE = "Cola actual"

    def pl_load(self):
        try:
            lists = json.loads(str(self.cfg.value("playlists", "{}") or "{}"))
        except ValueError:
            lists = {}
        if not isinstance(lists, dict):
            lists = {}
        if self.QUEUE not in lists:
            try:
                old = json.loads(str(self.cfg.value("playlist", "[]") or "[]"))
            except ValueError:
                old = []
            lists[self.QUEUE] = old if isinstance(old, list) else []
        self.pl_lists = {k: [p for p in v if isinstance(p, str) and os.path.isfile(p)]
                         for k, v in lists.items() if isinstance(v, list)}
        name = str(self.cfg.value("pl_name", self.QUEUE))
        self.pl_name = name if name in self.pl_lists else self.QUEUE
        self.playlist = self.pl_lists[self.pl_name]

    def pl_save(self):
        self.cfg.setValue("playlists", json.dumps(self.pl_lists))
        self.cfg.setValue("pl_name", self.pl_name)

    def pl_switch(self, name):
        if name not in self.pl_lists:
            return
        self.pl_name = name
        self.playlist = self.pl_lists[name]
        self.pl_save()
        self.pl_refresh()

    def pl_new(self, copy=False):
        name, ok = QInputDialog.getText(self, "Nueva lista de reproducción",
                                        "Nombre de la lista:" if not copy else "Guardar esta lista como:")
        name = (name or "").strip()
        if not ok or not name:
            return
        if name in self.pl_lists:
            QMessageBox.information(self, "Lista de reproducción", "Ya existe una lista con ese nombre.")
            return
        self.pl_lists[name] = list(self.playlist) if copy else []
        self.pl_switch(name)

    def pl_delete(self):
        if self.pl_name == self.QUEUE:
            self.pl_clear()
            return
        q = QMessageBox.question(self, "Eliminar lista", f"¿Eliminar la lista «{self.pl_name}»? (Las canciones no se borran.)")
        if q == QMessageBox.StandardButton.Yes:
            del self.pl_lists[self.pl_name]
            self.pl_switch(self.QUEUE)

    def pl_expand(self, paths):
        out = []
        for p in paths:
            if os.path.isdir(p):
                for root, dirs, files in os.walk(p):
                    dirs.sort(key=str.lower)
                    for f in sorted(files, key=str.lower):
                        if os.path.splitext(f)[1].lower() in AUDIO_EXT:
                            out.append(os.path.join(root, f))
            elif os.path.isfile(p) and os.path.splitext(p)[1].lower() in AUDIO_EXT:
                out.append(p)
        return out

    def pl_add(self, paths):
        have = set(self.playlist)
        new = [p for p in self.pl_expand(paths) if p not in have]
        self.playlist.extend(new)
        self.pl_save()
        self.pl_refresh()
        self.statusBar().showMessage(f"{len(new)} canción(es) añadida(s) a «{self.pl_name}» ({len(self.playlist)} en total).")

    def play_folder(self, folder):
        files = self.pl_expand([folder])
        if not files:
            self.statusBar().showMessage("Esa carpeta no tiene canciones.")
            return
        self.pl_switch(self.QUEUE)
        self.playlist[:] = files
        self.pl_save()
        self.pl_active = True
        self.play_file(files[0])
        self.pl_refresh()
        nombre = os.path.basename(os.path.normpath(folder)) or folder
        self.statusBar().showMessage(f"Reproduciendo la carpeta «{nombre}» ({len(files)} canciones).")

    def pl_label(self, i, p):
        name = os.path.splitext(os.path.basename(p))[0]
        return ("▶  " if p == self.playing_path and self.pl_active else "") + f"{i + 1}. {name}"

    def pl_refresh(self):
        lw = getattr(self, "pl_list", None)
        if lw is None:
            return
        lw.blockSignals(True)
        lw.clear()
        for i, p in enumerate(self.playlist):
            it = QListWidgetItem(self.pl_label(i, p))
            it.setData(PATH_ROLE, p)
            it.setToolTip(p)
            it.setSizeHint(QSize(10, 38))
            lw.addItem(it)
            if p == self.playing_path and self.pl_active:
                lw.setCurrentItem(it)
        lw.blockSignals(False)
        self.pl_combo.blockSignals(True)
        self.pl_combo.clear()
        self.pl_combo.addItems(list(self.pl_lists))
        self.pl_combo.setCurrentText(self.pl_name)
        self.pl_combo.blockSignals(False)
        self.pl_count.setText(f"{len(self.playlist)} canciones")

    def pl_update_np(self):
        if getattr(self, "np_title", None) is None:
            return
        st = self.player.playbackState() if self.player is not None else None
        if not self.playing_path or st == QMediaPlayer.PlaybackState.StoppedState:
            self.np_title.setText("Nada sonando")
            self.np_sub.setText("Doble clic en una canción para reproducirla")
            self.np_cover.setPixmap(self.default_icon.pixmap(64, 64))
            return
        self.np_title.setText(self.now_lbl.toolTip() or self.now_lbl.text())
        icon = "▶ Reproduciendo" if st == QMediaPlayer.PlaybackState.PlayingState else "⏸ En pausa"
        self.np_sub.setText(f"{icon} · {self.now_sub.toolTip() or self.now_sub.text()}".strip(" ·"))
        pm = self.now_cover.pixmap()
        if pm is not None and not pm.isNull():
            self.np_cover.setPixmap(rounded_pm(pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                          Qt.TransformationMode.SmoothTransformation), 10))

    def pl_sync(self):
        self.playlist[:] = [self.pl_list.item(r).data(PATH_ROLE) for r in range(self.pl_list.count())]
        self.pl_save()
        self.pl_refresh()

    def pl_remove(self):
        rows = sorted((self.pl_list.row(it) for it in self.pl_list.selectedItems()), reverse=True)
        for r in rows:
            del self.playlist[r]
        self.pl_save()
        self.pl_refresh()

    def pl_clear(self):
        self.playlist.clear()
        self.pl_save()
        self.pl_refresh()

    def pl_play(self, li):
        p = li.data(PATH_ROLE)
        if p and os.path.isfile(p):
            self.pl_active = True
            self.play_file(p)

    def pl_export(self):
        if not self.playlist:
            return
        fn, _ = QFileDialog.getSaveFileName(self, "Guardar lista de reproducción", f"{self.pl_name}.m3u8", "Lista M3U (*.m3u8 *.m3u)")
        if fn:
            try:
                with open(fn, "w", encoding="utf-8") as fh:
                    fh.write("#EXTM3U\n" + "\n".join(self.playlist) + "\n")
                self.statusBar().showMessage(f"Lista guardada en {fn}")
            except OSError as e:
                QMessageBox.warning(self, "Error", str(e))

    def pl_import(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Cargar lista de reproducción", "", "Lista M3U (*.m3u8 *.m3u)")
        if not fn:
            return
        try:
            base = os.path.dirname(fn)
            with open(fn, encoding="utf-8", errors="replace") as fh:
                items = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
        except OSError as e:
            QMessageBox.warning(self, "Error", str(e))
            return
        self.playlist[:] = [p for p in (x if os.path.isabs(x) else os.path.join(base, x) for x in items) if os.path.isfile(p)]
        self.pl_save()
        self.pl_refresh()

    def build_pl_panel(self, central):
        """Panel flotante con la lista de reproducción: se despliega sobre la columna derecha (portada, géneros, letra)."""
        panel = QFrame(central)
        panel.setObjectName("plpanel")
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        t = QLabel("Reproduciendo ahora")
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        v.addWidget(t)
        card = QFrame()
        card.setObjectName("npcard")
        ch = QHBoxLayout(card)
        ch.setContentsMargins(8, 8, 8, 8)
        self.np_cover = QLabel()
        self.np_cover.setFixedSize(64, 64)
        ch.addWidget(self.np_cover)
        col = QVBoxLayout()
        self.np_title = QLabel("Nada sonando")
        self.np_title.setWordWrap(True)
        ft = self.np_title.font()
        ft.setBold(True)
        self.np_title.setFont(ft)
        self.np_sub = QLabel("")
        self.np_sub.setObjectName("hint")
        self.np_sub.setWordWrap(True)
        col.addWidget(self.np_title)
        col.addWidget(self.np_sub)
        col.addStretch(1)
        ch.addLayout(col, 1)
        v.addWidget(card)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.pl_combo = QComboBox()
        self.pl_combo.activated.connect(lambda _=0: self.pl_switch(self.pl_combo.currentText()))
        row.addWidget(self.pl_combo, 1)
        for text, tip, fn in (("＋", "Crear una lista nueva", self.pl_new), ("🗑", "Eliminar la lista (o vaciar la cola)", self.pl_delete)):
            b = QPushButton(text)
            b.setObjectName("iconbtn")
            b.setFixedSize(34, 34)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            row.addWidget(b)
        more = QPushButton("⋯")
        more.setObjectName("iconbtn")
        more.setFixedSize(34, 34)
        more.setToolTip("Más opciones")
        mm = TMenu(self)
        mm.addAction("💾 Guardar esta lista con otro nombre…", lambda: self.pl_new(copy=True))
        mm.addAction("➖ Quitar las seleccionadas (Supr)", self.pl_remove)
        mm.addAction("🧹 Vaciar la lista", self.pl_clear)
        mm.addSeparator()
        mm.addAction("📤 Exportar como archivo .m3u8…", self.pl_export)
        mm.addAction("📥 Importar archivo .m3u8…", self.pl_import)
        more.setMenu(mm)
        row.addWidget(more)
        v.addLayout(row)
        self.pl_list = PlaylistList()
        self.pl_list.dropped.connect(self.pl_add)
        self.pl_list.reordered.connect(self.pl_sync)
        self.pl_list.itemDoubleClicked.connect(self.pl_play)
        sc = QShortcut(QKeySequence("Delete"), self.pl_list)
        sc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sc.activated.connect(self.pl_remove)
        v.addWidget(self.pl_list, 1)
        hint = QLabel("Arrastra aquí canciones o carpetas. Arrastra para ordenar. Doble clic para reproducir.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        v.addWidget(hint)
        self.pl_count = QLabel("")
        self.pl_count.setObjectName("hint")
        v.addWidget(self.pl_count)
        v.addSpacing(46)   # deja libre el botón flotante
        panel.hide()
        self.pl_panel = panel
        fab = QPushButton(central)
        fab.setIcon(icons.vicon("menu", "white"))
        fab.setIconSize(QSize(20, 20))
        fab.setObjectName("fab")
        fab.setFixedSize(40, 40)
        fab.setCursor(Qt.CursorShape.PointingHandCursor)
        fab.setToolTip("Todas las canciones, carpetas, artistas y géneros (para elegir qué reproducir)")
        sh = QGraphicsDropShadowEffect(fab)
        sh.setBlurRadius(18)
        sh.setOffset(0, 3)
        sh.setColor(QColor(0, 0, 0, 150))
        fab.setGraphicsEffect(sh)
        fab.clicked.connect(self.toggle_library)
        self.pl_fab = fab
        central.installEventFilter(self)
        self.main_split.splitterMoved.connect(lambda *a: self.layout_overlay())
        self.mid_split.splitterMoved.connect(lambda *a: self.layout_overlay())
        self.pl_refresh()
        self.pl_update_np()
        i18n.retranslate(panel)
        QTimer.singleShot(0, self.layout_overlay)

    def layout_overlay(self):
        c = self.centralWidget()
        if c is None or getattr(self, "pl_panel", None) is None:
            return
        r = self.cover_col
        tl = r.mapTo(c, QPoint(0, 0))
        self.pl_panel.setGeometry(tl.x(), tl.y(), max(300, r.width()), max(200, c.height() - tl.y()))
        mob = getattr(self, "mobile", None)
        # el botón redondo va siempre en la esquina de abajo a la derecha; con el reproductor grande abierto se
        # esconde (ahí ya está «Cola»), en vez de quedar flotando en medio de la ventana
        panel_open = mob is not None and mob.isVisible()
        self.pl_fab.move(c.width() - self.pl_fab.width() - 16, c.height() - self.pl_fab.height() - 12)
        self.pl_fab.setVisible(not panel_open and self.player_bar.isVisible())
        if self.pl_panel.isVisible():
            self.pl_panel.raise_()
        self.pl_fab.raise_()
        if mob is not None:
            mob.place()

    def show_playlist(self):
        """Muestra u oculta el panel flotante de la lista de reproducción."""
        if getattr(self, "player_style", "classic") == "mobile" and self.mobile is not None:
            if not self.mobile.isVisible():
                self.mobile.open_panel()
            self.mobile.show_page(2)   # en el estilo celular la lista va dentro del reproductor
            return
        if self.pl_panel.isVisible():
            self.pl_panel.hide()
            self.pl_fab.setIcon(icons.vicon("menu", "white"))
        else:
            self.layout_overlay()
            self.pl_refresh()
            self.pl_update_np()
            self.pl_panel.show()
            self.pl_panel.raise_()
            self.pl_fab.setIcon(icons.vicon("close", "white"))
            self.pl_fab.raise_()

    def play_seq(self):
        """Canciones que se van a recorrer: la lista de reproducción activa o las de la carpeta, en su orden."""
        if self.pl_active and self.playlist:
            return list(self.playlist), True
        ms = getattr(self, "mini_seq", None)
        if ms and self.playing_path in ms:   # se eligió desde la biblioteca del modo reproductor
            return list(ms), True
        return [self.list.item(r).data(PATH_ROLE) for r in range(self.list.count())
                if self.list.item(r).data(KIND_ROLE) != "dir"], False

    def set_trees_mode(self, mode):
        """«normal» = árboles siempre a la izquierda · «drawer» = escondidos, salen con la flechita del borde izquierdo."""
        self.trees_mode = mode if mode in ("normal", "drawer") else "normal"
        self.cfg.setValue("trees_mode", self.trees_mode)
        self.tree_drawer.set_enabled(self.trees_mode == "drawer")
        self.layout_overlay()

    def set_player_style(self, style, first=False):
        """«classic» = solo la barra de abajo · «mobile» = solo el reproductor estilo celular del borde derecho."""
        if self.mobile is None:
            style = "classic"
        self.player_style = style if style in ("classic", "mobile") else "classic"
        self.cfg.setValue("player_style", self.player_style)
        if self.player_style == "mobile":
            self.player_bar.hide()
            self.pl_fab.hide()            # la lista va dentro del reproductor celular
            self.pl_panel.hide()
            self._central_lay.setContentsMargins(self._central_lay.contentsMargins().left(), 0, 20, 0)   # canal propio para la flechita
            self.statusBar().setMinimumHeight(44)
            self.wide_viz.setGeometry(self.statusBar().rect())
            self.wide_viz.show()
            self.wide_viz.lower()
            self.wide_viz.start()
            self.mobile.tab.show()
            self.mobile.place()
            if not first or int(self.cfg.value("mobile_open", 1) or 0):
                if not self.mobile.isVisible():
                    self.mobile.open_panel()
        else:
            self.player_bar.show()
            self.pl_fab.show()
            self._central_lay.setContentsMargins(self._central_lay.contentsMargins().left(), 0, 0, 0)
            self.statusBar().setMinimumHeight(0)
            self.wide_viz.hide()
            if self.mobile is not None:
                self.mobile.anim.stop()
                self.mobile.hide()
                self.mobile.tab.hide()
        self.layout_overlay()

    def set_shuffle(self, on):
        self.shuffle = bool(on)
        self._shuffle_hist = []
        self.cfg.setValue("shuffle", 1 if on else 0)

    def set_repeat(self, mode):
        self.repeat = mode if mode in ("off", "all", "one") else "off"
        self.cfg.setValue("repeat", self.repeat)

    def step_play(self, d, auto=False):
        if self.player is None:
            return
        seq, from_pl = self.play_seq()
        if not seq:
            return
        cur = self.playing_path
        nxt = None
        if self.shuffle and len(seq) > 1:
            if d < 0 and self._shuffle_hist:
                nxt = self._shuffle_hist.pop()
            else:
                import random
                nxt = random.choice([p for p in seq if p != cur])
                if cur:
                    self._shuffle_hist = (self._shuffle_hist + [cur])[-200:]
        else:
            idx = seq.index(cur) if cur in seq else (-1 if d > 0 else len(seq))
            n = idx + d
            if not 0 <= n < len(seq):
                if self.repeat != "all":
                    return
                n %= len(seq)   # «repetir todas»: al final vuelve al principio
            nxt = seq[n]
        if from_pl:
            self.play_file(nxt)
        else:
            r = self.row_index.get(nxt)
            if r is None:
                return
            it = self.list.item(r)
            self.list.scrollToItem(it)
            self.play_item(it, user=False)

    def on_vol(self, x):
        if self.player is None:
            return
        if x > 0 and self.audio.isMuted():
            self.audio.setMuted(False)
        self.audio.setVolume(vol_curve(x))   # curva de oído: el cambio se siente parejo en todo el recorrido
        self.update_vol_icon()

    def toggle_mute(self):
        if self.player is None:
            return
        self.audio.setMuted(not self.audio.isMuted())
        self.update_vol_icon()

    def update_vol_icon(self):
        v = self.vol.value()
        muted = self.player is not None and self.audio.isMuted()
        self.btn_mute.setIcon(icons.vicon("vol0" if muted or v == 0 else ("vol1" if v < 34 else "vol2" if v < 67 else "vol3")))
        self.btn_mute.setToolTip(T("Quitar silencio") if muted else T("Silenciar"))

    def on_state(self, st):
        if getattr(self, "taskbar", None) is not None:
            self.taskbar.set_playing(st == QMediaPlayer.PlaybackState.PlayingState)
        self.btn_play.set_playing(st == QMediaPlayer.PlaybackState.PlayingState)
        self.disc.set_playing(st == QMediaPlayer.PlaybackState.PlayingState)
        if getattr(self, "wide_viz", None) is not None and self.wide_viz.isVisible():
            QTimer.singleShot(0, self.wide_viz.start)
        self.viz.set_state({QMediaPlayer.PlaybackState.PlayingState: "playing",
                            QMediaPlayer.PlaybackState.PausedState: "paused"}.get(st, "stopped"))
        self.pl_update_np()

    def on_media_status(self, st):
        if st == QMediaPlayer.MediaStatus.EndOfMedia:
            if getattr(self, "repeat", "off") == "one":
                self.player.setPosition(0)
                self.player.play()
            elif int(self.cfg.value("autonext", 1) or 0):
                self.step_play(1, auto=True)  # pasa a la siguiente canción de la lista

    def on_pos(self, ms):
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        self.time_lbl.setText(f"{fmt_ms(ms)} / {fmt_ms(self.player.duration())}")

    def on_dur(self, ms):
        self.seek.setRange(0, ms)
        self.time_lbl.setText(f"{fmt_ms(self.player.position())} / {fmt_ms(ms)}")

    def on_player_error(self, err, msg):
        self.statusBar().showMessage(f"No se pudo reproducir: {msg}")

    # ------------------------------------------------- Renombrar archivos
    def pattern_name(self, p, pat):
        a, t = self.val(p, "artist"), self.val(p, "title")
        al = self.val(p, "album")
        tr = self.val(p, "tracknumber").split("/")[0].strip()
        tr = tr.zfill(2) if tr.isdigit() else tr
        parts = {"Artista - Título": [a, t], "Pista - Título": [tr, t],
                 "Álbum - Título": [al, t], "Título": [t]}[pat]
        if not all(parts):
            return ""
        return safe_filename(" - ".join(parts))

    def rename_selected(self):
        it = self.list.currentItem()
        if it is not None and it.isSelected() and it.data(KIND_ROLE) == "dir" and not self.cur_paths:
            self.rename_folder(it.data(PATH_ROLE))   # una carpeta de la lista: se renombra ahí mismo
            return
        self.apply_form()
        paths = list(self.cur_paths)
        if not paths:
            return
        if len(paths) == 1:
            p = paths[0]
            r = self.row_index.get(p)
            if r is not None:   # se edita el nombre ahí mismo, como en el Explorador
                self.start_inline_rename(self.list.item(r), p)
                return
            base, ext = os.path.splitext(os.path.basename(p))
            new, ok = QInputDialog.getText(self, "Renombrar archivo", f"Nuevo nombre (sin «{ext}»):", text=base)
            if not ok:
                return
            res = [(p, safe_filename(new))]
        else:
            pat, ok = QInputDialog.getItem(self, "Renombrar varias canciones",
                                           f"Nombrar los {len(paths)} archivos como:", PATTERNS, 0, False)
            if not ok:
                return
            res = [(p, self.pattern_name(p, pat)) for p in paths]
        self.do_renames(res)

    @staticmethod
    def strip_parens(text, square=True):
        """«Summer (Official Video) [HD]» → «Summer». Quita lo que va entre paréntesis (y corchetes), también anidado."""
        t, prev = text or "", None
        while t != prev:
            prev = t
            t = re.sub(r"\s*\([^()]*\)", "", t)
            t = re.sub(r"\s*（[^（）]*）", "", t)
            if square:
                t = re.sub(r"\s*\[[^\[\]]*\]", "", t)
        t = re.sub(r"\s{2,}", " ", t)
        t = re.sub(r"(\s*-\s*){2,}", " - ", t)   # «Artista -  - Título»
        return t.strip(" -_.,")

    def copy_meta(self):
        """Copia las etiquetas (y la portada) de UNA canción para pegarlas luego en otras."""
        paths = self.selected_paths()
        if len(paths) != 1:
            self.statusBar().showMessage(T("Elige una sola canción para copiar sus metadatos."))
            return
        self.apply_form()
        p = paths[0]
        data = {k: self.val(p, k) for k, _ in FIELDS}
        pend = self.pending.get(p, {})
        cover = pend["_cover"] if "_cover" in pend else None
        if cover is None:
            try:
                cover = inspect_file(p).get("cover")
            except Exception:
                cover = None
        self.meta_clip = {"src": p, "tags": data, "cover": cover or None}
        self.statusBar().showMessage(T(f"Metadatos copiados de «{os.path.basename(p)}». Elige otras canciones y pulsa "
                                       f"Ctrl+Shift+V (o clic derecho → Pegar metadatos)."))

    def paste_meta(self):
        clip = getattr(self, "meta_clip", None)
        if not clip:
            self.statusBar().showMessage(T("Primero copia los metadatos de una canción (clic derecho → Copiar metadatos)."))
            return
        paths = [p for p in self.selected_paths() if p != clip["src"]] or self.selected_paths()
        if not paths:
            self.statusBar().showMessage(T("Selecciona las canciones donde quieres pegar los metadatos."))
            return
        self.apply_form()
        dlg = QDialog(self)
        dlg.setWindowTitle(T("Pegar metadatos"))
        dlg.resize(520, 520)
        v = QVBoxLayout(dlg)
        sub = QLabel(T(f"De «{os.path.basename(clip['src'])}» a {len(paths)} canción(es). Marca lo que quieres pegar:"))
        sub.setObjectName("dlgsub")
        sub.setWordWrap(True)
        v.addWidget(sub)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        checks = {}
        for i, (k, label) in enumerate(FIELDS):
            val = clip["tags"].get(k, "")
            c = QCheckBox(T(label))
            c.setChecked(bool(val) and k not in ("title", "tracknumber"))   # título y pista suelen ser distintos
            c.setEnabled(True)
            lv = QLabel(val or "—")
            lv.setObjectName("hint")
            lv.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(c, i, 0)
            grid.addWidget(lv, i, 1)
            checks[k] = c
        r = len(FIELDS)
        c_cov = QCheckBox(T("Portada"))
        c_cov.setChecked(bool(clip.get("cover")))
        c_cov.setEnabled(bool(clip.get("cover")))
        grid.addWidget(c_cov, r, 0)
        grid.addWidget(QLabel(T("sí") if clip.get("cover") else T("(la canción no tiene portada)")), r, 1)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        note = QLabel(T("Un campo vacío marcado también se pega (sirve para borrar ese dato en las otras)."))
        note.setObjectName("dlgsub")
        note.setWordWrap(True)
        v.addWidget(note)
        v.addStretch(1)
        row = QHBoxLayout()
        b_all = QPushButton(T("Marcar todo"))
        b_all.clicked.connect(lambda: [c.setChecked(True) for c in checks.values()])
        row.addWidget(b_all)
        row.addStretch(1)
        ok = QPushButton(T("📥 Pegar"))
        ok.setObjectName("accent")
        ok.clicked.connect(dlg.accept)
        cancel = QPushButton(T("Cancelar"))
        cancel.clicked.connect(dlg.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        v.addLayout(row)
        i18n.retranslate(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        keys = [k for k, c in checks.items() if c.isChecked()]
        for p in paths:
            ch = self.pending.setdefault(p, {})
            for k in keys:
                ch[k] = clip["tags"].get(k, "")
        if c_cov.isChecked() and clip.get("cover"):
            for p in paths:
                self.pending.setdefault(p, {})["_cover"] = clip["cover"]
        self.mark_items()
        self.on_select()
        self.statusBar().showMessage(T(f"Metadatos pegados en {len(paths)} canción(es) (en naranja). Pulsa Ctrl+S para guardar."))

    def open_strip_parens(self, paths):
        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            self.statusBar().showMessage(T("Selecciona una o varias canciones."))
            return
        self.apply_form()
        dlg = QDialog(self)
        dlg.setWindowTitle(T("Quitar paréntesis"))
        dlg.resize(980, 520)
        v = QVBoxLayout(dlg)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)
        try:
            from picard_tools import dialog_header, nice_table
        except Exception:
            dialog_header = nice_table = None
        if dialog_header:
            dialog_header(v, T("🧹 Quitar paréntesis"), T("Quita lo que va entre paréntesis (y si quieres entre corchetes) "
                                                        "en el nombre del archivo y en el título: «Summer (Official Video)» → «Summer»."))
        opts = QHBoxLayout()
        c_file = QCheckBox(T("En el nombre del archivo"))
        c_title = QCheckBox(T("En el título de la canción"))
        c_sq = QCheckBox(T("También lo que va entre corchetes [ ]"))
        for c in (c_file, c_title, c_sq):
            c.setChecked(True)
            opts.addWidget(c)
        opts.addStretch(1)
        v.addLayout(opts)
        tb = QTableWidget(0, 4)
        tb.setHorizontalHeaderLabels([T("Archivo"), T("Nuevo nombre"), T("Título"), T("Nuevo título")])
        tb.verticalHeader().setVisible(False)
        tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        for c in range(4):
            tb.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        if nice_table:
            nice_table(tb)
        v.addWidget(tb, 1)
        status = QLabel("")
        status.setObjectName("dlgsub")
        v.addWidget(status)
        br = QHBoxLayout()
        br.addStretch(1)
        go = QPushButton(T("🧹 Quitar paréntesis"))
        go.setObjectName("accent")
        cancel = QPushButton(T("Cancelar"))
        br.addWidget(go)
        br.addWidget(cancel)
        v.addLayout(br)
        plan = []

        def preview():
            plan.clear()
            tb.setRowCount(0)
            for p in paths:
                stem = os.path.splitext(os.path.basename(p))[0]
                title = self.val(p, "title")
                nstem = self.strip_parens(stem, c_sq.isChecked()) if c_file.isChecked() else stem
                ntitle = self.strip_parens(title, c_sq.isChecked()) if (c_title.isChecked() and title) else title
                nstem = safe_filename(nstem) or stem
                ntitle = ntitle or title
                if nstem == stem and ntitle == title:
                    continue
                plan.append((p, nstem if nstem != stem else None, ntitle if ntitle != title else None))
                r = tb.rowCount()
                tb.insertRow(r)
                for c_, txt in enumerate((stem, nstem if nstem != stem else "—", title, ntitle if ntitle != title else "—")):
                    tb.setItem(r, c_, QTableWidgetItem(txt))
            n_f = sum(1 for _p, f, _t in plan if f)
            n_t = sum(1 for _p, _f, t in plan if t)
            status.setText(T(f"{len(plan)} de {len(paths)} canciones cambian · {n_f} nombres de archivo · {n_t} títulos.")
                           if plan else T("Ninguna de estas canciones tiene paréntesis que quitar."))
            go.setEnabled(bool(plan))

        for c in (c_file, c_title, c_sq):
            c.toggled.connect(preview)
        cancel.clicked.connect(dlg.reject)
        go.clicked.connect(dlg.accept)
        preview()
        i18n.retranslate(dlg)
        if dlg.exec() != QDialog.DialogCode.Accepted or not plan:
            return
        for p, _f, title in plan:   # títulos: quedan pendientes de guardar (en naranja)
            if title:
                self.pending.setdefault(p, {})["title"] = title
        renames = [(p, f) for p, f, _t in plan if f]
        if renames:
            self.do_renames(renames)   # los cambios pendientes pasan al nombre nuevo
        else:
            self.mark_items()
            self.on_select()
        self.statusBar().showMessage(T(f"Paréntesis quitados en {len(plan)} canción(es). Los títulos están pendientes de guardar (Ctrl+S)."))

    def start_inline_rename(self, it, path):
        if not getattr(self, "_inline_hooked", False):
            self._inline_hooked = True
            self.list.itemChanged.connect(self.inline_changed)
            for d in {self.list.itemDelegate(), getattr(getattr(self, "details", None), "delegate", None),
                      getattr(getattr(self, "details", None), "normal_delegate", None)}:
                if d is not None:
                    d.closeEditor.connect(lambda *_: QTimer.singleShot(0, self.inline_end))
        self._inline = (it, path, it.text())
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsEditable)
        self.list.scrollToItem(it)
        self.list.setCurrentItem(it)
        self.list.editItem(it)

    def inline_changed(self, it):
        info = getattr(self, "_inline", None)
        if not info or it is not info[0] or it.text() == info[2]:
            return
        self._inline = None
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
        new = safe_filename(it.text().strip())
        old_path = info[1]
        if not new:
            it.setText(info[2])
            return
        if it.data(KIND_ROLE) == "dir":
            QTimer.singleShot(0, lambda: self.do_rename_folder(old_path, new))
            return
        QTimer.singleShot(0, lambda: self.do_renames([(old_path, new)]))

    def inline_end(self):
        info = getattr(self, "_inline", None)
        if info:   # se canceló (Esc) o no cambió nada
            self._inline = None
            try:
                info[0].setFlags(info[0].flags() & ~Qt.ItemFlag.ItemIsEditable)
            except RuntimeError:
                pass

    def do_renames(self, res):
        done, errors, newpaths = 0, [], []
        undo = []
        for old, nb in res:
            oname = os.path.basename(old)
            if not nb:
                errors.append(f"{oname}: nombre vacío o faltan datos (artista/título).")
                newpaths.append(old)
                continue
            new = os.path.join(os.path.dirname(old), nb + os.path.splitext(old)[1])
            if new == old:
                newpaths.append(old)
                continue
            if os.path.exists(new) and not os.path.samefile(old, new):
                errors.append(f"{oname}: ya existe «{os.path.basename(new)}».")
                newpaths.append(old)
                continue
            try:
                self.release_if([old])
                for attempt in range(8):   # el archivo puede estar abierto un instante (miniatura, tonalidad…)
                    try:
                        os.rename(old, new)
                        break
                    except PermissionError:
                        if attempt == 7:
                            raise
                        QApplication.processEvents()
                        time.sleep(0.15)
                self.retarget(old, new)
                newpaths.append(new)
                undo.append((new, old))
                done += 1
            except Exception as e:
                errors.append(f"{oname}: {e}")
                newpaths.append(old)
        self.push_undo(T("renombrar"), undo)
        if done:
            self.load_folder(self.current_dir, select=newpaths)
            self.statusBar().showMessage(f"{done} archivo(s) renombrado(s).")
        if errors:
            QMessageBox.warning(self, "No se renombraron algunos archivos", "\n".join(errors))

    # ---------------------------------------------------- Metadatos y panel
    def tags_of(self, p):
        if p not in self.tags_cache:
            self.tags_cache[p] = read_tags(p)
        return self.tags_cache[p]

    def val(self, p, k):
        return self.pending.get(p, {}).get(k, self.tags_of(p).get(k, ""))

    def on_lyrics_edit(self):
        if not self._loading:
            self.lyrics_edited = True
            self.update_dirty()

    def update_dirty(self):
        """Muestra el botón «Guardar» sobre la portada solo si la selección actual tiene cambios."""
        try:
            d = bool(self.edited or self.lyrics_edited or any(self.pending.get(p) for p in self.cur_paths))
            self.save_btn.setEnabled(d)
        except AttributeError:
            pass

    def yes_no_save(self):
        """«¿Desea guardar los cambios?» con solo Sí / No. Devuelve True si responde Sí."""
        mb = QMessageBox(self)
        mb.setIcon(QMessageBox.Icon.Question)
        mb.setWindowTitle("Cambios sin guardar")
        mb.setText("¿Desea guardar los cambios?")
        yes = mb.addButton("Sí", QMessageBox.ButtonRole.YesRole)
        mb.addButton("No", QMessageBox.ButtonRole.NoRole)
        mb.setDefaultButton(yes)
        mb.exec()
        return mb.clickedButton() is yes

    def ask_unsaved(self, paths=None):
        """Pregunta qué hacer con los cambios sin guardar. Devuelve False si el usuario quiere quedarse."""
        self.apply_form()
        ps = [p for p in (paths if paths is not None else self.pending) if self.pending.get(p)]
        if not ps:
            return True
        if self.yes_no_save():
            self.save_all()
        else:
            for p in ps:
                self.pending.pop(p, None)
                self.chosen.discard(p)
                self.meta.pop(p, None)
            self.mark_items()
        return True

    def on_select(self):
        self.sel_timer.stop()
        new_paths = self.selected_paths()
        if (self.cur_paths and set(new_paths) != set(self.cur_paths) and not getattr(self, "_in_prompt", False)
                and not getattr(self, "_loading_dir", False)):
            self._in_prompt = True
            try:
                ok = self.ask_unsaved(list(self.cur_paths))
            finally:
                self._in_prompt = False
            if not ok:   # se queda donde estaba: vuelve a marcar la selección anterior
                self.list.blockSignals(True)
                self.list.clearSelection()
                for p in self.cur_paths:
                    r = self.row_index.get(p)
                    if r is not None:
                        self.list.item(r).setSelected(True)
                self.list.blockSignals(False)
                return
            new_paths = self.selected_paths()
        if (self.edited or self.lyrics_edited) and self.cur_paths:
            self.apply_form()  # no pierdas lo que escribiste al cambiar de canción
        paths = new_paths
        self.cur_paths = paths
        self.edited.clear()
        self.lyrics_edited = False
        uncached = sum(1 for p in paths if p not in self.tags_cache and not self.pending.get(p))
        big = len(paths) > 1 and uncached > 12   # muchas sin leer todavía: no se traba leyendo todas
        key = tuple(paths)
        if key != getattr(self, "_sel_key", None):
            self._sel_key, self._sel_tries = key, 0
        if big and self._sel_tries < 6:
            self._sel_tries += 1
            self._sel_retry.start()   # se vuelve a intentar cuando las miniaturas hayan leído las etiquetas
        for k, le in self.inputs.items():
            if big:
                le.setText("")
                le.setPlaceholderText("‹varios valores›")
                le.setEnabled(True)
                continue
            vs = {self.val(p, k) for p in paths}
            multi = len(vs) > 1
            le.setText("" if multi or not vs else next(iter(vs)))
            le.setCursorPosition(0)   # que se vea el principio del texto, no el final
            le.setPlaceholderText("‹varios valores›" if multi else ("" if paths else "-"))
            le.setEnabled(bool(paths))
        self.fill_tech(paths)
        dirs = {os.path.dirname(p) for p in paths}
        self.dir_le.setText(next(iter(dirs)) if len(dirs) == 1 else ("‹varios›" if dirs else ""))
        self.dir_le.setCursorPosition(0)
        self.show_current(self.current_path(), len(paths))
        self.update_suggestions()

    def fill_tech(self, paths):
        icons_ = {"codec": "🎵", "enc": "🧩", "tag": "🏷", "bitrate": "⚡", "freq": "🔊", "dur": "⏱", "mode": "⚙",
                  "size": "💾", "ch": "🎧", "key": "🎹"}
        names = {"codec": "Formato", "enc": "Códec", "tag": "Etiqueta", "bitrate": "Bitrate", "freq": "Frecuencia",
                 "dur": "Duración", "mode": "Modo", "size": "Tamaño", "ch": "Canales", "key": "Tonalidad"}
        if not paths:
            for k, chip in self.tech.items():
                chip.set_full(f"{icons_[k]} —", T(names[k]))
            return
        if len(paths) == 1:
            infos = [tech_info(paths[0])]
        else:   # varias: usa lo que ya está en memoria y lee como mucho unas pocas más (no traba la ventana)
            infos, budget = [], 12
            for p in paths[:400]:
                i = tech_cached(p)
                if i is None and budget > 0:
                    budget -= 1
                    i = tech_info(p)
                if i is not None:
                    infos.append(i)
            infos = infos or [tech_info(paths[0])]
        for k, chip in self.tech.items():
            if k == "key":
                continue
            vs = {i.get(k, "—") for i in infos}
            v = T(next(iter(vs))) if len(vs) == 1 else T("‹varios›")
            tip = infos[0].get("enc_full", "") if (k == "enc" and len(infos) == 1) else ""
            chip.set_full(f"{icons_[k]} {v}", f"{T(names[k])}: {tip or v}")
        self.fill_key(paths)

    def fill_key(self, paths):
        """Tonalidad: de la etiqueta si la tiene; si no, se estima analizando el audio (solo con una canción)."""
        import keydetect
        chip = self.tech["key"]
        if len(paths) != 1:
            chip.set_full("🎹 " + T("‹varios›") if len(paths) > 1 else "🎹 —", T("Tonalidad"))
            return
        p = paths[0]
        tag = keydetect.read_tag(p)
        if tag:
            parsed = keydetect.parse_tag(tag)
            if parsed:
                short, long_ = keydetect.describe(*parsed)
                chip.set_full(f"🎹 {short}", f"{T('Tonalidad')}: {T(long_)} ({T('de la etiqueta')})")
            else:
                chip.set_full(f"🎹 {tag}", f"{T('Tonalidad')}: {tag} ({T('de la etiqueta')})")
            return
        try:
            key = (p, os.path.getmtime(p))
        except OSError:
            key = (p, 0)
        if key in self.key_cache:
            self.show_key(p, *self.key_cache[key])
            return
        chip.set_full("🎹 …", T("Calculando la tonalidad…"))
        w = KeyWorker(p)
        w.done.connect(lambda path, pc, mi, conf, key=key: self.on_key(key, path, pc, mi, conf))
        w.finished.connect(lambda w=w: self._key_workers.discard(w))
        if not hasattr(self, "_key_workers"):
            self._key_workers = set()
        self._key_workers.add(w)
        w.start()

    def on_key(self, key, path, pc, minor, conf):
        self.key_cache[key] = (pc, minor, conf)
        if self.cur_paths == [path]:
            self.show_key(path, pc, minor, conf)

    def show_key(self, path, pc, minor, conf):
        import keydetect
        chip = self.tech["key"]
        if pc < 0:
            chip.set_full("🎹 —", T("No se pudo calcular la tonalidad"))
            return
        short, long_ = keydetect.describe(pc, minor)
        sure = "" if conf >= 0.5 else " ?"
        chip.set_full(f"🎹 {short}{sure}", f"{T('Tonalidad')}: {T(long_)} · {T('estimada analizando el audio (puede fallar)')}")

    def show_current(self, path, n):
        self._loading = True
        if not path:
            self.cover_lbl.clear()
            self.cover_lbl.setText("Selecciona una canción")
            self.info_lbl.setText("")
            self.status_lbl.setText("")
            self.lyrics.setPlainText("")
            self.lyrics.setEnabled(False)
            self.lyrics.setPlaceholderText("")
            self.lyr_status.setText("")
            self._loading = False
            return
        d = inspect_file(path)
        pend = self.pending.get(path, {})
        data, has_cover, note = d["cover"], d["cover"] is not None, ""
        if "_cover" in pend:
            data, has_cover, note = (pend["_cover"] or None), bool(pend["_cover"]), "Portada nueva (pendiente de guardar)"
        elif data is None:
            fi = find_folder_image(os.path.dirname(path))
            if fi:
                try:
                    with open(fi, "rb") as fh:
                        data = fh.read()
                    note = "Mostrando la imagen de la carpeta"
                except OSError:
                    data = None
        pm = QPixmap()
        if data and pm.loadFromData(data):
            self.cover_lbl.setPixmap(rounded_pm(pm.scaled(COVER, COVER, Qt.AspectRatioMode.KeepAspectRatio,
                                                          Qt.TransformationMode.SmoothTransformation)))
        else:
            self.cover_lbl.clear()
            self.cover_lbl.setText("Sin portada")
        lyr = pend["lyrics"] if "lyrics" in pend else d["lyrics"]
        has_l = bool(lyr.strip())
        if n == 1:
            self.lyrics.setEnabled(True)
            self.lyrics.setPlaceholderText("Escribe o pega la letra aquí…")
            self.lyrics.setPlainText(lyr)
            if "lyrics" in pend:
                self.lyr_status.setText("✎ Letra nueva (pendiente de guardar): revísala antes de guardar")
            else:
                self.lyr_status.setText(("✔ Esta canción ya tiene letra" + (" ⏱ sincronizada (con minutos)" if is_lrc(lyr) else ""))
                                        if has_l else "✘ Esta canción no tiene letra")
        else:
            self.lyrics.setEnabled(False)
            self.lyrics.setPlainText("")
            self.lyrics.setPlaceholderText("Selecciona UNA sola canción para ver o editar su letra.")
            self.lyr_status.setText("")
        dims = f"Portada: {pm.width()}×{pm.height()} px · {len(data) // 1024} KB" if data and not pm.isNull() else ""
        if data and not pm.isNull():
            kind = "PNG" if data[:4] == b"\x89PNG" else ("JPEG" if data[:2] == b"\xff\xd8" else "IMG")
            self.info_lbl.setText(f"{kind} · {pm.width()}×{pm.height()} px · {len(data) // 1024} KB")
        else:
            self.info_lbl.setText("")
        self.info_lbl.setVisible(bool(self.info_lbl.text()))
        self.info_lbl.setToolTip(note)
        self.info_lbl.setStyleSheet("color:#E67E00" if "pendiente" in note else "")
        yes = '<span style="color:#2ecc71">✔ sí</span>'
        no = '<span style="color:#e74c3c">✘ no</span>'
        g = html.escape(self.val(path, "genre")) or "—"
        extra = f"<br><i>(+{n - 1} seleccionadas más)</i>" if n > 1 else ""
        self.status_lbl.setText(f"🖼 Portada: {yes if has_cover else no} &nbsp; 📝 Letra: {yes if has_l else no}"
                                f"<br>🎼 Género: <b>{g}</b>{extra}")
        self._loading = False

    def undo_changes(self):
        paths = list(self.cur_paths)
        if not paths:
            return
        for p in paths:
            self.pending.pop(p, None)
            self.chosen.discard(p)
        self.edited.clear()
        self.lyrics_edited = False
        self.mark_items()
        self.on_select()
        self.statusBar().showMessage("Cambios deshechos en la selección.")

    def apply_form(self):
        paths = self.cur_paths
        if not paths:
            return
        for p in paths:
            for k in self.edited:
                self.pending.setdefault(p, {})[k] = self.inputs[k].text().strip()
        if self.lyrics_edited and len(paths) == 1:
            self.pending.setdefault(paths[0], {})["lyrics"] = self.lyrics.toPlainText()
        if self.edited or self.lyrics_edited:
            self.statusBar().showMessage("Cambios aplicados (pendientes de guardar, en naranja).")
        self.edited.clear()
        self.lyrics_edited = False
        self.mark_items()

    def set_cover(self):
        if not self.cur_paths:
            return
        f, _ = QFileDialog.getOpenFileName(self, "Elegir imagen de portada", "",
                                           "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp)")
        if not f:
            return
        try:
            with open(f, "rb") as fh:
                data = prepare_cover(fh.read(), self.cover_side())
        except OSError as e:
            QMessageBox.warning(self, "Error", str(e))
            return
        if data is None:
            QMessageBox.warning(self, "Imagen no válida", "No se pudo leer esa imagen.")
            return
        self.apply_form()
        for p in self.cur_paths:
            self.pending.setdefault(p, {})["_cover"] = data
        self.mark_items()
        self.show_current(self.current_path(), len(self.cur_paths))

    def auto_cover(self):
        paths = list(self.cur_paths)
        if not paths:
            QMessageBox.information(self, "Portada automática", "Selecciona una o varias canciones primero.")
            return
        self.apply_form()
        todo = [p for p in paths if not self.cover_data_of(p)]
        if not todo and len(paths) == 1:
            q = QMessageBox.question(self, "Ya tiene portada", "Esta canción ya tiene portada. ¿Buscar otras opciones de mejor calidad en internet?")
            if q == QMessageBox.StandardButton.Yes:
                todo = paths
        if not todo:
            self.statusBar().showMessage("Todas las canciones seleccionadas ya tienen portada.")
            return
        groups, order = {}, []
        for p in todo:  # canciones del mismo álbum comparten la elección
            artist, album = self.val(p, "artist"), self.val(p, "album")
            title = self.val(p, "title") or os.path.splitext(os.path.basename(p))[0]
            key = (CoverWorker.norm(artist), CoverWorker.norm(album) or p)
            if key not in groups:
                groups[key] = {"paths": [], "q": (artist, title, album)}
                order.append(key)
            groups[key]["paths"].append(p)
        self.cov_groups = [groups[k] for k in order]
        self.cov_ok, self.cov_total, self.cov_fail = 0, len(todo), []
        self.cov_queue, self.cov_busy, self.cov_wdone, self.cov_first, self.cov_reported = [], False, False, False, False
        self.statusBar().showMessage(f"Buscando opciones de portada para {len(self.cov_groups)} álbum(es) en iTunes, Deezer y SoundCloud…")
        self.cov_worker = CoverWorker([g["q"] for g in self.cov_groups], 1200)
        self.cov_worker.group_done.connect(self.cov_group_done)
        self.cov_worker.finished_all.connect(self.cov_finished)
        self.cov_worker.start()

    def cov_group_done(self, i, cands):
        self.cov_queue.append((i, cands))
        self.cov_pump()

    def cov_finished(self):
        self.cov_wdone = True
        self.cov_pump()

    def cov_pump(self):
        if self.cov_busy:
            return
        self.cov_busy = True
        try:
            while self.cov_queue:
                i, cands = self.cov_queue.pop(0)
                g = self.cov_groups[i]
                if not cands:
                    self.cov_fail.append(g["paths"][0])
                    continue
                data = None
                if self.cov_first:
                    data = cands[0]["data"]
                else:
                    art, title, album = g["q"]
                    name = f"{art} - {album or title}" if art else (album or title)
                    dlg = CoverChooser(self, name, cands, len(self.cov_groups) - i - 1)
                    i18n.retranslate(dlg)
                    if dlg.exec():
                        data = dlg.choice
                        self.cov_first = dlg.take_first
                if data:
                    d = prepare_cover(data, self.cover_side())
                    if d:
                        for p in g["paths"]:
                            self.pending.setdefault(p, {})["_cover"] = d
                        self.cov_ok += len(g["paths"])
                        self.mark_items()
                        cp = self.current_path()
                        if cp and cp in g["paths"]:
                            self.show_current(cp, len(self.cur_paths))
            done = self.cov_wdone and not self.cov_queue and not self.cov_reported
        finally:
            self.cov_busy = False
        if done:
            self.cov_reported = True
            self.auto_cover_done()

    def auto_cover_done(self):
        self.statusBar().showMessage(
            f"Portada puesta en {self.cov_ok} de {self.cov_total} canciones (en naranja). Revísalas y pulsa «Guardar».")
        if self.cov_fail:  # solo si no apareció ni una opción se ofrece Google Imágenes
            n = len(self.cov_fail)
            p = self.cov_fail[0]
            name = (self.val(p, "artist") + " - " if self.val(p, "artist") else "") + (
                self.val(p, "title") or os.path.splitext(os.path.basename(p))[0])
            extra = "" if n == 1 else f"\n\n(Faltan {n} álbumes; te abro el primero. Para los demás, usa clic derecho en la portada → «Buscar en Google Imágenes».)"
            q = QMessageBox.question(self, "Portada no encontrada",
                                     f"No encontré ninguna opción de portada para «{name}».\n\n¿Buscarla en Google Imágenes? "
                                     f"Copia la imagen que te guste (clic derecho → Copiar imagen) y el programa te ofrecerá ponerla.{extra}")
            if q == QMessageBox.StandardButton.Yes:
                self.google_cover(p)

    def google_cover(self, path=None):
        path = path or self.current_path()
        if not path:
            return
        artist = self.val(path, "artist")
        title = self.val(path, "title") or os.path.splitext(os.path.basename(path))[0]
        q = quote_plus(f"{artist} {title} portada".strip())
        QDesktopServices.openUrl(QUrl(f"https://www.google.com/search?tbm=isch&q={q}"))
        self._await_cover = path
        cb = QApplication.clipboard()
        try:
            cb.dataChanged.disconnect(self.on_clip_for_cover)
        except TypeError:
            pass
        cb.dataChanged.connect(self.on_clip_for_cover)
        self.statusBar().showMessage("En el navegador: abre la imagen, clic derecho → «Copiar imagen». Aquí te ofreceré ponerla.")

    def on_clip_for_cover(self):
        path = getattr(self, "_await_cover", None)
        cb = QApplication.clipboard()
        img = cb.image()
        if not path or img.isNull() or min(img.width(), img.height()) < 100:
            return
        self._await_cover = None
        try:
            cb.dataChanged.disconnect(self.on_clip_for_cover)
        except TypeError:
            pass
        q = QMessageBox.question(self, "Poner portada", f"Copiaste una imagen de {img.width()}×{img.height()} px.\n\n"
                                 f"¿Ponerla como portada de «{os.path.basename(path)}»?")
        if q != QMessageBox.StandardButton.Yes:
            return
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG" if img.hasAlphaChannel() else "JPG", 92)
        data = prepare_cover(bytes(ba), self.cover_side())
        if data is None:
            return
        self.apply_form()
        self.pending.setdefault(path, {})["_cover"] = data
        self.mark_items()
        if self.current_path() == path:
            self.show_current(path, len(self.cur_paths))
        self.statusBar().showMessage("Portada puesta (pendiente de guardar, en naranja).")

    def apply_cover_bytes(self, paths, data):
        """Pone esta portada (ya preparada) en las canciones indicadas, pendiente de guardar."""
        self.apply_form()
        for p in paths:
            self.pending.setdefault(p, {})["_cover"] = data
        self.mark_items()
        cur = self.current_path()
        if cur in paths:
            self.show_current(cur, len(self.cur_paths))
        self.statusBar().showMessage("Portada puesta (pendiente de guardar, en naranja).")

    def open_upscale(self):
        import upscale
        p = self.current_path()
        data = self.cover_data_of(p) if p else None
        if not data:
            QMessageBox.information(self, "Mejorar calidad con IA", "Esta canción no tiene portada.")
            return
        dlg = upscale.UpscaleDialog(self, self.cur_paths or [p], data)
        i18n.retranslate(dlg)
        dlg.show()
        self._upscale = dlg

    def remove_cover(self):
        if not self.cur_paths:
            return
        self.apply_form()
        for p in self.cur_paths:
            self.pending.setdefault(p, {})["_cover"] = b""
        self.mark_items()
        self.show_current(self.current_path(), len(self.cur_paths))

    def save_all(self):
        self.apply_form()
        if not self.pending:
            self.statusBar().showMessage("No hay cambios pendientes.")
            return
        self.release_if(list(self.pending))
        errors, ok, skipped = [], 0, set()
        saved_paths = []
        save_lrc = bool(int(self.cfg.value("save_lrc_v2", 0) or 0))

        def write_one(item):
            path, ch = item
            sk = set()
            easy = {k: v for k, v in ch.items() if k in EASY_KEYS or k in MB_KEYS}
            if easy:
                sk |= set(write_tags(path, easy))
            if "lyrics" in ch or "_cover" in ch:
                write_extra(path, ch.get("lyrics"), ch.get("_cover"))
            if ch.get("lyrics") and is_lrc(ch["lyrics"]) and save_lrc:
                try:  # archivo .lrc junto a la canción: lo leen casi todos los reproductores
                    with open(os.path.splitext(path)[0] + ".lrc", "w", encoding="utf-8") as fh:
                        fh.write(ch["lyrics"])
                except OSError:
                    pass
            return sk

        todo = list(self.pending.items())
        if len(todo) >= 6:   # muchos archivos: en segundo plano, con barra de progreso (la ventana no se congela)
            try:
                self.thumbs.request(self.gen, [])
            except Exception:
                note_quiet()
            results = self.run_batch(f"Guardando {len(todo)} archivos…", todo, write_one)
        else:
            results = []
            for item in todo:
                try:
                    results.append((item, write_one(item), None))
                except Exception as e:
                    results.append((item, None, e))
        for (path, ch), sk, err in results:
            try:
                if err is not None:
                    raise err
                skipped |= sk or set()
                ok += 1
                saved_paths.append(path)
                del self.pending[path]
                self.meta.pop(path, None)
                self.tags_cache.pop(path, None)
                TECH_MEM.pop(path, None)
                self.suggestions.pop(path, None)
                self.chosen.discard(path)
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        saved_with_cover = [p for p in saved_paths if os.path.exists(p)]
        self.offer_m4a_rename(saved_with_cover)
        self.refresh_shell([p for p in saved_paths])
        self.load_folder(self.current_dir)
        msg = f"{ok} archivo(s) guardado(s)."
        if skipped:
            msg += f" Campos no soportados por algún formato: {', '.join(sorted(skipped))}."
        self.statusBar().showMessage(msg)
        if ok:
            try:
                import navidrome
                navidrome.scan_in_background(self)   # si está activado: Navidrome relee la biblioteca
            except Exception:
                note_quiet()
        if errors:
            QMessageBox.warning(self, "Errores al guardar", "\n".join(errors))

    def refresh_shell(self, paths):
        """Avisa al Explorador de Windows de que los archivos cambiaron (así refresca icono y portada)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            sh = ctypes.windll.shell32
            for p in paths:
                sh.SHChangeNotify(0x00002000, 0x0005 | 0x1000, ctypes.c_wchar_p(os.path.normpath(p)), None)   # UPDATEITEM
            if paths:
                d = os.path.normpath(os.path.dirname(paths[0]))
                sh.SHChangeNotify(0x00001000, 0x0005 | 0x1000, ctypes.c_wchar_p(d), None)                       # UPDATEDIR
        except Exception:
            note_quiet()

    def offer_m4a_rename(self, paths):
        """Windows no saca la portada de los .mp4: renombrarlos a .m4a (mismo archivo) hace que sí la muestre."""
        mp4 = [p for p in paths if p.lower().endswith(".mp4") and inspect_file(p).get("cover")]
        if not mp4:
            return
        ans = QMessageBox.question(
            self, "Portada en el Explorador",
            f"{len(mp4)} archivo(s) son .mp4 y Windows no muestra la portada de esos.\n\n"
            "¿Renombrarlos a .m4a? Es el mismo archivo (mismo audio); solo cambia la extensión y así el "
            "Explorador sí enseña la imagen.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        mapping = {}
        for p in mp4:
            new = os.path.splitext(p)[0] + ".m4a"
            if os.path.exists(new):
                continue
            try:
                self.release_if([p])
                os.rename(p, new)
                mapping[p] = new
            except OSError:
                pass
        if not mapping:
            return
        for lst in list(self.pl_lists.values()) + [self.playlist]:   # en el sitio, para no romper la lista activa
            lst[:] = [mapping.get(x, x) for x in lst]
        if self.playing_path in mapping:
            self.playing_path = mapping[self.playing_path]
        for old in mapping:
            self.meta.pop(old, None)
            self.tags_cache.pop(old, None)
            TECH_MEM.pop(old, None)
        self.refresh_shell(list(mapping.values()))

    # -------------------------------------------------------------- IA
    def on_provider(self, name):
        models = {"Claude": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
                  "ChatGPT": ["gpt-4o-mini", "gpt-4o"],
                  "Gemini": ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite"]}[name]
        self.model_cb.clear()
        self.model_cb.addItems(models)
        saved = self.cfg.value(f"model_{name}", models[0])
        if saved in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"):
            saved = models[0]  # modelos antiguos que Google ya no da a usuarios nuevos
        self.model_cb.setCurrentText(saved)
        self.key_le.setText(secret.get(self.cfg, f"key_{name}"))

    def run_ai(self):
        prov = self.provider.currentText()
        key, model = self.key_le.text().strip(), self.model_cb.currentText().strip()
        if not key:
            self.no_key_help(prov)
            return
        self.cfg.setValue("provider", prov)
        secret.put(self.cfg, f"key_{prov}", key)
        self.cfg.setValue(f"model_{prov}", model)
        paths = self.selected_paths() or [self.list.item(r).data(PATH_ROLE) for r in range(self.list.count())
                                          if self.list.item(r).data(KIND_ROLE) != "dir"]
        if not paths:
            return
        self.ai_rows = paths
        items = []
        for i, p in enumerate(paths):
            t = self.tags_of(p)
            items.append({"id": str(i), "artista": t["artist"], "titulo": t["title"],
                          "album": t["album"], "archivo": os.path.basename(p)})
        self.btn_ai.setEnabled(False)
        self.statusBar().showMessage(f"Consultando a {prov}…")
        self.worker = AIWorker(prov, model, key, items)
        self.worker.done.connect(self.ai_done)
        self.worker.failed.connect(self.ai_failed)
        self.worker.start()

    def ai_done(self, result):
        n = 0
        for i, val in result.items():
            try:
                path = self.ai_rows[int(i)]
            except (ValueError, IndexError):
                continue
            opts = make_options(val)
            if opts:
                self.suggestions[path] = opts
                self.chosen.discard(path)
                n += 1
        self.btn_ai.setEnabled(True)
        cur = self.current_path()
        if n and cur not in self.suggestions and len(self.cur_paths) <= 1:  # salta a la primera canción con opciones
            for r in range(self.list.count()):
                if self.list.item(r).data(PATH_ROLE) in self.suggestions:
                    self.go_to_row(r)
                    break
        self.update_suggestions()
        if len(self.cur_paths) > 1:
            self.statusBar().showMessage(T(f"La IA dio opciones para {n} canciones. Pulsa un género para ponerlo a todas las seleccionadas."))
        else:
            self.statusBar().showMessage(f"La IA dio opciones para {n} canciones. Elige el subgénero en el cuadro de la derecha.")

    def ai_failed(self, msg):
        self.btn_ai.setEnabled(True)
        self.statusBar().showMessage("Falló la consulta a la IA.")
        QMessageBox.warning(self, "Error de IA", msg)

    def no_key_help(self, prov=""):
        """Explica cómo conseguir gratis una clave de Gemini y abre los ajustes para pegarla."""
        box = QMessageBox(self)
        box.setWindowTitle("Falta la clave de la IA")
        box.setIconPixmap(self.logo_pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(i18n_more.NOKEY_ES)
        get = box.addButton("🔑 Conseguir clave gratis de Gemini", QMessageBox.ButtonRole.ActionRole)
        paste = box.addButton("⚙ Pegar la clave (Gemini)", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Close)
        while True:
            box.exec()
            b = box.clickedButton()
            if b is get:
                QDesktopServices.openUrl(QUrl("https://aistudio.google.com/apikey"))
                continue   # deja la ventana abierta para seguir los pasos
            break
        if b is paste:
            self.provider.setCurrentText("Gemini")
            self.on_provider("Gemini")
            self.open_settings(0)

    def ai_settings(self):
        prov = self.provider.currentText()
        key, model = self.key_le.text().strip(), self.model_cb.currentText().strip()
        if not key:
            self.no_key_help(prov)
            return None
        self.cfg.setValue("provider", prov)
        secret.put(self.cfg, f"key_{prov}", key)
        self.cfg.setValue(f"model_{prov}", model)
        return prov, model, key

    def run_lyrics(self, paths=None):
        paths = list(paths or self.cur_paths)
        if not paths:
            QMessageBox.information(self, "LRCLIB", "Selecciona una o varias canciones primero.")
            return
        self.apply_form()
        todo, skipped = [], 0
        for p in paths:
            pend = self.pending.get(p, {})
            existing = pend["lyrics"] if "lyrics" in pend else inspect_file(p)["lyrics"]
            if existing.strip():
                skipped += 1
            else:
                todo.append(p)
        if not todo and len(paths) == 1:
            q = QMessageBox.question(self, "Ya tiene letra", "Esta canción ya tiene letra. ¿Reemplazarla con la de LRCLIB?")
            if q == QMessageBox.StandardButton.Yes:
                todo = paths
        if not todo:
            self.statusBar().showMessage("Todas las canciones seleccionadas ya tienen letra.")
            return

        def secs(p):
            try:
                m, s_ = tech_info(p)["dur"].split(":")
                return int(m) * 60 + int(s_)
            except Exception:
                return 0
        jobs = [(p, self.val(p, "artist"), self.val(p, "title") or os.path.splitext(os.path.basename(p))[0],
                 self.val(p, "album"), secs(p)) for p in todo]
        self.lyr_ok, self.lyr_total = 0, len(jobs)
        self.btn_lyr.setEnabled(False)
        extra = f" ({skipped} ya tenían letra y se omiten)" if skipped else ""
        self.statusBar().showMessage(f"Buscando {len(jobs)} letra(s) en LRCLIB…{extra}")
        self.lyr_worker = LrclibWorker(jobs, bool(int(self.cfg.value("prefer_synced", 1) or 0)))
        self.lyr_worker.got.connect(self.lyrics_got)
        self.lyr_worker.finished_all.connect(self.lyrics_done)
        self.lyr_worker.failed.connect(self.lyrics_failed)
        self.lyr_worker.start()

    def lyrics_got(self, path, text):
        if not text:
            return
        self.pending.setdefault(path, {})["lyrics"] = text
        self.lyr_ok += 1
        self.mark_items()
        if len(self.cur_paths) == 1 and self.current_path() == path:
            self.show_current(path, 1)

    def lyrics_done(self):
        self.btn_lyr.setEnabled(True)
        w = self.lyr_worker
        src = ", ".join(f"{k}: {v}" for k, v in w.sources.items())
        msg = T(f"Letra puesta en {self.lyr_ok} de {self.lyr_total} canciones (en naranja). Revísalas y pulsa «Guardar».")
        if src:
            msg += f"  ({src})"
        if w.errored:
            msg += " " + T(f"{len(w.errored)} no se pudieron consultar (sin conexión).")
        self.statusBar().showMessage(msg)
        if self.lyr_total == 1 and self.lyr_ok == 0:   # una sola canción y no apareció: ofrece otras opciones
            self.lyrics_options(w.jobs[0][0], T("Ningún servicio (LRCLIB, NetEase, lyrics.ovh) tiene la letra de esta canción."))
        elif w.errored:
            self.lyrics_options(None, T(f"{len(w.errored)} canción(es) no se pudieron consultar por problemas de conexión."),
                                retry=w.errored)

    def lyrics_failed(self, msg):
        self.btn_lyr.setEnabled(True)
        self.statusBar().showMessage(T("Falló la consulta de letras."))
        w = self.lyr_worker
        self.lyrics_options(w.jobs[0][0] if len(w.jobs) == 1 else None,
                            T("No se pudo conectar con los servicios de letras.") + "\n\n" + msg,
                            retry=[j[0] for j in w.jobs])

    def lyrics_options(self, path, msg, retry=None):
        """Si la letra no aparece (o falla la conexión): reintentar, buscarla en Google, cargar un .lrc o escribirla."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(T("Letra"))
        box.setText(msg)
        box.setInformativeText(T("¿Qué quieres hacer?"))
        b_retry = box.addButton(T("Reintentar"), QMessageBox.ButtonRole.AcceptRole) if retry else None
        b_web = b_lrc = b_hand = b_musica = None
        if path:
            b_musica = box.addButton(T("Buscar en musica.com"), QMessageBox.ButtonRole.ActionRole)
            b_web = box.addButton(T("Buscar en Google"), QMessageBox.ButtonRole.ActionRole)
            b_lrc = box.addButton(T("Cargar archivo .lrc…"), QMessageBox.ButtonRole.ActionRole)
            b_hand = box.addButton(T("Escribirla / pegarla"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(T("Cerrar"), QMessageBox.ButtonRole.RejectRole)
        i18n.retranslate(box)
        box.exec()
        c = box.clickedButton()
        if c is None:
            return
        if c is b_retry:
            self.run_lyrics([p for p in retry if p])
        elif c is b_musica:
            self.lyrics_web("musica", path)
        elif c is b_web:
            q = f"{self.val(path, 'artist')} {self.val(path, 'title') or os.path.splitext(os.path.basename(path))[0]} lrc letra"
            QDesktopServices.openUrl(QUrl("https://www.google.com/search?q=" + urllib.parse.quote(q.strip())))
        elif c is b_lrc:
            self.load_lrc_file(path)
        elif c is b_hand:
            self.show_right_tab(1)
            self.lyrics.setFocus()

    def lyrics_web(self, site, path=None):
        """Busca la letra de la canción en una web de letras (se abre en el navegador)."""
        path = path or self.current_path()
        if not path:
            self.statusBar().showMessage(T("Selecciona una canción primero."))
            return
        artist = _main_artist(self.val(path, "artist"))
        title = _clean_title(self.val(path, "title") or os.path.splitext(os.path.basename(path))[0])
        q = f"site:musica.com {artist} {title} letra" if site == "musica" else f"{artist} {title} lrc letra"
        QDesktopServices.openUrl(QUrl("https://www.google.com/search?q=" + urllib.parse.quote(q.strip())))
        self.statusBar().showMessage(T("Copia la letra en el navegador y pulsa «📋 Pegar letra»."))

    def paste_lyrics(self):
        path = self.current_path()
        if not path or len(self.cur_paths) != 1:
            self.statusBar().showMessage(T("Selecciona una sola canción para pegarle la letra."))
            return
        text = QApplication.clipboard().text() or ""
        lines = [l.rstrip() for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
        out, blank = [], False
        for l in lines:   # quita líneas vacías repetidas (deja una entre estrofas)
            if not l.strip():
                if out and not blank:
                    out.append("")
                blank = True
                continue
            blank = False
            out.append(l.strip())
        text = "\n".join(out).strip()
        if len(text) < 10:
            QMessageBox.information(self, T("Letra"), T("No hay ninguna letra copiada. Selecciona la letra en el navegador, cópiala (Ctrl+C) y vuelve a pulsar «Pegar letra»."))
            return
        self.pending.setdefault(path, {})["lyrics"] = text
        self.mark_items()
        self.show_current(path, 1)
        self.show_right_tab(1)
        self.update_dirty()
        self.statusBar().showMessage(T("Letra pegada (pendiente de guardar)."))

    def load_lrc_file(self, path):
        fn, _ = QFileDialog.getOpenFileName(self, T("Cargar letra"), os.path.dirname(path),
                                            T("Letras") + " (*.lrc *.txt);;" + T("Todos") + " (*.*)")
        if not fn:
            return
        text = ""
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                with open(fn, "r", encoding=enc) as fh:
                    text = fh.read()
                break
            except (UnicodeDecodeError, OSError):
                continue
        if not text.strip():
            QMessageBox.warning(self, T("Letra"), T("El archivo está vacío o no se pudo leer."))
            return
        self.pending.setdefault(path, {})["lyrics"] = text.strip()
        self.mark_items()
        if self.current_path() == path:
            self.show_current(path, len(self.cur_paths))
        self.show_right_tab(1)
        self.statusBar().showMessage(T("Letra cargada (pendiente de guardar)."))

    def open_meta_ai(self):
        path = self.current_path()
        if not path:
            QMessageBox.information(self, "Rellenar con IA", "Selecciona una canción primero.")
            return
        settings = self.ai_settings()
        if not settings:
            return
        self.meta_ai_dlg = MetaAIDialog(self, path, settings)
        self.meta_ai_dlg.show()

    def apply_ai_meta(self, path, vals):
        self.apply_form()
        for k, v in vals.items():
            if k in EASY_KEYS:
                self.pending.setdefault(path, {})[k] = v
        self.mark_items()
        if path in self.cur_paths:
            self.on_select()
        self.statusBar().showMessage(f"{len(vals)} dato(s) rellenados con IA (pendientes de guardar).")

    def open_chat(self):
        path = self.current_path()
        if not path:
            QMessageBox.information(self, "Hablar con la IA", "Selecciona una canción primero.")
            return
        settings = self.ai_settings()
        if not settings:
            return
        self.chat_dlg = GenreChat(self, path, settings)
        self.chat_dlg.show()

    def apply_genre(self, path, text):
        if not text:
            return
        self.apply_form()
        self.pending.setdefault(path, {})["genre"] = text
        self.chosen.add(path)
        self.mark_items()
        if path in self.cur_paths:
            self.on_select()
        self.statusBar().showMessage(f"Género «{text}» puesto (pendiente de guardar).")

    def resize_covers(self, side):
        """Cuadradas (1000×1000, 600×600…): se reducen solas. Las que no son cuadradas (700×1200…): se abre una
        ventanita para elegir qué parte recortar en cuadrado."""
        if not self.cur_paths:
            QMessageBox.information(self, "Redimensionar", "Selecciona una o varias canciones.")
            return
        import covercrop
        self.apply_form()
        done, skipped, last, odd = 0, 0, "", []
        for p in self.cur_paths:
            pend = self.pending.get(p, {})
            data = pend["_cover"] if "_cover" in pend else inspect_file(p)["cover"]
            if not data:
                skipped += 1
                continue
            w, h = cover_dims(data)
            if not covercrop.is_square(w, h):
                odd.append((p, data))   # no es cuadrada: se recorta después, eligiendo la parte
                continue
            new = prepare_cover(data, side)
            if new is None or new == data:  # sin portada válida o ya es más pequeña
                skipped += 1
                continue
            a = cover_dims(new)
            last = f"{w}×{h} → {a[0]}×{a[1]} px"
            self.pending.setdefault(p, {})["_cover"] = new
            done += 1
        cropped, auto_side = 0, None
        for i, (p, data) in enumerate(odd):
            if auto_side:   # «recortar centradas las demás»
                img = QImage.fromData(data)
                x, y, s_ = covercrop.centered_square(img.width(), img.height())
                self.pending.setdefault(p, {})["_cover"] = covercrop.crop_square(img, x, y, s_, auto_side)
                cropped += 1
                continue
            dlg = covercrop.CropDialog(self, data, side, os.path.basename(p), len(odd) - i - 1)
            i18n.retranslate(dlg)
            dlg.exec()
            if dlg.cancel_all:
                break
            if dlg.result_bytes:
                self.pending.setdefault(p, {})["_cover"] = dlg.result_bytes
                cropped += 1
                if dlg.apply_all:
                    auto_side = dlg.side()
            else:
                skipped += 1
        self.mark_items()
        self.show_current(self.current_path(), len(self.cur_paths))
        msg = f"{done} portada(s) redimensionada(s) a máx. {side} px"
        if done == 1:
            msg += f" ({last})"
        if cropped:
            msg += f" · {cropped} recortada(s) en cuadrado"
        msg += " (pendiente de guardar)"
        if skipped:
            msg += f". {skipped} sin cambios (sin portada, ya eran más pequeñas o las saltaste)"
        self.statusBar().showMessage(msg + ".")

    def toggle_orient(self):
        if getattr(self, "tree_drawer", None):
            QTimer.singleShot(0, self.tree_drawer.place)
        horiz = self.left_split.orientation() == Qt.Orientation.Vertical
        self.left_split.setOrientation(Qt.Orientation.Horizontal if horiz else Qt.Orientation.Vertical)
        self.cfg.setValue("trees_h", 1 if horiz else 0)
        self.act_orient.setText("⇅ Árboles apilados" if horiz else "⇄ Árboles lado a lado")
        i18n.deco(self.act_orient)
        sizes = self.main_split.sizes()
        left = 620 if (horiz and self.tree2_box.isVisible()) else 290
        self.main_split.setSizes([left, max(300, sum(sizes) - left)])

    # ------------------------------------------- Copiar / cortar / pegar / eliminar
    def selection_paths(self):
        """Lo que está seleccionado en el panel que tiene el foco (árbol o lista)."""
        fw = QApplication.focusWidget()
        if fw is self.tree or fw is self.tree2:
            return fw.selected_dirs()
        return self.selected_all_paths() or self.active_tree.selected_dirs()

    def clip_set(self, mode):
        paths = self.selection_paths()
        if mode == "cut":
            paths = [p for p in paths if not (os.path.isdir(p) and self.is_protected(p))]
        if not paths:
            self.statusBar().showMessage("No hay nada seleccionado (o es una carpeta principal que no se puede cortar).")
            return
        self.clip = {"mode": mode, "paths": paths}
        self.set_cut_marks(paths if mode == "cut" else [])
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        QApplication.clipboard().setMimeData(md)
        self.statusBar().showMessage(
            f"{len(paths)} elemento(s) {'cortado(s)' if mode == 'cut' else 'copiado(s)'}. "
            "Elige la carpeta de destino y pega (Ctrl+V).")

    def set_cut_marks(self, paths):
        """Lo cortado se ve medio transparente hasta que se pega (o se copia/corta otra cosa)."""
        cut = set(paths or [])
        for w_ in (self.list, self.tree, self.tree2):
            w_.cut_paths = cut
            w_.viewport().update()
        if hasattr(self, "details") and getattr(self.details, "enabled", False):
            self.list.viewport().update()

    def paste_target(self):
        fw = QApplication.focusWidget()
        if fw is self.tree or fw is self.tree2:
            d = fw.selected_dirs()
            return d[0] if d else self.current_dir
        dirs = self.selected_dir_paths()
        return dirs[0] if len(dirs) == 1 else self.current_dir

    def paste_here(self):
        target = self.paste_target()
        if not target or not os.path.isdir(target):
            return
        md = QApplication.clipboard().mimeData()
        urls = [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md and md.hasUrls() else []
        mode, paths = "copy", urls
        if self.clip:
            if not urls or {norm(u) for u in urls} == {norm(p) for p in self.clip["paths"]}:
                mode, paths = self.clip["mode"], self.clip["paths"]
        if not paths:
            self.statusBar().showMessage("No hay nada que pegar. Copia o corta algo primero.")
            return
        if mode == "cut":
            self.move_items(paths, target)
            self.clip = None
            self.set_cut_marks([])
            QApplication.clipboard().clear()
        else:
            self.copy_items(paths, target)

    def copy_items(self, paths, target):
        target = os.path.normpath(target)
        done, errors = 0, []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for src in paths:
                src = os.path.normpath(src)
                if not os.path.exists(src):
                    continue
                name = os.path.basename(src)
                if os.path.isdir(src) and (target == src or target.startswith(src + os.sep)):
                    errors.append(f"No puedes copiar «{name}» dentro de sí misma.")
                    continue
                dst = os.path.join(target, name)
                if os.path.exists(dst):  # nunca sobrescribe: "nombre - copia", "nombre - copia (2)"…
                    root, ext = os.path.splitext(dst) if os.path.isfile(src) else (dst, "")
                    n, cand = 1, f"{root} - copia{ext}"
                    while os.path.exists(cand):
                        n += 1
                        cand = f"{root} - copia ({n}){ext}"
                    dst = cand
                try:
                    shutil.copytree(src, dst) if os.path.isdir(src) else shutil.copy2(src, dst)
                    done += 1
                except Exception as e:
                    errors.append(f"{name}: {e}")
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"{done} elemento(s) copiado(s) a {target}")
        if errors:
            QMessageBox.warning(self, "Algunos elementos no se copiaron", "\n".join(errors))
        self.after_fs_change()

    def delete_paths(self, paths):
        paths = [p for p in paths if not (os.path.isdir(p) and self.is_protected(p))]
        if not paths:
            return
        txt = "\n".join(os.path.basename(p) for p in paths[:10]) + ("\n…" if len(paths) > 10 else "")
        how = "a la papelera" if send2trash else "de forma PERMANENTE"
        ask = int(self.cfg.value("confirm_delete", 1) or 0) or not send2trash  # sin papelera siempre se pregunta
        if ask and QMessageBox.question(self, "Eliminar", f"¿Eliminar {how}?\n\n{txt}") != QMessageBox.StandardButton.Yes:
            return
        if getattr(self, "_deleting", None) is not None and self._deleting.isRunning():
            self.statusBar().showMessage(T("Espera: todavía se están eliminando los anteriores…"))
            return
        paths = [os.path.normpath(p) for p in paths]
        self.release_if(paths)
        self._watch_paused_until = time.monotonic() + 3600   # sin vigilar carpetas mientras se borra
        # se ocultan ya de la lista y los árboles (el borrado real sigue en segundo plano, sin trabar el programa)
        gone = {os.path.normcase(p) for p in paths}
        for r in range(self.list.count()):
            it = self.list.item(r)
            if os.path.normcase(os.path.normpath(it.data(PATH_ROLE) or "")) in gone:
                it.setHidden(True)
        for t in (self.tree, self.tree2):
            for it in t.all_items():
                pth = it.data(0, PATH_ROLE)
                if pth and os.path.normcase(os.path.normpath(pth)) in gone:
                    it.setHidden(True)
        self.statusBar().showMessage(T(f"Eliminando {len(paths)} elemento(s)…"))
        w = DeleteWorker(paths, send2trash)
        w.done.connect(lambda ok, errors, paths=paths: self.delete_done(paths, ok, errors))
        self._deleting = w
        w.start()

    def delete_done(self, paths, ok, errors):
        self._watch_paused_until = 0
        for p in paths:
            if not os.path.exists(p):
                for d in (self.pending, self.meta, self.tags_cache, self.suggestions):
                    d.pop(p, None)
                self.chosen.discard(p)
        self.after_fs_change()
        self.update_watch()
        self.statusBar().showMessage(T(f"{ok} elemento(s) eliminado(s).") if not errors else
                                     T(f"{ok} eliminado(s), {len(errors)} con error."))
        if errors:
            QMessageBox.warning(self, T("Eliminar"), "\n".join(errors[:15]))

    def delete_selected(self):
        self.delete_paths(self.active_tree.selected_dirs())

    def defer_move(self, paths, target):
        """Mueve (o copia, con Ctrl) cuando termina el arrastre, para no recargar la lista en pleno arrastre."""
        copy = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier)
        if copy:
            QTimer.singleShot(0, lambda: self.copy_items(paths, target))
        else:
            QTimer.singleShot(0, lambda: self.move_items(paths, target))

    def open_dir(self, path):
        if not self.active_tree.reveal(path):
            self.load_folder(path)

    def on_list_double(self, item):
        if item.data(KIND_ROLE) == "dir":
            self.open_dir(item.data(PATH_ROLE))
        else:
            self.play_item(item)

    def play_current(self):
        it = self.list.currentItem()
        if it is not None:
            self.on_list_double(it)

    def selected_all_paths(self):
        return [i.data(PATH_ROLE) for i in self.list.selectedItems()]

    def selected_dir_paths(self):
        return [i.data(PATH_ROLE) for i in self.list.selectedItems() if i.data(KIND_ROLE) == "dir"]

    # ------------------------------------------------------ Menús contextuales
    def tree_menu(self, tree, pos):
        tree.setFocus()
        it = tree.itemAt(pos)
        if it is not None and not it.isSelected():
            tree.setCurrentItem(it)
        self.active_tree = tree
        m = TMenu(self)
        if it is not None:
            p = it.data(0, PATH_ROLE)
            m.addAction("📂 Abrir en el Explorador", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
            if p and os.path.isdir(p):
                m.addAction("▶ Reproducir carpeta", lambda: self.play_folder(p))
                m.addAction("➕ Añadir carpeta a la lista", lambda: self.pl_add([p]))
            m.addSeparator()
            m.addAction("✂️ Cortar", lambda: self.clip_set("cut"))
            m.addAction("📋 Copiar", lambda: self.clip_set("copy"))
        m.addAction("📥 Pegar aquí", self.paste_here)
        m.addAction("➕ Nueva carpeta aquí", lambda: self.new_folder())
        if it is not None and it.data(0, PATH_ROLE) and os.path.isdir(it.data(0, PATH_ROLE)):
            m.addAction("🏷 Géneros en lote de esta carpeta…", lambda d=it.data(0, PATH_ROLE): self.open_batch_genres(folder=d))
        other = self.tree2 if tree is self.tree else self.tree
        oc = other.currentItem()
        if it is not None and self.tree2_box.isVisible() and oc is not None and oc.data(0, PATH_ROLE):
            srcs, dst = tree.selected_dirs(), oc.data(0, PATH_ROLE)
            m.addSeparator()
            m.addAction(f"➡ Mover al otro árbol  ({oc.text(0)})", lambda: self.move_items(srcs, dst))
            m.addAction(f"⧉ Copiar al otro árbol  ({oc.text(0)})", lambda: self.copy_items(srcs, dst))
        if it is not None:
            if it.data(0, KIND_ROLE) == "pinned":
                m.addSeparator()
                m.addAction("📌 Quitar de la lista", lambda: self.unpin(p))
            elif it.data(0, KIND_ROLE) is None:
                m.addSeparator()
                m.addAction("✏️ Renombrar (F2)", lambda: self.rename_folder(p, tree))
                m.addAction("🗑 Eliminar", self.delete_selected)
        m.exec(tree.viewport().mapToGlobal(pos))

    def list_menu(self, pos):
        """Menú contextual ordenado: lo de siempre arriba, lo demás agrupado en submenús."""
        self.list.setFocus()
        it = self.list.itemAt(pos)
        if it is not None and not it.isSelected():
            self.list.clearSelection()
            it.setSelected(True)
        m = TMenu(self)
        if it is not None and it.data(KIND_ROLE) == "dir":
            d = it.data(PATH_ROLE)
            m.addAction("📂 Abrir carpeta", lambda: self.open_dir(d))
            m.addAction("▶ Reproducir carpeta", lambda: self.play_folder(d))
            m.addAction("➕ Añadir carpeta a la lista", lambda: self.pl_add([d]))
            m.addSeparator()
            m.addAction("✂️ Cortar (Ctrl+X)", lambda: self.clip_set("cut"))
            m.addAction("📋 Copiar (Ctrl+C)", lambda: self.clip_set("copy"))
            m.addAction("✏️ Renombrar (F2)", lambda: self.rename_folder(d))
            m.addAction("🗑 Eliminar (Supr)", lambda: self.delete_paths(self.selected_all_paths()))
            m.addSeparator()
            m.addAction("🏷 Géneros en lote de esta carpeta…", lambda: self.open_batch_genres(folder=d))
        elif it is not None:
            p = it.data(PATH_ROLE)
            n = len(self.selected_paths())
            m.addAction("▶ Reproducir", lambda: self.play_item(it))
            m.addAction("➕ Añadir a la lista de reproducción", lambda: self.pl_add(self.selected_paths()))
            m.addSeparator()
            m.addAction("✂️ Cortar (Ctrl+X)", lambda: self.clip_set("cut"))
            m.addAction("📋 Copiar (Ctrl+C)", lambda: self.clip_set("copy"))
            m.addAction("📥 Pegar aquí (Ctrl+V)", self.paste_here)
            sel1 = self.selected_paths()
            if len(sel1) == 1:   # útil sobre todo al buscar o con «Incluir subcarpetas»
                m.addAction(T("📂 Ir a la carpeta"), lambda p=sel1[0]: self.go_to_folder(p))
                m.addAction(T("🗂 Mostrar en el Explorador de Windows"), lambda p=sel1[0]: self.show_in_explorer(p))
                m.addSeparator()
            m.addAction("✏️ Renombrar (F2)", self.rename_selected)
            m.addAction(T("🧹 Quitar paréntesis del nombre…"), lambda: self.open_strip_parens(self.selected_paths()))
            m.addSeparator()
            a_cm = m.addAction(T("📋 Copiar metadatos") + "\tCtrl+Shift+C", self.copy_meta)
            a_cm.setEnabled(len(self.selected_paths()) == 1)
            a_pm = m.addAction(T("📥 Pegar metadatos…") + "\tCtrl+Shift+V", self.paste_meta)
            a_pm.setEnabled(bool(getattr(self, "meta_clip", None)))
            m.addAction("🗑 Eliminar (Supr)", lambda: self.delete_paths(self.selected_all_paths()))
            m.addSeparator()
            tools = m.addMenu(icons.vicon("tools", ctx="menu"), T("Herramientas"))
            for text, fn in (("📊 Espectrograma / calidad" + (" (comparar)" if n > 1 else ""), self.open_spectrum),
                             ("🎚 Ajustes de la canción…", self.open_fx),
                             ("🔄 Convertir formato…", self.convert_selected),
                             ("🏷 Géneros en lote…", self.open_batch_genres),
                             ("📁 Crear carpetas por… (intérprete, álbum, género…)", self.open_folders_by),
                             ("🎧 Identificar por sonido (AcoustID)…", self.open_acoustid),
                             ("💿 Emparejar álbum con MusicBrainz…", self.open_album_match),
                             ("▶️ Buscar en YouTube", lambda: self.open_youtube(p))):
                tools.addAction(T(text), fn)
            artist = self.val(p, "artist")
            if artist:
                am = m.addMenu(icons.vicon("person", ctx="menu"), artist if len(artist) < 40 else artist[:38] + "…")
                for text, kind in (("📖 Historia del artista (Wikipedia)", "wiki"), ("▶️ Buscar artista en YouTube", "youtube"),
                                   ("🟢 Buscar artista en Spotify", "spotify"), ("🌊 Buscar artista en Tidal", "tidal"),
                                   ("🎧 Buscar artista en Qobuz", "qobuz")):
                    am.addAction(T(text), lambda _=False, k=kind: self.web_artist(k, artist))
            if self.tree2_box.isVisible():
                _s, dst, _w = self.xfer_plan()
                if dst:
                    dn = os.path.basename(dst.rstrip(os.sep)) or dst
                    om = m.addMenu(icons.vicon("swap", ctx="menu"), T(f"Al otro árbol ({dn})"))
                    om.addAction(T("➡ Enviar (mover)"), lambda: self.xfer(True))
                    om.addAction(T("📋 Copiar"), lambda: self.xfer(False))
        else:
            m.addAction("📥 Pegar aquí (Ctrl+V)", self.paste_here)
            m.addAction("➕ Nueva carpeta aquí", lambda: self.new_folder(self.current_dir))
        m.addSeparator()
        self.add_view_menus(m)
        m.addAction("⟳ Actualizar (F5)", self.refresh_dir)
        m.addAction("📂 Mostrar carpeta en el Explorador",
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_dir)))
        m.exec(self.list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------- Apariencia / paneles
    def toggle_theme(self):
        self.set_theme("light" if self.theme == "dark" else "dark")

    def set_theme(self, name):
        self.theme = name
        self.cfg.setValue("theme", name)
        apply_theme(QApplication.instance(), name, self.accent or None)
        self.retint()

    def set_accent(self, color):
        self.accent = color or ""
        self.cfg.setValue("accent", self.accent)
        apply_theme(QApplication.instance(), self.theme, self.accent or None)
        self.retint()

    def retint(self):
        self._cur_tint = self.accent or None
        p = self.playing_path
        if p and self.player is not None and self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._cur_tint = "x"
            self.apply_cover_colors(self.cover_data_of(p))

    def show_right_tab(self, i):
        self.act_lyr.blockSignals(True)
        self.act_lyr.setChecked(i == 1)
        self.act_lyr.blockSignals(False)
        self.toggle_lyr(i == 1)

    def toggle_lyr(self, on):
        self.right_stack.setCurrentIndex(1 if on else 0)
        self.btn_tab_gen.setChecked(not on)
        self.btn_tab_lyr.setChecked(on)
        self.cfg.setValue("show_lyr", 1 if on else 0)

    def search_hay(self, f):
        tags = self.tags_cache.get(f) or {}
        return (os.path.splitext(os.path.basename(f))[0] + " " +
                " ".join(v for v in tags.values() if isinstance(v, str))).lower()

    def fill_list(self):
        """Llena la lista con las canciones de la carpeta (solo las que coinciden si hay una búsqueda)."""
        t = getattr(self, "_filter_t", "")
        files = self._all_files
        if t:
            files = [f for f in files if t in self.search_hay(f)]
        self.list.setUpdatesEnabled(False)   # se llena de una vez y se pinta al final (no canción por canción)
        self.list.clear()
        if not t:
            for name, dp in self._all_dirs:
                di = QListWidgetItem(self.folder_icon, name)
                di.setData(PATH_ROLE, dp)
                di.setData(KIND_ROLE, "dir")
                di.setToolTip(dp)
                self.list.addItem(di)
        for f in files:
            it = QListWidgetItem(os.path.splitext(os.path.basename(f))[0])
            it.setData(PATH_ROLE, f)
            it.setToolTip(f)
            m = self.meta.get(f)
            it.setIcon(m["icon"] if m and m["icon"] else self.default_icon)
            self.list.addItem(it)
        self.row_index = {self.list.item(r).data(PATH_ROLE): r for r in range(self.list.count())}
        self.list.setUpdatesEnabled(True)
        return files

    def apply_filter(self, text=""):
        t = (text or "").strip().lower()
        if getattr(self, "_all_files", None) is None:
            return
        if t != getattr(self, "_filter_t", ""):
            sel = set(self.selected_paths())
            cur = self.list.currentItem()
            cur_p = cur.data(PATH_ROLE) if cur is not None else None
            self._filter_t = t
            self._loading_dir = True
            self.list.blockSignals(True)
            try:
                found = self.fill_list()
                for p in sel:   # lo que estaba seleccionado y sigue en la lista, sigue seleccionado
                    r = self.row_index.get(p)
                    if r is not None:
                        self.list.item(r).setSelected(True)
                if cur_p in self.row_index:
                    self.list.setCurrentItem(self.list.item(self.row_index[cur_p]),
                                             QItemSelectionModel.SelectionFlag.NoUpdate)
            finally:
                self.list.blockSignals(False)
                self._loading_dir = False
            self.mark_items()
            self.list.verticalScrollBar().setValue(0)
            missing = [p for p in found if self.meta.get(p) is None] if t else []
            if missing:   # primero las miniaturas de lo encontrado
                ms = set(missing)
                rest = [p for p in getattr(self, "thumb_queue", []) if self.meta.get(p) is None and p not in ms]
                try:
                    self.thumbs.request(self.gen, missing + rest)
                except Exception:
                    note_quiet()
        self._filtered = bool(t)
        if t:
            shown = sum(1 for r in range(self.list.count()) if self.list.item(r).data(KIND_ROLE) != "dir")
            total = len(self._all_files)
            self.filter_lbl.setText("🔍  " + T(f"Mostrando {shown} de {total} canciones · búsqueda «{text.strip()}»"))
            self.filter_bar.show()
            self.list.overlay.setText(T(f"Ninguna canción de esta carpeta coincide con «{text.strip()}».") if not shown else "")
            self.list.overlay.setGeometry(self.list.viewport().rect())
            self.list.overlay.setVisible(shown == 0)
        else:
            self.filter_bar.hide()
            self.list.overlay.setText("Aquí no hay música todavía.\n\nElige otra carpeta a la izquierda o pega archivos con Ctrl+V.")
            self.list.overlay.setVisible(self.list.count() == 0)

    def set_rows_locked(self, locked):
        """Con los metadatos a la vista, la división entre la fila de arriba y la de abajo no se estira (se ve mejor);
        solo se puede mover cuando está el espectrograma."""
        for sp in (self.top_split, self.bottom_split):   # la división de las columnas nunca se mueve
            hh = sp.handle(1)
            if hh is not None:
                hh.setEnabled(False)
                hh.setCursor(Qt.CursorShape.ArrowCursor)
        h = self.mid_split.handle(1)
        if h is not None:
            h.setEnabled(not locked)
            h.setCursor(Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SplitVCursor)
        if locked:   # la fila de abajo mide siempre lo mismo: al volver de espectrograma queda exactamente en el mismo sitio
            hgt = self.bottom_row_h()
            self.bottom_stack.setFixedHeight(hgt)
        else:
            self.bottom_stack.setMinimumHeight(0)
            self.bottom_stack.setMaximumHeight(16777215)

    def bottom_row_h(self):
        return max(self.bottom_w.sizeHint().height() + 6, 290)

    def set_meta_fold(self, on):
        """Ajustes → General: permitir (o no) ocultar los metadatos con la barrita."""
        self.meta_fold = bool(on)
        self.cfg.setValue("meta_fold", 1 if on else 0)
        if not on:
            self.set_meta_open(True)
        self.fold_btn.setVisible(self.meta_fold)
        if getattr(self, "spec_pane", None) is None:
            self.set_rows_locked(True)

    def set_meta_open(self, on, animate=True):
        """Oculta / muestra SOLO los metadatos: la lista baja hasta abajo y la portada y Géneros/Letra se quedan."""
        on = bool(on) or not getattr(self, "meta_fold", True)
        self.fold_btn.setVisible(getattr(self, "meta_fold", True))
        for b in (self.fold_btn, self.fold_btn2):
            b.setIcon(icons.vicon("chevron_d" if on else "chevron_u"))
            b.setToolTip(T("Ocultar o mostrar los metadatos (se puede desactivar en Ajustes → General)"))
        self.fold_btn.setText(T("Ocultar metadatos"))
        self.fold_btn2.setText(T("Mostrar metadatos"))
        if on == self.meta_open and self.center_stack.currentIndex() == (0 if on else 1):
            return
        self.meta_open = on
        self.cfg.setValue("meta_open", 1 if on else 0)
        cols = self.top_split.sizes()
        if on:   # todo vuelve a su sitio de filas
            self.top_split.insertWidget(0, self.list_pane)
            self.top_split.insertWidget(1, self.cover_w)
            self.bottom_split.insertWidget(1, self.rightlow)
            self.rightlow.setMinimumHeight(0)
            self.rightlow.setMaximumHeight(16777215)
            self.center_stack.setCurrentIndex(0)
            fs = self.fold_split.sizes()
            if sum(fs) > 0:
                self.top_split.setSizes(fs)
                self.bottom_split.setSizes(fs)
            self.set_rows_locked(getattr(self, "spec_pane", None) is None)
        else:
            self.fold_left.layout().insertWidget(0, self.list_pane, 1)
            fr = self.fold_right.layout()
            fr.addWidget(self.cover_w, 1)
            fr.addWidget(self.rightlow)
            self.rightlow.setFixedHeight(self.bottom_row_h())   # Géneros/Letra con el mismo alto de siempre
            self.center_stack.setCurrentIndex(1)
            if sum(cols) > 0:
                self.fold_split.setSizes(cols)
        self.list_pane.show()
        self.cover_w.show()
        self.rightlow.show()
        QTimer.singleShot(0, self.layout_overlay)

    def style_splitter(self, sp):
        sp.setHandleWidth(9)
        sp.setChildrenCollapsible(False)

    def fit_to_screen(self):
        """Si la ventana (por tamaño guardado o cambio de pantalla) no cabe, la ajusta y la mete en la pantalla."""
        if self.isMaximized() or self.isFullScreen():
            return
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        w, h = min(self.width(), scr.width()), min(self.height(), scr.height())
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        g = self.frameGeometry()
        x = max(scr.left(), min(g.x(), scr.right() - g.width() + 1))
        y = max(scr.top(), min(g.y(), scr.bottom() - g.height() + 1))
        if (x, y) != (g.x(), g.y()):
            self.move(x, y)

    def closeEvent(self, e):
        self.apply_form()
        if any(self.pending.values()):
            if self.yes_no_save():
                self.save_all()
        self.cfg.setValue("geometry", self.saveGeometry())
        self.cfg.setValue("split_main2", self.main_split.saveState())
        self.cfg.setValue("split_rows2", self.mid_split.saveState())
        self.cfg.setValue("split_cols2", (self.top_split if self.meta_open else self.fold_split).saveState())
        if self.player is not None:
            self.player.stop()
        try:
            self.music_keys.release_global()
            if self.media is not None:
                self.media.close()
        except Exception:
            note_quiet()
        if getattr(self, "mini", None) is not None:
            self.mini.shutdown()
        if getattr(getattr(self, "mobile", None), "inner", None) is not None:
            self.mobile.inner.shutdown()
        try:
            self.thumbs.stop()
        except Exception:
            note_quiet()
        super().closeEvent(e)

    # ------------------------------------------------ Portada: menú de clic derecho
    def cover_side(self):
        return self.cover_max

    def set_cover_max(self, v):
        self.cover_max = v
        self.cfg.setValue("cover_size", "Original" if v is None else str(v))
        self.statusBar().showMessage(
            "Las portadas nuevas se dejarán en su tamaño original." if v is None
            else f"Las portadas nuevas se reducirán a un máximo de {v} px.")

    def cover_data_of(self, path):
        """Portada que ve el usuario: la pendiente, la incrustada o la imagen de la carpeta."""
        pend = self.pending.get(path, {})
        if "_cover" in pend:
            return pend["_cover"] or None
        d = inspect_file(path)
        if d["cover"]:
            return d["cover"]
        fi = find_folder_image(os.path.dirname(path))
        if fi:
            try:
                with open(fi, "rb") as fh:
                    return fh.read()
            except OSError:
                return None
        return None

    def view_cover(self):
        p = self.current_path()
        data = self.cover_data_of(p) if p else None
        pm = QPixmap()
        if not data or not pm.loadFromData(data):
            self.statusBar().showMessage("Esta canción no tiene portada.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(os.path.basename(p))
        v = QVBoxLayout(dlg)
        scr = QApplication.primaryScreen().availableGeometry()
        side = int(min(scr.width(), scr.height()) * 0.8)
        lab = QLabel()
        lab.setPixmap(pm if max(pm.width(), pm.height()) <= side else
                      pm.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        v.addWidget(lab)
        dlg.exec()

    def cover_menu(self, pos):
        if not self.cur_paths:
            return
        n = len(self.cur_paths)
        m = TMenu(self)
        m.addAction("🖼 Cambiar portada…", self.set_cover)
        m.addAction("✨ Buscar portada automáticamente", self.auto_cover)
        m.addAction("🌐 Buscar en Google Imágenes…", lambda: self.google_cover())
        m.addAction("🪄 Mejorar calidad con IA (agrandar)…", self.open_upscale)
        m.addAction("🗑 Quitar portada", self.remove_cover)
        m.addSeparator()
        m.addAction("📋 Copiar portada", self.copy_cover)
        paste = m.addAction("📥 Pegar portada (reemplaza la actual)", self.paste_cover)
        paste.setEnabled(self.cover_clip is not None or not QApplication.clipboard().image().isNull())
        m.addSeparator()
        m.addAction("💾 Guardar portada como imagen…" if n == 1 else f"💾 Guardar las {n} portadas en una carpeta…",
                    self.save_cover_as)
        m.addSeparator()
        sub = m.addMenu("↔ Redimensionar portada" + ("s" if n > 1 else "") + " a…")
        for s in (300, 500, 600, 800, 1000, 1200):
            sub.addAction(f"{s} px", lambda _=False, s=s: self.resize_covers(s))
        sub.addAction("Otro tamaño…", self.resize_custom)
        sub2 = m.addMenu("⚙ Tamaño máximo al poner portadas nuevas")
        for label, v in [("Original (sin reducir)", None)] + [(f"{s} px", s) for s in (300, 500, 600, 800, 1000, 1200)]:
            a = sub2.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.cover_max == v)
            a.triggered.connect(lambda _=False, v=v: self.set_cover_max(v))
        m.exec(self.cover_lbl.mapToGlobal(pos))

    def resize_custom(self):
        v, ok = QInputDialog.getInt(self, "Redimensionar portadas", "Lado mayor máximo (px):", 600, 50, 4000)
        if ok:
            self.resize_covers(v)

    def copy_cover(self):
        p = self.current_path()
        data = self.cover_data_of(p) if p else None
        if not data:
            self.statusBar().showMessage("Esta canción no tiene portada que copiar.")
            return
        self.cover_clip = data
        self.cover_clip_img = QImage.fromData(data)
        if not self.cover_clip_img.isNull():
            QApplication.clipboard().setImage(self.cover_clip_img)  # también sirve para pegarla en otros programas
        self.statusBar().showMessage("Portada copiada. Ve a otra canción → clic derecho en la portada → Pegar portada.")

    def paste_cover(self):
        if not self.cur_paths:
            return
        data = None
        cb = QApplication.clipboard().image()
        if self.cover_clip is not None and (cb.isNull() or (self.cover_clip_img is not None
                                                            and cb.size() == self.cover_clip_img.size())):
            data = self.cover_clip  # la que copiamos aquí (conserva su calidad original)
        elif not cb.isNull():  # una imagen copiada desde otro programa
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            cb.save(buf, "PNG" if cb.hasAlphaChannel() else "JPG", 92)
            data = bytes(ba)
        if not data:
            self.statusBar().showMessage("No hay ninguna portada copiada.")
            return
        data = prepare_cover(data, self.cover_side())
        if data is None:
            QMessageBox.warning(self, "Imagen no válida", "No se pudo usar esa imagen.")
            return
        self.apply_form()
        for p in self.cur_paths:
            self.pending.setdefault(p, {})["_cover"] = data
        self.mark_items()
        self.show_current(self.current_path(), len(self.cur_paths))
        self.statusBar().showMessage(f"Portada pegada en {len(self.cur_paths)} canción(es) (pendiente de guardar).")

    def save_cover_as(self):
        paths = list(self.cur_paths)
        if not paths:
            return
        try:
            if len(paths) == 1:
                p = paths[0]
                data = self.cover_data_of(p)
                if not data:
                    self.statusBar().showMessage("Esta canción no tiene portada.")
                    return
                ext = ".png" if mime_of(data) == "image/png" else ".jpg"
                base = safe_filename(f"{self.val(p, 'artist')} - {self.val(p, 'title')}".strip(" -")) \
                    or os.path.splitext(os.path.basename(p))[0]
                f, _ = QFileDialog.getSaveFileName(self, "Guardar portada como", os.path.join(os.path.dirname(p), base + ext),
                                                   "Imagen (*.jpg *.jpeg *.png)")
                if not f:
                    return
                if not os.path.splitext(f)[1]:
                    f += ext
                with open(f, "wb") as fh:
                    fh.write(data)
                self.statusBar().showMessage(f"Portada guardada en {f}")
            else:
                folder = QFileDialog.getExistingDirectory(self, "Carpeta donde guardar las portadas")
                if not folder:
                    return
                saved = 0
                for p in paths:
                    data = self.cover_data_of(p)
                    if not data:
                        continue
                    ext = ".png" if mime_of(data) == "image/png" else ".jpg"
                    base = os.path.splitext(os.path.basename(p))[0]
                    dst, n = os.path.join(folder, base + ext), 2
                    while os.path.exists(dst):
                        dst = os.path.join(folder, f"{base} ({n}){ext}")
                        n += 1
                    with open(dst, "wb") as fh:
                        fh.write(data)
                    saved += 1
                self.statusBar().showMessage(f"{saved} portada(s) guardada(s) en {folder}")
        except OSError as e:
            QMessageBox.warning(self, "Error", str(e))

    def open_spectrum(self):
        paths = self.selected_paths()
        if not paths:
            cp = self.current_path()
            paths = [cp] if cp and os.path.isfile(cp) else []
        if not paths:
            QMessageBox.information(self, "Espectrograma", "Selecciona una o varias canciones (Ctrl+clic para varias).")
            return
        try:
            import spectro
        except ImportError as e:
            QMessageBox.warning(self, "Espectrograma", f"Falta un componente: {e}\n\nInstala:  pip install numpy imageio-ffmpeg")
            return
        self.close_spectrum(restore=False)
        pane = QWidget()
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        back = QPushButton("⬅ Volver a metadatos y letra")
        back.setObjectName("tabbtn")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.clicked.connect(lambda: self.close_spectrum())
        top.addWidget(back)
        top.addStretch(1)
        pv.addLayout(top)
        sw = spectro.SpectrumDialog(paths[:12], pane)
        sw.setWindowFlags(Qt.WindowType.Widget)
        pv.addWidget(sw, 1)
        pane.setMinimumHeight(260)
        self.spec_pane, self.spec_widget = pane, sw
        self._spec_sizes = self.mid_split.sizes()
        if not self.meta_open:
            self.set_meta_open(True, animate=False)
        self.bottom_stack.addWidget(pane)
        self.bottom_stack.setCurrentWidget(pane)   # reemplaza metadatos + géneros/letra; la portada se queda arriba
        self.set_rows_locked(False)                # con el espectrograma sí se puede estirar
        total = max(sum(self._spec_sizes), 600)
        self.mid_split.setSizes([int(total * 0.36), int(total * 0.64)])
        i18n.retranslate(pane)
        self.statusBar().showMessage("Espectrograma en el panel de abajo. «Volver» recupera los metadatos y la letra.")

    def close_spectrum(self, restore=True):
        pane = getattr(self, "spec_pane", None)
        if pane is None:
            return
        try:
            self.spec_widget.shutdown()
        except Exception:
            note_quiet()
        self.bottom_stack.setCurrentIndex(0)
        self.bottom_stack.removeWidget(pane)
        self.set_rows_locked(True)
        restore = False   # el tamaño de la fila de abajo ya queda fijo; no se restauran proporciones
        pane.hide()
        pane.setParent(None)
        pane.deleteLater()
        self.spec_pane = self.spec_widget = None
        if restore:
            sz = getattr(self, "_spec_sizes", None)
            if sz and len(sz) >= 2:
                self.mid_split.setSizes(sz[:2])

    def open_youtube(self, path, external=True):
        artist, title = self.val(path, "artist"), self.val(path, "title")
        q = f"{artist} {title}".strip() if title else os.path.splitext(os.path.basename(path))[0]
        QDesktopServices.openUrl(QUrl("https://www.youtube.com/results?search_query=" + quote_plus(q)))
        self.statusBar().showMessage(f"Buscando «{q}» en YouTube…")

    def schedule_select(self):
        """Espera a que termines de seleccionar antes de leer datos (evita la lentitud)."""
        if self.list.selecting:
            return
        self.sel_timer.start()

    # ------------------------------------------------------ Menús y ayuda
    def build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("&Archivo")
        m.addAction(self.act("📌 Agregar carpeta al árbol…", self.pin_folder))
        m.addAction(self.act("➕ Nueva carpeta", lambda: self.new_folder()))
        m.addSeparator()
        sv = self.act("💾 Guardar cambios en los archivos\tCtrl+S", self.save_all)
        m.addAction(sv)
        m.addSeparator()
        m.addAction(self.act("Salir", self.close))

        e = mb.addMenu("&Edición")
        e.addAction(self.act("✂️ Cortar\tCtrl+X", lambda: self.clip_set("cut")))
        e.addAction(self.act("📋 Copiar\tCtrl+C", lambda: self.clip_set("copy")))
        e.addAction(self.act("📥 Pegar\tCtrl+V", self.paste_here))
        e.addAction(self.act("↩ Deshacer último mover / renombrar\tCtrl+Alt+Z", self.undo_fs,
                             "Devuelve a su sitio lo último que moviste o renombraste"))
        e.addSeparator()
        e.addAction(self.act("📋 Copiar metadatos\tCtrl+Shift+C", self.copy_meta,
                             "Copia las etiquetas y la portada de la canción elegida"))
        e.addAction(self.act("📥 Pegar metadatos…\tCtrl+Shift+V", self.paste_meta,
                             "Pega en las canciones elegidas las etiquetas copiadas (eliges cuáles)"))
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, activated=self.copy_meta)
        QShortcut(QKeySequence("Ctrl+M"), self, activated=lambda: self.enter_mini(False))
        QShortcut(QKeySequence("Ctrl+Shift+M"), self, activated=lambda: self.enter_mini(True))
        QShortcut(QKeySequence("Ctrl+Alt+Z"), self, activated=self.undo_fs)
        QShortcut(QKeySequence("Ctrl+Shift+V"), self, activated=self.paste_meta)
        e.addSeparator()
        e.addAction(self.act("✏️ Renombrar\tF2", self.rename_current))
        e.addAction(self.act("🗑 Eliminar\tSupr", self.delete_current))
        e.addSeparator()
        e.addAction(self.act("🔍 Buscar canción…\tCtrl+F", lambda: (self.search.setFocus(), self.search.selectAll())))
        self.act_sub = self.act("📂 Incluir subcarpetas", lambda on: self.chk_sub.setChecked(on), "", True)
        self.chk_sub.toggled.connect(self.act_sub.setChecked)
        e.addAction(self.act_sub)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=lambda: (self.search.setFocus(), self.search.selectAll()))

        v = mb.addMenu("&Ver")
        v.addAction(self.act_view)
        v.addAction(self.act_tree2)
        v.addAction(self.act_orient)
        v.addAction(self.act_lyr)
        self.act_cc = self.act("🎨 Colores según la portada", self.toggle_cover_colors,
                               "El programa toma el color de la portada de la canción que suena", True)
        self.act_cc.setChecked(bool(int(self.cfg.value("cover_colors", 1) or 0)))
        v.addAction(self.act_cc)
        v.addSeparator()
        v.addAction(self.act("🔄 Recargar carpetas", self.reload_all))

        p = mb.addMenu("&Reproducción")
        p.addAction(self.act("▶ Reproducir / pausa\tEspacio", self.toggle_play))
        p.addAction(self.act("⏮ Anterior", lambda: self.step_play(-1)))
        p.addAction(self.act("⏭ Siguiente", lambda: self.step_play(1)))
        p.addAction(self.act("⏹ Detener", self.stop_play))
        p.addSeparator()
        p.addAction(self.act("☰ Lista de reproducción", self.show_playlist))
        p.addAction(self.act("🪟 Modo reproductor (solo el reproductor)\tCtrl+M", lambda: self.enter_mini(False)))
        p.addAction(self.act("🪟 Separar el reproductor (dos ventanas)\tCtrl+Shift+M", lambda: self.enter_mini(True),
                             "El reproductor pasa a su propia ventana y el editor sigue abierto"))
        p.addAction(self.act("➕ Añadir selección a la lista", lambda: self.pl_add(self.selected_paths())))

        t = mb.addMenu("&Herramientas")
        t.setToolTipsVisible(True)
        groups = [
            ("Audio y calidad", [
                ("📊 Espectrograma y calidad…", self.open_spectrum,
                 "Espectrograma y análisis de calidad de las canciones seleccionadas (varias = comparar)"),
                ("🎚 Ajustes de la canción…", self.open_fx,
                 "Graves, agudos, tempo, tono, velocidad, bucle, eco… y guardar como canción nueva o reemplazar"),
                ("🔊 Normalizar volumen…", self.open_normalize, "Deja todas las canciones seleccionadas con el mismo volumen"),
                ("🩹 Reparar recortes (clipping)…", self.open_repair,
                 "Reconstruye los golpes fuertes «aplastados» que suenan ásperos o distorsionados"),
                ("🔄 Convertir formato…", self.convert_selected, "Convierte las canciones seleccionadas a otro formato")]),
            ("Etiquetas y portadas", [
                ("🎧 Identificar por sonido (AcoustID)…", self.open_acoustid,
                 "Reconoce las canciones seleccionadas escuchando su audio, aunque no tengan nombre ni etiquetas"),
                ("💿 Emparejar álbum con MusicBrainz…", self.open_album_match,
                 "Coloca cada archivo en su pista del álbum y corrige título, pista, disco, año e intérprete del álbum"),
                ("🎼 Buscar etiquetas en MusicBrainz…", lambda: self.open_tag_source("musicbrainz"),
                 "Buscar las etiquetas de esta canción en MusicBrainz (gratis)"),
                ("💿 Buscar etiquetas en Discogs…", lambda: self.open_tag_source("discogs"),
                 "Buscar las etiquetas de esta canción en Discogs (necesita tu token)"),
                ("✨ Portadas automáticas (alta calidad)", self.auto_cover,
                 "Busca en iTunes/Deezer la portada de las canciones seleccionadas"),
                ("🏷 Géneros en lote…", self.open_batch_genres,
                 "Afina géneros generales («Electronic», «Rock»…) por álbum con MusicBrainz y la IA, o pon géneros a muchas a la vez"),
                ("🏷 Etiquetas desde el nombre del archivo…", self.open_tags_from_name,
                 "Saca artista, título, pista… del nombre de los archivos seleccionados")]),
            ("Organizar la biblioteca", [
                ("📋 Informe de la biblioteca…", self.open_report,
                 "Cuántas canciones no tienen portada, letra, género, año… y acceso directo a cada una"),
                ("🔁 Buscar canciones repetidas…", self.open_dupes,
                 "Encuentra canciones duplicadas y deja marcadas las copias de peor calidad"),
                ("🗂 Organizar en carpetas (Artista / Álbum)…", self.open_organize, "Mueve las canciones a carpetas según sus etiquetas"),
                ("📁 Crear carpetas por… (canciones elegidas)", self.open_folders_by,
                 "Reparte las canciones seleccionadas en carpetas por intérprete, álbum, género, año…")]),
            ("Internet y servidor", [
                ("⬇ Descargar de YouTube / SoundCloud a MP3…", self.open_ytdl,
                 "Descarga el audio de un enlace de YouTube o SoundCloud como MP3 para luego editarlo"),
                ("▶️ Buscar en YouTube (navegador)", self.youtube_current, "Abre la canción elegida en YouTube"),
                ("📡 Navidrome (servidor de música)…", self.open_navidrome,
                 "Conecta con tu Navidrome: actualizar la biblioteca, revisar qué se verá mal y ver tus más escuchadas")]),
        ]
        group_icons = {"Audio y calidad": "fx", "Etiquetas y portadas": "tag", "Organizar la biblioteca": "layers",
                       "Internet y servidor": "globe"}
        for head, items in groups:   # una categoría por línea; al pasar el ratón se despliegan sus herramientas
            sub = t.addMenu(icons.vicon(group_icons.get(head, "tools"), ctx="menu"), T(head))
            sub.setToolTipsVisible(True)
            for text, fn, tip in items:
                sub.addAction(self.act(text, fn, tip))

        fs = mb.addMenu("&Fuente de etiquetas")
        fs.addAction(self.act("🎼 Buscar en MusicBrainz…", lambda: self.open_tag_source("musicbrainz")))
        fs.addAction(self.act("💿 Buscar en Discogs…", lambda: self.open_tag_source("discogs")))
        fs.addSeparator()
        fs.addAction(self.act("🔑 Token de Discogs…", lambda: self.open_settings(3)))

        # «Ajustes» abre la ventana de opciones directamente (todo está dentro: IA, apariencia, idioma…)
        self.act_settings = self.act("&Ajustes", lambda: self.open_settings("general"), "Opciones del programa")
        mb.addAction(self.act_settings)

        a = mb.addMenu("A&yuda")
        a.addAction(self.act("👋 Primeros pasos", self.show_welcome, "Un recorrido corto por lo principal del programa"))
        a.addAction(self.act("❓ Guía rápida", self.show_guide))
        a.addAction(self.act("⌨ Atajos de teclado", self.show_shortcuts, "Todas las teclas rápidas del programa"))
        a.addAction(self.act("🔄 Buscar actualizaciones…", self.check_updates))
        self.act_autoupd = self.act("Buscar actualizaciones al abrir el programa", self.toggle_auto_update, "", True)
        self.act_autoupd.setChecked(bool(int(self.cfg.value("auto_update", 1) or 0)))
        a.addAction(self.act_autoupd)
        a.addSeparator()
        a.addAction(self.act("🆕 Novedades de esta versión", lambda: self.show_whats_new(True)))
        a.addAction(self.act("ℹ️ Acerca de Music Manager", self.show_about))
        a.addAction(self.act("🐞 Reportar un problema…", self.report_problem,
                             "Prepara un informe con la versión y los últimos errores para enviarlo al autor"))
        a.addAction(self.act("📋 Registro de errores…", self.open_error_log,
                             "Abre el archivo donde el programa anota los fallos (útil para enviarlo si algo no funciona)"))
        mb.setCornerWidget(self._corner, Qt.Corner.TopRightCorner)
        i18n.set_lang(str(self.cfg.value("lang", "es")))
        self.set_view_mode(str(self.cfg.value("view_mode", "icons") or "icons"), save=False)
        i18n.retranslate(self)
        self.update_lang_btn()
        QTimer.singleShot(5000, self.auto_check_updates)

    def auto_check_updates(self):
        self.report_update_result()
        self.show_whats_new()
        if int(self.cfg.value("auto_update", 1) or 0):
            self.check_updates(manual=False)

    def open_repair(self):
        import repair
        paths = [p for p in self.selected_paths() if p and os.path.isfile(p)]
        if not paths:
            cp = self.current_path()
            paths = [cp] if cp and os.path.isfile(cp) else []
        if not paths:
            QMessageBox.information(self, T("Reparar recortes (clipping)"), T("Selecciona una o varias canciones."))
            return
        dlg = repair.RepairDialog(self, paths)
        i18n.retranslate(dlg)
        dlg.show()
        self._repair = dlg

    def convert_paths(self, paths, fmt="MP3", kbps=320):
        """Abre «Convertir formato» con el formato y la calidad ya elegidos (lo usa la recomendación del espectrograma)."""
        import convert
        dlg = convert.ConvertDialog(list(paths), self, on_done=lambda: self.load_folder(self.current_dir))
        if fmt in convert.FORMATS:
            dlg.fmt.setCurrentText(fmt)
            i = dlg.q.findData(kbps)
            if i >= 0:
                dlg.q.setCurrentIndex(i)
        i18n.retranslate(dlg)
        dlg.show()
        self._conv = dlg

    def convert_selected(self):
        paths = self.selected_paths()
        if not paths:
            cp = self.current_path()
            paths = [cp] if cp and os.path.isfile(cp) else []
        if not paths:
            QMessageBox.information(self, "Convertir", T("Selecciona una o varias canciones."))
            return
        try:
            import convert
        except ImportError as e:
            QMessageBox.warning(self, "Convertir", f"Falta un componente: {e}")
            return
        dlg = convert.ConvertDialog(paths, self, on_done=lambda: self.load_folder(self.current_dir))
        i18n.retranslate(dlg)
        dlg.show()
        self._conv = dlg

    def open_dupes(self):
        import dupes
        folder = self.current_dir if self.current_dir and os.path.isdir(self.current_dir) else None
        if not folder:
            self.statusBar().showMessage("Abre primero una carpeta de música.")
            return
        dlg = dupes.DupesDialog(folder, AUDIO_EXT, self, on_changed=self.refresh_dir, on_open=self.reveal_file,
                                send2trash=send2trash)
        dlg.show()
        self._dupes = dlg

    def _lib_folder(self):
        f = self.current_dir if self.current_dir and os.path.isdir(self.current_dir) else None
        if not f:
            self.statusBar().showMessage("Abre primero una carpeta de música.")
        return f

    def _lib_paths(self):
        paths = self.selected_paths() or [self.list.item(r).data(PATH_ROLE) for r in range(self.list.count())
                                          if self.list.item(r).data(KIND_ROLE) != "dir"]
        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            self.statusBar().showMessage("Selecciona una o varias canciones.")
        return paths

    def _show_tool(self, dlg):
        i18n.retranslate(dlg)
        dlg.show()
        self._tool = dlg

    def open_batch_genres(self, folder=None):
        import genres
        sel = [] if folder else [p for p in self.selected_paths() if p and os.path.isfile(p)]
        folder = folder or (self.current_dir if self.current_dir and os.path.isdir(self.current_dir) else None)
        if not sel and not folder:
            self.statusBar().showMessage("Abre primero una carpeta de música.")
            return
        dlg = genres.BatchGenresDialog(self, folder=folder, paths=sel if len(sel) > 1 else None, audio_ext=AUDIO_EXT,
                                       read_tags=read_tags, ai_base=AIBase)
        self._show_tool(dlg)

    def open_report(self):
        import libtools
        f = self._lib_folder()
        if f:
            self._show_tool(libtools.ReportDialog(self, f, AUDIO_EXT, inspect_file, read_tags))

    def open_organize(self):
        import libtools
        f = self._lib_folder()
        if f:
            self._show_tool(libtools.OrganizeDialog(self, f, AUDIO_EXT))

    def open_acoustid(self):
        import picard_tools
        paths = [p for p in self.selected_paths() if p and os.path.isfile(p)]
        if not paths:
            self.statusBar().showMessage(T("Selecciona una o varias canciones."))
            return
        self._show_tool(picard_tools.AcoustIdDialog(self, paths[:200]))

    def open_album_match(self):
        import picard_tools
        paths = [p for p in self.selected_paths() if p and os.path.isfile(p)]
        if len(paths) < 2:   # sin selección (o una sola): todas las canciones de la carpeta abierta
            paths = [self.list.item(r).data(PATH_ROLE) for r in range(self.list.count())
                     if self.list.item(r).data(KIND_ROLE) != "dir"]
        paths = [p for p in paths if p and os.path.isfile(p)]
        if not paths:
            self.statusBar().showMessage(T("Abre una carpeta con un álbum o selecciona sus canciones."))
            return
        self._show_tool(picard_tools.AlbumMatchDialog(self, paths[:150], tech_info))

    def menu_head(self, menu, text):
        """Título de grupo dentro de un menú (texto pequeño en gris, no se puede pulsar)."""
        from PyQt6.QtWidgets import QWidgetAction
        lab = QLabel(T(text).upper())
        lab.setObjectName("menuhead")
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(lab)
        wa.setEnabled(False)
        menu.addAction(wa)
        return wa

    def open_navidrome(self):
        import navidrome
        folder = self.current_dir if self.current_dir and os.path.isdir(self.current_dir) else ""
        self._show_tool(navidrome.NavidromeDialog(self, folder, AUDIO_EXT, read_tags, inspect_file, find_folder_image))

    def open_folders_by(self):
        import folders_by
        paths = self._lib_paths()
        if paths:
            self._show_tool(folders_by.FoldersByDialog(self, paths, tech_info))

    def open_tags_from_name(self):
        import libtools
        paths = self._lib_paths()
        if paths:
            self._show_tool(libtools.TagsFromNameDialog(self, paths))

    def open_normalize(self):
        import libtools
        paths = self._lib_paths()
        if paths:
            self._show_tool(libtools.NormalizeDialog(self, paths))

    def go_to_folder(self, path):
        """Desde una búsqueda (o con «Incluir subcarpetas»): abre la carpeta donde está la canción, sin búsqueda,
        y la deja marcada y a la vista."""
        if self.search.text():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.apply_filter("")
        if self.chk_sub.isChecked():
            self.chk_sub.blockSignals(True)
            self.chk_sub.setChecked(False)   # solo esa carpeta, como en el Explorador
            self.chk_sub.blockSignals(False)
        folder = os.path.dirname(path)
        self.reveal_file(path)
        def center():
            r = self.row_index.get(path)
            if r is not None and self.list.item(r) is not None:
                self.list.scrollToItem(self.list.item(r), QAbstractItemView.ScrollHint.PositionAtCenter)
        center()
        QTimer.singleShot(150, center)   # otra vez cuando termine de colocar las tarjetas
        QTimer.singleShot(600, center)
        self.statusBar().showMessage(T(f"Carpeta: {folder}"))

    def show_in_explorer(self, path):
        if sys.platform == "win32":
            import subprocess
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def reveal_file(self, path):
        """Abre la carpeta de esa canción en la lista y la deja seleccionada."""
        folder = os.path.dirname(path)
        if os.path.normpath(folder) != os.path.normpath(self.current_dir or ""):
            self.open_dir(folder)
        self.load_folder(folder, select=[path])
        self.raise_()
        self.activateWindow()

    def fx_release(self, path):
        """path=None: pausa el reproductor (para oír la muestra). path=archivo: suelta ese archivo si suena."""
        if self.player is None:
            return
        if path is None:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
        elif self.playing_path and os.path.normpath(self.playing_path) == os.path.normpath(path):
            self.player.stop()
            self.player.setSource(QUrl())

    def open_fx(self):
        import fx
        path = self.playing_path if self.playing_path and os.path.isfile(self.playing_path) else None
        if path is None:
            sel = [p for p in self.selected_paths() if os.path.isfile(p)]
            path = sel[0] if sel else None
        if path is None:
            self.statusBar().showMessage("Reproduce o selecciona una canción para ajustarla.")
            return
        off = 0.0
        if self.player is not None and self.playing_path and os.path.normpath(self.playing_path) == os.path.normpath(path):
            off = self.player.position() / 1000.0
        dlg = fx.FxDialog(path, self, offset=off, release=self.fx_release, on_saved=self.fx_done)
        i18n.retranslate(dlg)
        dlg.show()
        self._fx = dlg

    def fx_done(self, path, replaced):
        find_folder_image.cache_clear()
        folder = os.path.dirname(path)
        if os.path.normpath(folder) != os.path.normpath(self.current_dir or ""):
            self.open_dir(folder)
        self.load_folder(folder, select=[path])
        self.statusBar().showMessage(("Canción reemplazada con los ajustes: " if replaced else "Canción nueva guardada: ")
                                     + os.path.basename(path))

    def open_ytdl(self):
        import ytdl
        dest = self.current_dir if self.current_dir and os.path.isdir(self.current_dir) else (
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.MusicLocation) or os.path.expanduser("~"))
        dlg = ytdl.YoutubeDialog(dest, self, on_done=self.ytdl_done)
        i18n.retranslate(dlg)
        dlg.show()
        self._ytdl = dlg

    def ytdl_done(self, folder, files):
        if os.path.normpath(folder) != os.path.normpath(self.current_dir or ""):
            self.open_dir(folder)
        find_folder_image.cache_clear()
        self.load_folder(folder, select=files or None)
        if files:
            self.statusBar().showMessage("Descargado. Edita los metadatos, ponle portada y guarda.")

    def apply_field_visibility(self):
        hidden = {x for x in str(self.cfg.value("hidden_fields", "") or "").split(",") if x}
        for k, (lb, le) in self.field_widgets.items():
            lb.setVisible(k not in hidden)
            le.setVisible(k not in hidden)
        self.tech_bar.setVisible("tech" not in hidden)

    def web_artist(self, kind, name):
        name = (name or "").strip()
        if not name:
            return
        if kind == "wiki":
            lang = i18n.CUR if i18n.CUR in ("es", "en", "ru") else "es"
            url = f"https://{lang}.wikipedia.org/wiki/Special:Search?go=Go&search=" + quote(name)
        elif kind == "youtube":
            url = "https://www.youtube.com/results?search_query=" + quote_plus(name)
        elif kind == "tidal":
            url = "https://tidal.com/search?q=" + quote(name)
        elif kind == "qobuz":
            url = "https://www.qobuz.com/search?q=" + quote_plus(name)
        else:
            url = "https://open.spotify.com/search/" + quote(name)
        app = {"spotify": ("spotify", "spotify:search:" + quote(name)),
               "tidal": ("tidal", "tidal://search/" + quote(name))}.get(kind)
        if app and app_installed(app[0]):   # programa instalado: se abre directamente en él
            if QDesktopServices.openUrl(QUrl(app[1])):
                self.statusBar().showMessage(f"Abriendo «{name}» en {kind.capitalize()}…")
                return
        QDesktopServices.openUrl(QUrl(url))
        self.statusBar().showMessage(f"Abriendo «{name}» en el navegador…")

    def web_song(self, kind):
        p = self.current_path()
        if not p:
            self.statusBar().showMessage("Selecciona una canción primero.")
            return
        artist, title = self.val(p, "artist"), self.val(p, "title")
        title = title or os.path.splitext(os.path.basename(p))[0]
        if kind == "wiki":
            self.web_artist("wiki", artist or title)
        else:
            self.web_artist(kind, f"{artist} {title}".strip())

    def add_person_actions(self, m, name):
        name = (name or "").strip()
        if not name:
            return
        m.addSeparator()
        hd = m.addAction(f"👤 {name}")
        hd.setEnabled(False)
        m.addAction(T("📖 Historia del artista (Wikipedia)"), lambda: self.web_artist("wiki", name))
        m.addAction(T("▶️ Buscar artista en YouTube"), lambda: self.web_artist("youtube", name))
        m.addAction(T("🟢 Buscar artista en Spotify"), lambda: self.web_artist("spotify", name))
        m.addAction(T("🌊 Buscar artista en Tidal"), lambda: self.web_artist("tidal", name))
        m.addAction(T("🎧 Buscar artista en Qobuz"), lambda: self.web_artist("qobuz", name))

    def person_menu(self, le, pos):
        m = le.createStandardContextMenu()
        self.add_person_actions(m, le.text())
        m.exec(le.mapToGlobal(pos))

    def open_tag_source(self, source):
        paths = self.selected_paths()
        if not paths:
            cp = self.current_path()
            paths = [cp] if cp and os.path.isfile(cp) else []
        if not paths:
            QMessageBox.information(self, "Etiquetas", T("Selecciona una canción."))
            return
        token = secret.get(self.cfg, "discogs_token")
        if source == "discogs" and not token:
            QMessageBox.information(self, "Discogs", "Discogs necesita un token personal gratuito.\nPégalo en Ajustes → Fuentes de etiquetas.")
            self.open_settings(3)
            return
        self.apply_form()
        p = paths[0]
        import tagsource
        dlg = tagsource.TagSourceDialog(source, token, self.val(p, "artist"),
                                        self.val(p, "title") or os.path.splitext(os.path.basename(p))[0],
                                        self.val(p, "album"), self)
        dlg.applied.connect(lambda fields, cover, p=p: self.apply_external(p, fields, cover))
        i18n.retranslate(dlg)
        dlg.show()
        self._tagdlg = dlg

    def apply_external(self, path, fields, cover):
        d = self.pending.setdefault(path, {})
        d.update(fields)
        if cover:
            data = prepare_cover(cover, self.cover_side())
            if data:
                d["_cover"] = data
        self.mark_items()
        self.on_select()
        self.statusBar().showMessage("Etiquetas aplicadas a «%s» (pendientes de guardar, en naranja)." % os.path.basename(path))

    def youtube_current(self, external=True):
        p = self.current_path()
        if not p or not os.path.isfile(p):
            QMessageBox.information(self, "YouTube", T("Selecciona una canción."))
            return
        self.open_youtube(p, external)

    def update_lang_btn(self):
        code = i18n.CUR
        self.lang_btn.setIcon(icons.flag_icon(code))
        self.lang_btn.setText(code.upper())

    def set_language(self, code):
        """Cambia el idioma al momento, sin reiniciar."""
        i18n.set_lang(code)
        self.cfg.setValue("lang", code)
        i18n.retranslate(self)
        self.update_lang_btn()
        for fn in (self.update_vol_icon, self.update_xfer, self.update_tree_titles):
            try:
                fn()
            except Exception:
                note_quiet()
        self.statusBar().showMessage({"es": "Idioma: Español", "en": "Language: English",
                                      "ru": "Язык: Русский"}.get(code, ""), 3000)

    def open_settings(self, tab="ia"):
        tab = {0: "ia", 1: "apariencia", 2: "idioma", 3: "fuentes"}.get(tab, tab)
        snap = (self.theme, self.accent, i18n.CUR)
        dlg = QDialog(self)
        dlg.setWindowTitle("Ajustes")
        dlg.resize(780, 540)
        outer = QVBoxLayout(dlg)
        body = QHBoxLayout()
        outer.addLayout(body, 1)
        nav = QTreeWidget()
        nav.setObjectName("settingsnav")
        nav.setHeaderHidden(True)
        nav.setFixedWidth(210)
        nav.setIndentation(14)
        body.addWidget(nav)
        right = QVBoxLayout()
        body.addLayout(right, 1)
        head = QLabel("")
        head.setObjectName("title")
        right.addWidget(head)
        stack = QStackedWidget()
        right.addWidget(stack, 1)
        pages, titles, apply_fns = {}, [], []

        def add_page(key, title, widget, parent=None):
            it = QTreeWidgetItem([T(title)])
            it.setData(0, Qt.ItemDataRole.UserRole, key)
            (parent.addChild(it) if parent is not None else nav.addTopLevelItem(it))
            if widget is not None:
                pages[key] = stack.addWidget(widget)
            titles.append((it, title))
            return it

        def page(*items):
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.setContentsMargins(4, 8, 4, 4)
            for x in items:
                lay.addWidget(x) if isinstance(x, QWidget) else lay.addLayout(x)
            lay.addStretch(1)
            return w

        def chk(text, key, default):
            c = QCheckBox(text)
            c.setChecked(bool(int(self.cfg.value(key, default) or 0)))
            apply_fns.append(lambda c=c, key=key: self.cfg.setValue(key, 1 if c.isChecked() else 0))
            return c

        # General
        snap_trees = getattr(self, "trees_mode", "normal")
        r_tn = QRadioButton("Siempre visibles a la izquierda (normal)")
        r_td = QRadioButton("Escondidas: se abren con la flechita del borde izquierdo")
        grp_tm = QButtonGroup(dlg)
        grp_tm.addButton(r_tn)
        grp_tm.addButton(r_td)
        (r_td if snap_trees == "drawer" else r_tn).setChecked(True)
        r_tn.toggled.connect(lambda on: on and self.set_trees_mode("normal"))
        r_td.toggled.connect(lambda on: on and self.set_trees_mode("drawer"))
        fold_chk = QCheckBox("Barrita para ocultar y mostrar los metadatos")
        fold_chk.setChecked(self.meta_fold)
        apply_fns.append(lambda: self.set_meta_fold(fold_chk.isChecked()))
        add_page("general", "General", page(
            chk("Abrir la última carpeta al iniciar", "open_last", 1),
            chk("Confirmar antes de eliminar (con papelera)", "confirm_delete", 1),
            chk("Mostrar la guía rápida cada vez que se inicia", "guide_every", 0),
            fold_chk,
            QLabel(" "), QLabel("<b>Árboles de carpetas</b>"), r_tn, r_td))
        # Reproductor (siempre la barra clásica; el modo celular y el modo ventana se abren con sus botones de la barra)
        snap_style = getattr(self, "player_style", "classic")
        hint_ps = QLabel("En la barra de reproducción, el botón de celular abre el reproductor grande y el de ventanita deja "
                         "solo la portada en una ventana pequeña.")
        hint_ps.setWordWrap(True)
        hint_ps.setObjectName("hint")
        add_page("reproductor", "Reproductor", page(QLabel("<b>Reproductor</b>"),
                                                    chk("Pasar a la siguiente canción al terminar", "autonext", 1), hint_ps))
        # Atajos de música
        hk_rows = []
        for hk_key, hk_def, hk_lab in HOTKEYS:
            ed = QKeySequenceEdit(QKeySequence(str(self.cfg.value(hk_key, hk_def) or "")))
            try:
                ed.setMaximumSequenceLength(1)
                ed.setClearButtonEnabled(True)
            except Exception:
                note_quiet()
            ed.setFixedWidth(200)
            rowk = QHBoxLayout()
            lbk = QLabel(hk_lab)
            lbk.setFixedWidth(170)
            rowk.addWidget(lbk)
            rowk.addWidget(ed)
            dfb = QPushButton("Por defecto")
            dfb.clicked.connect(lambda _c=False, ed=ed, d=hk_def: ed.setKeySequence(QKeySequence(d)))
            rowk.addWidget(dfb)
            rowk.addStretch(1)
            hk_rows.append(rowk)
            apply_fns.append(lambda ed=ed, k=hk_key: self.cfg.setValue(
                k, ed.keySequence().toString(QKeySequence.SequenceFormat.PortableText)))
        apply_fns.append(lambda: self.music_keys.load())
        hk_hint = QLabel("Haz clic en un recuadro y pulsa la tecla (o combinación) que quieras. Funcionan en el editor, en el "
                         "modo reproductor y en la ventanita de la portada, mientras no estés escribiendo en un cuadro de "
                         "texto. Deja un recuadro vacío para quitar ese atajo.")
        hk_hint.setWordWrap(True)
        hk_hint.setObjectName("hint")
        hk_glob = chk("Funcionan también fuera del programa (escribiendo un documento, jugando…)", "hk_global", 1)
        hk_warn = QLabel("Mientras haya una canción puesta, esas teclas quedan reservadas para la música en todo Windows: "
                         "por ejemplo, AvPág y RePág dejan de bajar y subir la página en otros programas. Si eso te molesta, "
                         "elige una combinación (como Ctrl+Alt+Derecha) o las teclas multimedia del teclado. Al detener la "
                         "música o cerrar el programa, las teclas vuelven a la normalidad.")
        hk_warn.setWordWrap(True)
        hk_warn.setObjectName("hint")
        apply_fns.append(lambda: self.music_keys.load())
        add_page("atajos", "Atajos de música", page(QLabel("<b>Teclas para controlar la música</b>"), *hk_rows, hk_hint,
                                                    QLabel(" "), hk_glob, hk_warn))
        # Apariencia
        theme_cb = QComboBox()
        theme_cb.addItem(T("Oscuro"), "dark")
        theme_cb.addItem(T("Claro"), "light")
        theme_cb.setCurrentIndex(0 if self.theme == "dark" else 1)
        theme_cb.currentIndexChanged.connect(lambda: self.set_theme(theme_cb.currentData()))
        f2 = QFormLayout()
        f2.addRow("Tema", theme_cb)
        row = QHBoxLayout()
        for col, name in ACCENTS:
            b = QPushButton()
            b.setFixedSize(30, 30)
            b.setToolTip(name)
            b.setStyleSheet(f"QPushButton {{ background:{col}; border:2px solid transparent; border-radius:15px; }}"
                            f"QPushButton:hover {{ border-color:white; }}")
            b.clicked.connect(lambda _=False, c=col: self.set_accent(c))
            row.addWidget(b)
        row.addStretch(1)
        row2 = QHBoxLayout()
        bo = QPushButton("🎨 Otro color…")
        bo.clicked.connect(lambda: (lambda c: c.isValid() and self.set_accent(c.name()))(
            QColorDialog.getColor(QColor(self.accent or THEMES[self.theme]["accent"]), dlg)))
        br = QPushButton("↺ Restablecer")
        br.clicked.connect(lambda: self.set_accent(""))
        row2.addWidget(bo)
        row2.addWidget(br)
        row2.addStretch(1)
        add_page("apariencia", "Apariencia", page(f2, QLabel("Color de acento"), row, row2))
        # Idioma
        lang_cb = QComboBox()
        lang_cb.setIconSize(QSize(22, 15))
        for code, name in i18n.LANGS:
            lang_cb.addItem(icons.flag_icon(code), name, code)
        lang_cb.setCurrentIndex(max(0, [c for c, _ in i18n.LANGS].index(i18n.CUR)))
        add_page("idioma", "Idioma", page(QLabel("Idioma de la interfaz"), lang_cb,
                                          QLabel("También puedes cambiarlo con la banderita de arriba a la derecha.")))
        # Etiquetas (grupo)
        grp = add_page("etiquetas", "Etiquetas", None)
        hidden = {x for x in str(self.cfg.value("hidden_fields", "") or "").split(",") if x}
        gl = QGridLayout()
        boxes = {}
        names = [(k, n) for k, n in FIELDS] + [("tech", "Información técnica (códec, tasa de bits, frecuencia…)")]
        for i, (k, n) in enumerate(names):
            c = QCheckBox(T(n))
            c.setChecked(k not in hidden)
            boxes[k] = c
            gl.addWidget(c, i // 2, i % 2)
        gw = QWidget()
        gw.setLayout(gl)

        def save_fields():
            self.cfg.setValue("hidden_fields", ",".join(k for k, c in boxes.items() if not c.isChecked()))
            self.apply_field_visibility()
        apply_fns.append(save_fields)
        add_page("panel", "Panel de etiquetas", page(QLabel("Campos que se muestran en el panel de metadatos:"), gw), grp)
        size_cb = QComboBox()
        for v in ("Original", "300", "500", "600", "800", "1000", "1200", "1600"):
            size_cb.addItem(v if v == "Original" else v + " px", v)
        size_cb.setCurrentIndex(max(0, size_cb.findData("Original" if self.cover_max is None else str(self.cover_max))))
        apply_fns.append(lambda: self.set_cover_max(parse_side(size_cb.currentData())))
        add_page("letras", "Letras", page(
            chk("Preferir la letra sincronizada (con minutos) al buscar en LRCLIB", "prefer_synced", 1),
            chk("Guardar también un archivo .lrc junto a la canción", "save_lrc_v2", 0)), grp)
        add_page("portadas", "Portadas", page(QLabel("Tamaño máximo de las portadas nuevas (nunca se agranda):"), size_cb), grp)
        # Fuentes de etiquetas
        tok = QLineEdit(secret.get(self.cfg, "discogs_token"))
        tok.setEchoMode(QLineEdit.EchoMode.Password)
        tok.setPlaceholderText("Token de Discogs")
        apply_fns.append(lambda: secret.put(self.cfg, "discogs_token", tok.text()))
        lnk = QLabel('<a href="https://www.discogs.com/settings/developers">Conseguir mi token (discogs.com/settings/developers)</a>')
        lnk.setOpenExternalLinks(True)
        add_page("fuentes", "Fuentes de etiquetas", page(
            QLabel("MusicBrainz no necesita clave. Discogs necesita un token personal gratuito:"), tok, lnk))
        # Inteligencia artificial (los campos que usa el resto del programa)
        self.ai_cfg.show()
        add_page("ia", "Inteligencia artificial", page(QLabel("Elige el proveedor, el modelo y pega tu clave."), self.ai_cfg))

        nav.expandAll()

        def on_nav(cur, _prev):
            if cur is None:
                return
            key = cur.data(0, Qt.ItemDataRole.UserRole)
            if key not in pages:
                if cur.childCount():
                    nav.setCurrentItem(cur.child(0))
                return
            stack.setCurrentIndex(pages[key])
            head.setText(T(next(t for it, t in titles if it is cur)))
        nav.currentItemChanged.connect(on_nav)

        def change_lang():
            self.set_language(lang_cb.currentData())
            i18n.retranslate(dlg)
            for it, t in titles:
                it.setText(0, T(t))
            cur = nav.currentItem()
            if cur is not None:
                head.setText(T(next(t for it, t in titles if it is cur)))
        lang_cb.currentIndexChanged.connect(change_lang)

        btns = QHBoxLayout()
        btns.addStretch(1)
        okb, cb = QPushButton("Aceptar"), QPushButton("Cancelar")
        okb.setObjectName("accent")
        okb.clicked.connect(dlg.accept)
        cb.clicked.connect(dlg.reject)
        btns.addWidget(okb)
        btns.addWidget(cb)
        outer.addLayout(btns)
        i18n.retranslate(dlg)
        first = next((it for it, _ in titles if it.data(0, Qt.ItemDataRole.UserRole) == tab), titles[0][0])
        nav.setCurrentItem(first)
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        if accepted:
            for fn in apply_fns:
                fn()
            prov = self.provider.currentText()
            self.cfg.setValue("provider", prov)
            secret.put(self.cfg, f"key_{prov}", self.key_le.text())
            self.cfg.setValue(f"model_{prov}", self.model_cb.currentText().strip())
        else:
            if snap[0] != self.theme:
                self.set_theme(snap[0])
            if snap[1] != self.accent:
                self.set_accent(snap[1])
            if snap[2] != i18n.CUR:
                self.set_language(snap[2])
            if snap_style != getattr(self, "player_style", "classic"):
                self.set_player_style(snap_style)
            if snap_trees != getattr(self, "trees_mode", "normal"):
                self.set_trees_mode(snap_trees)
            self.provider.setCurrentText(str(self.cfg.value("provider", "Claude")))
            self.on_provider(self.provider.currentText())
        self.ai_cfg.hide()
        self.ai_cfg.setParent(self)
        self.ai_cfg.hide()

    def rename_current(self):
        fw = QApplication.focusWidget()
        if fw is self.tree or fw is self.tree2:
            self.rename_tree_current(fw)
        else:
            self.rename_selected()

    def delete_current(self):
        fw = QApplication.focusWidget()
        if fw is self.tree or fw is self.tree2:
            self.active_tree = fw
            self.delete_selected()
        else:
            self.delete_paths(self.selected_all_paths() or self.active_tree.selected_dirs())

    def show_guide(self):
        box = QMessageBox(self)
        box.setWindowTitle("Guía rápida")
        box.setIconPixmap(self.logo_pm.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(T(i18n_more.GUIDE_ES))
        box.exec()

    # ------------------------------------------------------- Actualizaciones
    def check_updates(self, manual=True):
        if getattr(self, "upd_worker", None) is not None and self.upd_worker.isRunning():
            return
        self._upd_manual = manual
        if manual:
            self.statusBar().showMessage("Buscando actualizaciones…")
        self.upd_worker = UpdateCheckWorker()
        self.upd_worker.result.connect(self.on_update_info)
        self.upd_worker.start()

    def on_update_info(self, info):
        manual = getattr(self, "_upd_manual", True)
        if not info.get("ok"):
            if manual:
                QMessageBox.warning(self, "Actualizaciones", f"No se pudo consultar GitHub.\n{info.get('error', '')}")
            return
        if info.get("none") or ver_tuple(info.get("tag")) <= ver_tuple(APP_VERSION):
            if manual:
                QMessageBox.information(self, "Actualizaciones", f"Ya tienes la última versión ({APP_VERSION}).")
            self.statusBar().clearMessage()
            return
        tag = info["tag"].lstrip("vV")
        notes = (info.get("notes") or "").strip()
        box = QMessageBox(self)
        box.setWindowTitle("Hay una versión nueva")
        box.setText(f"Versión {tag} disponible (tienes la {APP_VERSION}).")
        if notes:
            box.setInformativeText(notes[:600])
        can_auto = bool(info.get("url")) and getattr(sys, "frozen", False) and sys.platform == "win32"
        b_up = box.addButton("⬇ Actualizar ahora" if can_auto else "Abrir la página de descarga", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Más tarde", QMessageBox.ButtonRole.RejectRole)
        i18n.retranslate(box)
        box.exec()
        if box.clickedButton() is not b_up:
            return
        if can_auto:
            self.download_update(info)
        else:
            QDesktopServices.openUrl(QUrl(info.get("page") or f"https://github.com/{REPO}/releases/latest"))

    def download_update(self, info):
        import tempfile
        dest = os.path.join(tempfile.gettempdir(), "MusicManager-update.zip")
        dlg = QProgressDialog("Descargando la actualización…", "Cancelar", 0, 100, self)
        dlg.setWindowTitle("Actualizando Music Manager")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        w = UpdateDownloadWorker(info["url"], dest, info.get("digest", ""))
        self.upd_dl = w

        def prog(got, total):
            if total:
                dlg.setValue(int(got * 100 / total))
            dlg.setLabelText(f"Descargando la actualización… {got / 1048576:.1f}" + (f" / {total / 1048576:.1f} MB" if total else " MB"))
        w.progress.connect(prog)
        w.failed.connect(lambda m: (dlg.close(), QMessageBox.warning(self, "Actualizaciones", f"No se pudo descargar: {m}")))
        w.done.connect(lambda p: (dlg.close(), self.apply_update(p)))
        dlg.canceled.connect(w.requestInterruption)
        w.start()
        dlg.show()

    def apply_update(self, zip_path):
        """Descomprime la versión nueva (con el programa aún abierto), lo cierra del todo, copia los archivos
        encima y lo vuelve a abrir. Deja un registro en %TEMP%\\mm_update.log para saber qué pasó."""
        import tempfile, subprocess, zipfile
        exe = sys.executable
        app_dir = os.path.dirname(exe)
        tmp = tempfile.gettempdir()
        stage = os.path.join(tmp, "mm_update_new")
        bat = os.path.join(tmp, "mm_update.bat")
        log = os.path.join(tmp, "mm_update.log")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            shutil.rmtree(stage, ignore_errors=True)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(stage)
            root = stage
            name = os.path.basename(exe)
            if not os.path.exists(os.path.join(root, name)):   # por si el zip trae una carpeta raíz
                for d in os.listdir(stage):
                    sub = os.path.join(stage, d)
                    if os.path.isdir(sub) and os.path.exists(os.path.join(sub, name)):
                        root = sub
                        break
                else:
                    raise RuntimeError(f"El archivo descargado no contiene {name}.")
            pid = os.getpid()
            sysd = "%SystemRoot%\\System32\\"
            script = "\r\n".join([
                "@echo off",
                f'set "LOG={log}"',
                'echo Inicio de la actualizacion > "%LOG%"',
                "set /a N=0",
                ":wait",
                f'{sysd}tasklist.exe /FI "PID eq {pid}" /NH 2>nul | {sysd}find.exe "{pid}" >nul',
                "if errorlevel 1 goto go",
                "set /a N+=1",
                f"if %N% GEQ 15 {sysd}taskkill.exe /F /PID {pid} >nul 2>&1",
                f"{sysd}ping.exe -n 2 127.0.0.1 >nul",
                "if %N% GEQ 40 goto fail",
                "goto wait",
                ":go",
                f"{sysd}ping.exe -n 3 127.0.0.1 >nul",
                "set /a T=0",
                ":copy",
                f'{sysd}xcopy.exe "{root}\\*" "{app_dir}" /E /Y /Q /I >> "%LOG%" 2>&1',
                "if not errorlevel 1 goto ok",
                "set /a T+=1",
                "echo intento %T% fallido >> \"%LOG%\"",
                "if %T% GEQ 8 goto fail",
                f"{sysd}ping.exe -n 3 127.0.0.1 >nul",
                "goto copy",
                ":ok",
                'echo OK >> "%LOG%"',
                f'rmdir /s /q "{stage}" 2>nul',
                f'del "{zip_path}" 2>nul',
                f'start "" "{exe}"',
                "exit /b 0",
                ":fail",
                'echo FALLO >> "%LOG%"',
                f'start "" "{exe}"',
                "exit /b 1",
                "",
            ])
            with open(bat, "w", encoding="mbcs", errors="replace") as fh:
                fh.write(script)
            subprocess.Popen(["cmd.exe", "/c", bat], creationflags=0x08000200, close_fds=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Actualizaciones", f"No se pudo preparar la actualización:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Actualizando", "Music Manager se cerrará, se actualizará solo y volverá a abrirse en unos segundos.\n"
                                "Si no se abre, ábrelo tú: se habrá actualizado igual.")
        self.cfg.sync()
        self.close()
        QApplication.quit()
        QTimer.singleShot(1500, lambda: os._exit(0))   # asegura que el proceso termine del todo y se liberen los archivos

    def report_update_result(self):
        """Al abrir: si hubo una actualización pendiente de informar, dice cómo terminó."""
        import tempfile
        log = os.path.join(tempfile.gettempdir(), "mm_update.log")
        if not os.path.exists(log):
            return
        try:
            with open(log, encoding="mbcs", errors="replace") as fh:
                txt = fh.read()
            os.remove(log)
        except OSError:
            return
        if "FALLO" in txt:
            QMessageBox.warning(self, "Actualización", "La última actualización no se pudo instalar.\n\n"
                                "Descarga el .zip nuevo desde la página de GitHub (Releases) y reemplaza la carpeta.\n\n"
                                f"Detalle técnico:\n{txt[-500:]}")
        elif "OK" in txt:
            self.statusBar().showMessage(f"✔ Music Manager se actualizó correctamente (versión {APP_VERSION}).", 15000)

    def toggle_auto_update(self, on):
        self.cfg.setValue("auto_update", 1 if on else 0)

    def show_whats_new(self, force=False):
        """Pantallita con lo que cambió, la primera vez que se abre una versión nueva."""
        last = str(self.cfg.value("last_version", "") or "")
        self.cfg.setValue("last_version", APP_VERSION)
        if not force and not last and not int(self.cfg.value("welcome_done", 0) or 0):
            self.show_welcome()   # instalación nueva: en vez de la lista de novedades, un recorrido corto
            return
        if not force:
            if last == APP_VERSION or (last and ver_tuple(last) > ver_tuple(APP_VERSION)):
                return
        if force or not last:
            entries = [e for e in CHANGELOG if e[0] == APP_VERSION]
        else:
            entries = [e for e in CHANGELOG if ver_tuple(e[0]) > ver_tuple(last)]
        if not entries:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("🎉 Novedades")
        dlg.resize(520, 440)
        v = QVBoxLayout(dlg)
        head = QLabel(f"<h2 style='margin:0'>🎉 Music Manager {APP_VERSION}</h2>"
                      + (f"<p style='margin:2px 0'>Se actualizó desde la versión {last}. Esto es lo nuevo:</p>" if last and not force
                         else "<p style='margin:2px 0'>Esto es lo nuevo en esta versión:</p>"))
        head.setTextFormat(Qt.TextFormat.RichText)
        head.setWordWrap(True)
        v.addWidget(head)
        tb = QTextBrowser()
        tb.setHtml(changelog_html(entries))
        v.addWidget(tb, 1)
        ok = QPushButton("¡Entendido!")
        ok.setObjectName("accent")
        ok.clicked.connect(dlg.accept)
        v.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        i18n.retranslate(dlg)
        dlg.exec()

    def show_shortcuts(self):
        rows = [("Archivos", [("F2", "Renombrar (canción o carpeta)"), ("Supr", "Eliminar (a la papelera)"),
                              ("Ctrl + C / Ctrl + X / Ctrl + V", "Copiar / cortar / pegar"),
                              ("F5", "Actualizar la carpeta"), ("Alt + ← / Alt + →", "Atrás / adelante"),
                              ("Alt + ↑", "Subir a la carpeta de arriba")]),
                ("Etiquetas", [("Ctrl + S", "Guardar los cambios"), ("Ctrl + F", "Buscar canción"),
                               ("Ctrl + Shift + C", "Copiar metadatos"), ("Ctrl + Shift + V", "Pegar metadatos")]),
                ("Reproducir", [("Enter / doble clic", "Reproducir la canción"), ("Espacio", "Pausa / seguir")]),
                ("Dos árboles", [("F6", "Enviar (mover) de «De» a «A»"), ("F7", "Copiar de «De» a «A»")]),
                ("Vista", [("Ctrl + rueda del ratón", "Agrandar o achicar las portadas"),
                           ("Arrastrar arriba/abajo", "Sombrear varias canciones o carpetas")])]
        dlg = QDialog(self)
        dlg.setWindowTitle(T("Atajos de teclado"))
        dlg.resize(560, 520)
        v = QVBoxLayout(dlg)
        tb = QTableWidget(0, 2)
        tb.horizontalHeader().setVisible(False)
        tb.verticalHeader().setVisible(False)
        tb.setShowGrid(False)
        tb.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tb.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tb.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tb.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for group, items in rows:
            r = tb.rowCount()
            tb.insertRow(r)
            gi = QTableWidgetItem(T(group).upper())
            f = gi.font()
            f.setBold(True)
            f.setPointSizeF(max(7.5, f.pointSizeF() - 1))
            gi.setFont(f)
            gi.setForeground(QBrush(self.palette().color(QPalette.ColorRole.PlaceholderText)))
            tb.setItem(r, 0, gi)
            for key, what in items:
                r = tb.rowCount()
                tb.insertRow(r)
                ki = QTableWidgetItem(key)
                kf = ki.font()
                kf.setBold(True)
                ki.setFont(kf)
                tb.setItem(r, 0, ki)
                tb.setItem(r, 1, QTableWidgetItem(T(what)))
        tb.verticalHeader().setDefaultSectionSize(30)
        v.addWidget(tb, 1)
        close = QPushButton(T("Cerrar"))
        close.clicked.connect(dlg.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)
        dlg.exec()

    def show_welcome(self):
        """Recorrido corto para quien abre el programa por primera vez (también en Ayuda → Primeros pasos)."""
        pages = [
            ("folder", "Bienvenido a Music Manager",
             "Ordena, etiqueta y escucha tu música en un solo lugar.<br><br>A la <b>izquierda</b> están tus carpetas. "
             "«Música» ya aparece; con <b>Archivo → Agregar carpeta</b> sumas las tuyas (un disco externo, descargas…)."),
            ("edit", "Editar es seleccionar y escribir",
             "Haz clic en una canción (o en varias con Ctrl o Mayús) y cambia título, artista, álbum, portada o letra "
             "abajo y a la derecha.<br><br>Nada se toca en tus archivos hasta que pulses <b>Guardar (Ctrl+S)</b>. "
             "Mover nunca sobrescribe y borrar va a la papelera."),
            ("sparkle", "Herramientas que hacen el trabajo",
             "En <b>Herramientas</b>: rellenar etiquetas automáticamente, buscar portadas y letras, renombrar en lote, "
             "encontrar duplicados, convertir formatos y revisar la calidad real (espectrograma).<br><br>"
             "Si te equivocas al mover o renombrar: <b>Edición → Deshacer</b>."),
            ("note", "Y a escuchar",
             "Doble clic en una canción para reproducirla. El botón de ventanita separa el reproductor en su propia "
             "ventana; AvPág y RePág cambian de canción aunque estés en otro programa.<br><br>"
             "¿Algo falla? <b>Ayuda → Reportar un problema</b>. ¡Disfrútalo!"),
        ]
        d = QDialog(self)
        d.setWindowTitle(T("Primeros pasos"))
        d.setFixedSize(560, 380)
        v = QVBoxLayout(d)
        stack = QStackedWidget()
        for glyph, title, body in pages:
            w_ = QWidget()
            pv = QVBoxLayout(w_)
            pv.setContentsMargins(24, 14, 24, 6)
            ic = QLabel()
            ic.setPixmap(icons.vicon(glyph, self.palette().color(QPalette.ColorRole.Highlight)).pixmap(54, 54))
            ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tl = QLabel("<h2>" + T(title) + "</h2>")
            tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bl = QLabel(T(body))
            bl.setWordWrap(True)
            bl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            bl.setTextFormat(Qt.TextFormat.RichText)
            pv.addWidget(ic)
            pv.addWidget(tl)
            pv.addWidget(bl, 1)
            stack.addWidget(w_)
        v.addWidget(stack, 1)
        row = QHBoxLayout()
        dots = QLabel("")
        back = QPushButton(T("Atrás"))
        nxt = QPushButton("")
        nxt.setObjectName("accent")
        nxt.setDefault(True)
        skip = QPushButton(T("Saltar"))

        def upd():
            i = stack.currentIndex()
            dots.setText("  ".join("●" if k == i else "○" for k in range(stack.count())))
            back.setEnabled(i > 0)
            nxt.setText(T("Empezar") if i == stack.count() - 1 else T("Siguiente"))

        def go(step):
            i = stack.currentIndex() + step
            if i >= stack.count():
                d.accept()
            else:
                stack.setCurrentIndex(max(0, i))
                upd()
        back.clicked.connect(lambda: go(-1))
        nxt.clicked.connect(lambda: go(1))
        skip.clicked.connect(d.reject)
        row.addWidget(skip)
        row.addStretch(1)
        row.addWidget(dots)
        row.addStretch(1)
        row.addWidget(back)
        row.addWidget(nxt)
        v.addLayout(row)
        upd()
        self.cfg.setValue("welcome_done", 1)
        d.exec()

    def report_problem(self):
        """Arma un informe (versión, Windows y los últimos errores anotados) que el usuario puede revisar, copiar y
        enviar por GitHub. No se envía nada solo: se muestra primero y lo manda la persona."""
        import platform
        tail = ""
        for pth in (error_log_path(), os.path.join(os.path.dirname(error_log_path()), "errores_menores.txt")):
            try:
                with open(pth, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()[-1800:]
                if txt.strip():
                    tail += f"\n--- {os.path.basename(pth)} ---\n{txt}"
            except OSError:
                pass
        home = os.path.expanduser("~")
        tail = tail.replace(home, "~")   # sin el nombre de usuario de Windows
        body = (T("¿Qué estabas haciendo y qué pasó? (escríbelo aquí)") + "\n\n\n"
                f"Music Manager {APP_VERSION} · {platform.system()} {platform.release()} ({platform.version()})\n"
                + (tail or "\n(" + T("sin errores anotados") + ")"))
        d = QDialog(self)
        d.setWindowTitle(T("Reportar un problema"))
        d.resize(640, 520)
        v = QVBoxLayout(d)
        info = QLabel(T("Esto es lo que se enviará. Puedes editarlo o borrar lo que no quieras compartir (por ejemplo, "
                        "nombres de carpetas). Nada se envía solo: al pulsar «Abrir en GitHub» se abre la página con el "
                        "texto listo y tú lo publicas (hace falta una cuenta gratuita de GitHub). Si no tienes, usa "
                        "«Copiar» y mándalo por donde prefieras."))
        info.setWordWrap(True)
        info.setObjectName("dlgsub")
        v.addWidget(info)
        ed = QPlainTextEdit(body)
        v.addWidget(ed, 1)
        row = QHBoxLayout()
        cp = QPushButton(T("Copiar"))
        gh = QPushButton(T("Abrir en GitHub"))
        gh.setObjectName("accent")
        cl = QPushButton(T("Cerrar"))

        def copy():
            QApplication.clipboard().setText(ed.toPlainText())
            self.statusBar().showMessage(T("Informe copiado."))

        def open_gh():
            QApplication.clipboard().setText(ed.toPlainText())   # por si el texto es largo y la página lo corta
            q = urllib.parse.urlencode({"title": f"[{APP_VERSION}] ", "body": ed.toPlainText()[:5500]})
            QDesktopServices.openUrl(QUrl("https://github.com/PandxMax/MusicManager/issues/new?" + q))
        cp.clicked.connect(copy)
        gh.clicked.connect(open_gh)
        cl.clicked.connect(d.reject)
        row.addWidget(cp)
        row.addStretch(1)
        row.addWidget(cl)
        row.addWidget(gh)
        v.addLayout(row)
        d.exec()

    def open_error_log(self):
        p = error_log_path()
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            QMessageBox.information(self, T("Registro de errores"), T("No se ha anotado ningún error. ¡Todo bien!"))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))

    def kofi_icon(self):
        if getattr(self, "_kofi_icon", None) is None:
            pm = QPixmap()
            try:
                import kofi_data
                pm.loadFromData(base64.b64decode("".join(kofi_data.KOFI_PNG_B64)))
            except Exception:
                note_quiet()
            self._kofi_icon = QIcon(pm) if not pm.isNull() else QIcon()
        return self._kofi_icon

    def make_kofi_button(self, text):
        b = QToolButton()
        b.setObjectName("kofibtn")
        b.setText(T(text))
        b.setIcon(icons.vicon("kofi"))   # dibujado: sigue el tema y el color de acento como los demás iconos
        b.setIconSize(QSize(20, 20))
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setToolTip(T("¿Te gusta Music Manager? Invítame un café en Ko-fi ☕ (ko-fi.com/pandxmax)"))
        b.clicked.connect(self.open_kofi)
        return b

    def open_kofi(self):
        try:
            import kofi_data
            url = kofi_data.KOFI_URL
        except Exception:
            url = "https://ko-fi.com/pandxmax"
        QDesktopServices.openUrl(QUrl(url))

    def show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Acerca de Music Manager")
        dlg.resize(560, 560)
        v = QVBoxLayout(dlg)
        top = QHBoxLayout()
        pm = QLabel()
        pm.setPixmap(self.logo_pm.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        top.addWidget(pm)
        t = QLabel(f"<h2 style='margin:0'>Music Manager</h2><p style='margin:2px 0'>{T('Versión')} <b>{APP_VERSION}</b></p>"
                   + T(i18n_more.ABOUT_ES) +
                   f"<p>{T('Creado por')} <b>PandxMax</b> · <a href='https://github.com/PandxMax/MusicManager'>github.com/PandxMax/MusicManager</a></p>")
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setWordWrap(True)
        t.setOpenExternalLinks(True)
        top.addWidget(t, 1)
        v.addLayout(top)
        sup = QFrame()
        sup.setObjectName("card")
        sl = QHBoxLayout(sup)
        sl.setContentsMargins(14, 10, 10, 10)
        sup_t = QLabel(T("<b>¿Te gusta Music Manager?</b><br>Es gratis y lo hago en mi tiempo libre. Si te sirve, "
                         "puedes apoyarlo invitándome un café en Ko-fi."))
        sup_t.setWordWrap(True)
        sup_t.setTextFormat(Qt.TextFormat.RichText)
        sl.addWidget(sup_t, 1)
        sl.addWidget(self.make_kofi_button("Apoyar en Ko-fi"), 0, Qt.AlignmentFlag.AlignVCenter)
        v.addWidget(sup)
        log = QTextBrowser()
        log.setOpenExternalLinks(True)
        log.setHtml("<h3>📜 Historial de versiones</h3>" + changelog_html(CHANGELOG, APP_VERSION))
        v.addWidget(log, 1)
        ok = QPushButton("Cerrar")
        ok.clicked.connect(dlg.accept)
        v.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        dlg.exec()

    def go_to_row(self, r):
        it = self.list.item(r)
        self.list.clearSelection()
        it.setSelected(True)
        self.list.setCurrentItem(it)
        self.list.scrollToItem(it)

    def unresolved_rows(self):
        return [r for r in range(self.list.count())
                if self.list.item(r).data(PATH_ROLE) in self.suggestions
                and self.list.item(r).data(PATH_ROLE) not in self.chosen]

    def update_suggestions(self):
        self.sug_list.clear()
        sel = [p for p in self.cur_paths if p] if len(self.cur_paths) > 1 else []
        if sel:   # varias canciones elegidas: opciones juntas, y el clic pone el género a TODAS
            counts, labels = {}, {}
            for p in sel:
                for label, value in self.suggestions.get(p, []):
                    counts[value] = counts.get(value, 0) + 1
                    labels.setdefault(value, label)
            if counts:
                self.sug_label.setText(T(f"Elige un género para las {len(sel)} canciones seleccionadas (se pone a todas):"))
                for value in sorted(counts, key=lambda v: -counts[v]):
                    extra = f"   ·  {counts[value]}/{len(sel)}" if counts[value] < len(sel) else ""
                    it = QListWidgetItem(labels[value] + extra)
                    it.setData(PATH_ROLE, value)
                    self.sug_list.addItem(it)
            else:
                self.sug_label.setText(T(f"{len(sel)} canciones seleccionadas: pulsa «Sugerir género» o escribe uno abajo "
                                         f"y pulsa «Poner» para ponérselo a todas."))
            return
        cur = self.current_path()
        if cur and cur in self.suggestions:
            left = len(self.unresolved_rows())
            more = f"  (quedan {left} por elegir)" if left else "  ✔ ya elegido"
            self.sug_label.setText(f"Elige el género/subgénero para «{os.path.basename(cur)}»:{more}")
            for label, value in self.suggestions[cur]:
                it = QListWidgetItem(label)
                it.setData(PATH_ROLE, value)
                self.sug_list.addItem(it)
                if self.pending.get(cur, {}).get("genre") == value:
                    it.setSelected(True)
        else:
            self.sug_label.setText("Pulsa «Sugerir género» para ver opciones de esta canción.")

    def put_genre_many(self, paths, genre):
        genre = (genre or "").strip()
        if not genre or not paths:
            return
        self.apply_form()
        for p in paths:
            self.pending.setdefault(p, {})["genre"] = genre
            self.chosen.add(p)
        self.mark_items()
        self.on_select()
        self.statusBar().showMessage(T(f"Género «{genre}» puesto en {len(paths)} canción(es) (pendiente de guardar)."))

    def put_manual_genre(self):
        paths = [p for p in self.cur_paths if p] or ([self.current_path()] if self.current_path() else [])
        if not paths:
            self.statusBar().showMessage("Selecciona una o varias canciones.")
            return
        self.put_genre_many(paths, self.genre_pick.currentText())

    def pick_suggestion(self, item):
        if len(self.cur_paths) > 1:   # varias elegidas: el género va a todas
            self.put_genre_many([p for p in self.cur_paths if p], item.data(PATH_ROLE))
            return
        cur = self.current_path()
        if not cur:
            return
        self.apply_form()  # conserva lo que hayas escrito
        self.pending.setdefault(cur, {})["genre"] = item.data(PATH_ROLE)
        self.chosen.add(cur)
        self.mark_items()
        self.statusBar().showMessage(f"Género «{item.data(PATH_ROLE)}» puesto (pendiente de guardar).")

        def advance():
            rows = self.unresolved_rows()
            cur_row = self.row_index.get(cur, 0)
            nxt = next((r for r in rows if r > cur_row), rows[0] if rows else None)
            if nxt is not None:
                self.go_to_row(nxt)  # pasa a la siguiente canción por elegir
            else:
                self.on_select()

        QTimer.singleShot(0, advance)


class DeleteWorker(QThread):
    """Elimina (a la papelera) en segundo plano: varias carpetas grandes ya no congelan el programa.
    Se manda todo junto a la papelera en una sola operación, que es mucho más rápido que una por una."""
    done = pyqtSignal(int, list)

    def __init__(self, paths, trash):
        super().__init__()
        self.paths, self.trash = paths, trash

    def run(self):
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.ole32.CoInitialize(None)
            except Exception:
                note_quiet()
        ok, errors = 0, []
        todo = [p for p in self.paths if os.path.exists(p)]
        if self.trash and todo:
            try:
                self.trash(todo)   # todo de una vez
                todo = [p for p in todo if os.path.exists(p)]
            except Exception:
                note_quiet()
        for p in todo:   # lo que quede (o sin papelera): uno por uno
            try:
                if self.trash:
                    self.trash(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except Exception as e:
                errors.append(f"{os.path.basename(p)}: {e}")
        ok = sum(1 for p in self.paths if not os.path.exists(p))
        self.done.emit(ok, errors)


class DialogPolish(QObject):
    """Todas las ventanas de herramientas con el mismo aspecto: márgenes amplios y el título arriba en grande."""
    SKIP = ("QMessageBox", "QFileDialog", "QInputDialog", "QProgressDialog", "QColorDialog", "QFontDialog")

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Show and isinstance(obj, QDialog) and obj.isWindow() \
                and not obj.property("_polished") and type(obj).__name__ not in self.SKIP:
            obj.setProperty("_polished", True)
            try:
                self.polish(obj)
            except Exception:
                note_quiet()
        return False

    def polish(self, dlg):
        lay = dlg.layout()
        if lay is None:
            return
        m = lay.contentsMargins()
        if m.left() < 14:
            lay.setContentsMargins(18, 14, 18, 14)
        if lay.spacing() < 8:
            lay.setSpacing(10)
        title = dlg.windowTitle().strip()
        has_head = any(l.objectName() in ("dlgtitle", "title") or "<h" in (l.text() or "")
                       for l in dlg.findChildren(QLabel))
        if title and not has_head and isinstance(lay, QVBoxLayout) and dlg.windowTitle() not in ("Ajustes", T("Ajustes")):
            head = QLabel(title)
            head.setObjectName("dlgtitle")
            lay.insertWidget(0, head)


def error_log_path():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) or \
        os.path.join(os.path.expanduser("~"), ".musicmanager")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "errores.txt")


_last_err = [0.0]


def install_error_guard():
    """Si algo falla dentro del programa, se anota en «errores.txt» y se avisa en la barra de abajo, en vez de
    cerrarse de golpe (PyQt6 cierra el programa ante cualquier error no controlado)."""
    import traceback

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            p = error_log_path()
            if os.path.exists(p) and os.path.getsize(p) > 512 * 1024:   # que no crezca sin fin
                os.replace(p, p + ".old")
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} · versión {APP_VERSION} =====\n{text}")
        except OSError:
            pass
        sys.__stderr__ and sys.__stderr__.write(text)
        try:
            app = QApplication.instance()
            win = next((w for w in app.topLevelWidgets() if isinstance(w, QMainWindow) and w.isVisible()), None)
            if win is not None and time.time() - _last_err[0] > 3:
                _last_err[0] = time.time()
                win.statusBar().showMessage(T("Algo falló, pero el programa sigue funcionando. Detalles en Ayuda → "
                                              "Registro de errores."), 8000)
        except Exception:
            note_quiet()
    sys.excepthook = hook


def tidy_install_folder():
    """fpcalc.exe ahora va escondido dentro de «_internal»: si quedó la copia vieja junto al programa, se borra."""
    if not getattr(sys, "frozen", False):
        return
    here = os.path.dirname(sys.executable)
    old = os.path.join(here, "fpcalc.exe")
    if os.path.isfile(old) and os.path.isfile(os.path.join(getattr(sys, "_MEIPASS", os.path.join(here, "_internal")), "fpcalc.exe")):
        try:
            os.remove(old)
        except OSError:
            pass


if __name__ == "__main__":
    if os.environ.get("MM_SELFTEST"):   # comprobación al compilar: que el EXE trae lo necesario (no abre ventanas)
        res = []
        for mod in ("winrt.windows.media.playback", "winrt.windows.media", "winrt.windows.storage.streams",
                    "smtc", "miniplayer", "changelog", "secret"):
            try:
                __import__(mod)
                res.append(f"OK {mod}")
            except Exception as e:
                res.append(f"FALLA {mod}: {type(e).__name__}: {e}")
        with open(os.environ["MM_SELFTEST"], "w", encoding="utf-8") as fh:
            fh.write("\n".join(res))
        sys.exit(0)
    install_error_guard()
    tidy_install_folder()
    _polish = DialogPolish()
    if sys.platform == "win32":
        try:  # para que Windows muestre el icono propio en la barra de tareas
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MusicManager.App")
        except Exception:
            note_quiet()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Music Manager")
    i18n.install_hooks()
    _wheel = DragWheelFilter()
    app.installNativeEventFilter(_wheel)
    _deco = icons.IconDeco(app)
    app.installEventFilter(_deco)
    app.installEventFilter(_polish)
    # una sola ventana del programa: si ya estaba abierto, aquel se cierra y se abre este de nuevo
    _server = None
    try:
        from PyQt6.QtNetwork import QLocalServer, QLocalSocket
        _name = "MusicManager-unica-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "yo")
        _old = QLocalSocket()
        _old.connectToServer(_name)
        if _old.waitForConnected(400):
            _old.write(b"cerrar")
            _old.flush()
            _old.waitForBytesWritten(1000)
            _old.disconnectFromServer()
            _t0 = time.time()
            while time.time() - _t0 < 20:   # espera a que el anterior termine de cerrarse (por si pregunta si guardar)
                _chk = QLocalSocket()
                _chk.connectToServer(_name)
                if not _chk.waitForConnected(200):
                    break
                _chk.disconnectFromServer()
                app.processEvents()
                time.sleep(0.3)
        QLocalServer.removeServer(_name)
        _server = QLocalServer()
        _server.listen(_name)
    except Exception:
        _server = None
    w = Main()

    def _other_instance():
        c = _server.nextPendingConnection()
        if c is None:
            return
        c.waitForReadyRead(500)
        if bytes(c.readAll()).startswith(b"cerrar"):
            QTimer.singleShot(0, w.close)

    if _server is not None:
        _server.newConnection.connect(_other_instance)
    try:   # botones anterior / play / siguiente en la miniatura de la barra de tareas
        import taskbar
        w.taskbar = taskbar.TaskbarButtons(w, icons.draw_glyph)
        app.installNativeEventFilter(w.taskbar)
    except Exception:
        w.taskbar = None
    w.show()
    sys.exit(app.exec())

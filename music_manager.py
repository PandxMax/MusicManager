#!/usr/bin/env python3
"""
Music Manager: explorador de carpetas (arrastrar y soltar) + editor de metadatos
(con portada y letra) + sugerencia de géneros/subgéneros con Claude, ChatGPT o Gemini.

Instalación:   pip install PyQt6 mutagen send2trash
Ejecutar:      python music_manager.py
"""
import sys, os, json, re, shutil, time, base64, html, urllib.request, urllib.error, urllib.parse
from functools import lru_cache
from urllib.parse import quote_plus, quote

from PyQt6.QtCore import (QCoreApplication, Qt, QSettings, QThread, pyqtSignal, QMimeData, QUrl, QSize,
                          QTimer, QRectF, QStandardPaths, QPropertyAnimation, QEasingCurve, QPoint, QRect, QBuffer, QByteArray, QIODevice, QEvent, QPointF)
from PyQt6.QtGui import (QAction, QColor, QBrush, QIcon, QPixmap, QPainter, QImage,
                         QFont, QDesktopServices, QShortcut, QKeySequence, QDrag, QPalette, QLinearGradient, QPainterPath, QPolygonF, QCursor, QMouseEvent, QPen)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem, QListView, QAbstractItemView, QVBoxLayout,
    QHBoxLayout, QGridLayout, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QComboBox, QGroupBox, QCheckBox, QFileDialog, QMessageBox,
    QInputDialog, QGraphicsDropShadowEffect, QToolTip, QStackedWidget, QStyle, QStyleOptionSlider, QHeaderView, QMenu, QToolBar, QTabWidget, QColorDialog, QSizePolicy, QScrollArea, QFileIconProvider, QFrame, QSlider, QDialog, QTextBrowser, QProgressDialog, QLayout, QRubberBand, QSplashScreen, QToolButton,
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
PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole.value + 1
THUMB, COVER = 96, 200
THUMB_GEN = 160   # las miniaturas se generan a este tamaño para que se vean nítidas al agrandarlas
APP_VERSION = "1.49"


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
        pass
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
    out = {"codec": "—", "enc": "—", "enc_full": "", "tag": "—", "bitrate": "—", "freq": "—", "dur": "—", "mode": "—", "size": "—"}
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
        bm = getattr(i, "bitrate_mode", None)
        if bm is not None and str(bm).split(".")[-1] not in ("UNKNOWN", "0"):
            out["mode"] = str(bm).split(".")[-1]
        elif out["codec"] in ("FLAC", "ALAC"):
            out["mode"] = "Sin pérdida"
    except Exception:
        pass
    return out


def tech_info(path):
    try:
        m = os.path.getmtime(path)
    except OSError:
        m = 0
    return _tech(path, m)


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
        pass
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
                    pass
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
QToolButton#langbtn { background: transparent; border: 1px solid @border; border-radius: 8px; padding: 3px 8px; font-weight: 600; }
QToolButton#langbtn:hover { border-color: @accent; background: @accent_soft; }
QToolButton#langbtn::menu-indicator { image: none; width: 0px; }
QToolBar QLineEdit { min-width: 200px; }
QLabel#title { font-size: 15px; font-weight: 700; }
QLabel#hint { color: @muted; font-size: 11px; }
QLabel#techchip { background: @surface2; border: 1px solid @border; border-radius: 9px; padding: 1px 6px; font-size: 10px; }
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
QMenu { background: @surface; border: 1px solid @border; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 24px; border-radius: 6px; }
QMenu::item:selected { background: @accent; color: white; }
QMenu::item:disabled { color: @muted; }
QMenu::separator { height: 1px; background: @border; margin: 4px 8px; }
QToolTip { background: @surface2; color: @text; border: 1px solid @border; padding: 4px 6px; }
QDialog { background: @window; }
"""


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
        pass
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


CHANGELOG = [
    ('1.49', [
        'El archivo .lrc (copia de la letra sincronizada junto a la canción) ya no se crea por defecto. Quien lo quiera puede activarlo en Ajustes → Etiquetas. La letra sigue guardándose dentro de la canción.',
    ]),
    ('1.48', [
        'Descargas de YouTube / SoundCloud: ya no quedan archivos sueltos sin icono junto al MP3 (el audio original, .part o .ytdl). Se borran solos al terminar o si la descarga falla.',
    ]),
    ('1.47', [
        'Inglés y ruso mucho más completos: ahora se traducen también los textos que cambian mientras usas el programa (letra, análisis del espectrograma, comparación, portadas, fuentes de etiquetas, avisos con nombres y cantidades…).',
        'Si usas la IA sin clave, aparece una guía paso a paso para conseguir gratis una clave de Gemini, con un botón que abre la página de Google y otro para pegarla.',
    ]),
    ('1.46', [
        'Nuevo selector de idioma con banderitas arriba a la derecha: cambia entre Español, English y Русский al instante, sin reiniciar.',
        'Mucho más traducido al inglés y al ruso: ventanas de IA, ajustes de la canción, descargas, espectrograma, portadas, listas de reproducción, avisos, mensajes de la barra de estado, guía rápida y «Acerca de».',
        'Los botones «Sí / No / Aceptar / Cancelar» de los avisos ahora salen en el idioma elegido (antes salían en inglés).',
    ]),
    ('1.45', [
        '«Rellenar con IA» ahora rellena todos los campos: título, intérprete, álbum, intérprete del álbum, compositor, género, año, pista, número de disco y comentario (sello, productor…).',
        'Antes de preguntar a la IA busca la canción en iTunes y Deezer, así el álbum, el año, la pista y el disco salen del catálogo real y no adivinados.',
        'Corregido: la pista y el número de disco a veces no se rellenaban.',
    ]),
    ('1.44', [
        'Se quitó la pantalla de carga del panda: el programa se abre directamente.',
    ]),
    ('1.43', [
        'Más fluido: las portadas de la lista se cargan en segundo plano, así la ventana ya no se traba mientras aparecen.',
        'Las miniaturas se guardan en caché: volver a una carpeta que ya abriste es casi instantáneo.',
        'Para no ocupar espacio, cada hora se borran solas las miniaturas que no se usaron en la última hora.',
    ]),
    ('1.42', [
        'Logo rediseñado con un estilo más profesional: panda con auriculares y ondas de sonido sobre fondo oscuro, en los colores del programa.',
        'La pantalla de carga usa el mismo estilo nuevo.',
    ]),
    ('1.41', [
        'Nuevo logo: un panda con auriculares escuchando música (también en el icono del programa).',
        'Nueva pantalla de carga animada: el panda abre una carpeta y van saliendo canciones volando mientras el programa se prepara.',
    ]),
    ('1.40', [
        'El programa pesa menos: se quitaron archivos que no se usaban (OpenGL por software, visor de PDF de Qt, OpenSSL duplicado, traducciones de Qt y formatos de imagen raros) y el componente de descargas ya no incluye su código fuente suelto.',
    ]),
    ('1.39', [
        'Nuevo botón «Ajustes de la canción» junto al reproductor (también en Herramientas): graves, medios, agudos, volumen, normalizar, tempo, tono, velocidad (tasa), recorte, bucle (repetir), al revés, eco, reverberación, ancho estéreo, mono, quitar la voz y entrada/salida gradual.',
        'Puedes escuchar una muestra de 30 s con los ajustes antes de guardar, y guardarla como canción nueva «(editada)» o reemplazar la original. Se conservan las etiquetas y la portada (MP3, M4A, MP4 y FLAC).',
        'Botones de verdad: los emojis de los botones, menús y del reproductor (guardar, atrás/adelante, actualizar, volumen, IA, buscar, descargar…) se sustituyen por iconos dibujados que siguen el tema y el color del programa.',
    ]),
    ('1.38', [
        'Portadas: además de iTunes y Deezer, ahora también se buscan en SoundCloud (aparecen como opción para elegir).',
        'Herramientas → «Descargar de YouTube / SoundCloud a MP3»: ahora también acepta enlaces de SoundCloud.',
        'Deezer: no se pueden descargar canciones completas (están protegidas con DRM); si pegas un enlace de Deezer el programa te lo explica en vez de fallar.',
    ]),
    ('1.37', [
        'Metadatos más compactos y estables: las etiquetas técnicas son más pequeñas y tienen su sitio reservado (los campos ya no bajan ni suben), y el botón de guardar es solo el icono 💾, pegado a la derecha.',
        'La rueda del ratón ya no desplaza toda la ventana.',
        'La ventana de cambios sin guardar ahora pregunta solo «¿Desea guardar los cambios?» con Sí / No.',
    ]),
    ('1.36', [
        'Metadatos: ahora son los mismos que ves en las propiedades de Windows: Título, Intérprete, Álbum, Intérprete del álbum, Compositor, Género, Año, Pista, Número de disco y Comentario, más el Directorio (solo lectura). Se quitó BPM.',
    ]),
    ('1.35', [
        'Datos técnicos: ahora también se ve la etiqueta que usa el archivo (ID3v2.3, ID3v2.4, Vorbis Comment, MP4…) y el codec con detalle (por ejemplo «MPEG-1 Layer III · LAME 3.100» o «AAC-LC»).',
    ]),
    ('1.34', [
        'Nuevo botón «✨ Rellenar metadatos con IA…» debajo de los metadatos: pide el nombre de la canción y el artista, la IA busca los datos (álbum, género, año, pista…) y los rellena. Antes de aplicar puedes revisarlos y corregirlos.',
    ]),
    ('1.33', [
        'Portada: la etiqueta con formato y tamaño (JPEG · 600×600 px · 93 KB) ya no se pega ni tapa la imagen; tiene su propio espacio debajo.',
        'Vuelve «Herramientas → Descargar de YouTube a MP3» (se había quitado por error en la 1.29).',
        'Árboles de carpetas: al mover archivos o carpetas ya no se abre solo el 2.º árbol ni aparece la fila «…»; cada árbol conserva exactamente lo que tenías abierto.',
    ]),
    ('1.32', [
        'En «Acerca de» ahora aparece el creador: PandxMax.',
    ]),
    ('1.31', [
        'Metadatos: las etiquetas técnicas (formato, bitrate, frecuencia, duración, modo, tamaño) se ven siempre, también sin canción seleccionada, así nada salta de sitio.',
        'El botón «Guardar» ahora está en la cabecera de los metadatos (arriba a la derecha) y solo se activa cuando hay cambios.',
    ]),
    ('1.30', [
        'Metadatos: los campos quedan pegados a las etiquetas técnicas (sin hueco en medio); el espacio sobrante queda abajo.',
        'El botón «Guardar» ahora está al costado derecho de la portada (aparece solo cuando hay cambios).',
    ]),
    ('1.29', [
        'Se quitó «Reparar portadas»: ahora basta con guardar. Cada vez que guardas un MP3 queda en el formato que el Explorador de Windows entiende.',
        'Las portadas en FLAC se guardan con sus medidas (ancho, alto y profundidad) para que Windows las muestre como miniatura.',
    ]),
    ('1.28', [
        'Arreglo importante: los MP3 ahora se guardan en ID3v2.3 con texto UTF-16 (el formato que entiende el Explorador de Windows). Antes la portada se guardaba bien, pero Windows no la mostraba como miniatura.',
    ]),
    ('1.27', [
        'Nuevo botón ⟳ «Actualizar» junto a atrás/adelante/subir, y clic derecho en el espacio en blanco → «Actualizar» (también F5), para que aparezcan las canciones que añades desde fuera.',
        'Herramientas → «Descargar de YouTube a MP3»: pega el enlace, descarga el audio y se selecciona en la lista para ponerle metadatos y portada.',
    ]),
    ('1.26', [
        'Se quitaron los botones «Deshacer cambios» y «Guardar cambios» de los metadatos.',
        'Cuando hay un cambio en el archivo aparece un botón «Guardar» encima de la portada (y desaparece al guardar).',
        'Si cambias a otra canción (o carpeta) con cambios sin guardar, sale una ventana para guardar, descartar o quedarte.',
    ]),
    ('1.25', [
        'Al guardar, el programa avisa al Explorador de Windows para que refresque el icono y muestre la portada del archivo.',
        'Los archivos .mp4 de solo audio no muestran portada en Windows: al guardar una portada, el programa ofrece renombrarlos a .m4a (es el mismo archivo y así Windows sí muestra la imagen).',
    ]),
    ('1.24', [
        'El programa abre más rápido: aparece una pantalla de carga al instante y lo pesado (reproductor, comprobar actualizaciones, guía) se carga después de mostrar la ventana.',
        'El ejecutable es más ligero (se quitaron módulos que no se usan), así que arranca antes.',
    ]),
    ('1.23', [
        'Comparación: ahora puedes arrastrar canciones o carpetas de cualquier lugar (del explorador de Windows o de las listas del programa) para añadirlas y compararlas.',
        'Debajo de la portada hay botones para buscar la canción en YouTube, Spotify, Tidal, Qobuz y Wikipedia.',
    ]),
    ('1.22', [
        'Al arrastrar archivos o carpetas ya no aparece el signo de «prohibido», y la carpeta que tienes debajo se resalta para soltar encima.',
    ]),
    ('1.21', [
        'La división entre la lista y la portada (y entre metadatos y géneros) ya no se puede mover: se queda quieta.',
        'Con los metadatos a la vista, la fila de abajo tiene siempre el mismo tamaño y posición; al cerrar el espectrograma vuelve exactamente al mismo sitio.',
        'Sin canción seleccionada, los campos de metadatos aparecen vacíos con una sola línea «-» y se rellenan al elegir una canción.',
    ]),
    ('1.20', [
        'Con los metadatos a la vista, la barra roja para estirar la fila de abajo ya no aparece (solo se puede estirar con el espectrograma abierto).',
        'Corregido: ahora sí se puede arrastrar un archivo o carpeta sobre otra carpeta de la misma lista; la carpeta de destino se resalta al pasar por encima.',
    ]),
    ('1.19', [
        'Corregido: tras arrastrar archivos y soltarlos en el mismo sitio, ya no queda el recuadro de selección fantasma ni la selección «pegada».',
        'Corregido: se puede soltar carpetas y archivos sobre otra carpeta dentro de la misma lista.',
        'Corregido: la pestaña Comparación del espectrograma ahora se desplaza y se puede ver completa, aunque la ventana sea pequeña.',
    ]),
    ('1.18', [
        'El espectrograma ocupa toda la fila de abajo (también bajo la portada) y la portada se queda arriba a la derecha, sin estirarse.',
        'Ctrl + rueda del ratón sobre los archivos cambia su tamaño, de grandes a pequeños (en vista de iconos y de lista).',
    ]),
    ('1.17', [
        'Los botones Espectro, MusicBrainz y Discogs pasaron a la derecha de la barra de la lista.',
        'Los botones del reproductor (lista, anterior, siguiente y detener) ahora están dibujados con el color del programa y cambian junto con el botón de reproducir.',
    ]),
    ('1.16', [
        'Los botones Espectro, MusicBrainz y Discogs ahora están arriba, a la izquierda, junto a las flechas de navegación; ya no ocupan lugar en los metadatos.',
    ]),
    ('1.15', [
        'Datos técnicos más ordenados: las etiquetas a la izquierda y los botones Espectro / MusicBrainz / Discogs siempre juntos a la derecha.',
        'Panel de portada más compacto: botones más pequeños, menos espacio vacío y la columna derecha un poco más angosta.',
    ]),
    ('1.14', [
        'Corregido: la ventana ya no se sale de la pantalla ni se corta por los lados (se ajusta al tamaño de tu pantalla al abrir).',
        'La fila de datos técnicos y los botones (Espectro, MusicBrainz, Discogs) pasa a otra línea cuando no cabe, en vez de ensanchar la ventana.',
        'Si aun así la ventana es muy pequeña, aparecen barras de desplazamiento en lugar de cortar el contenido.',
    ]),
    ('1.13', [
        'Junto a «📊 Espectro» hay ahora dos botones, «🎼 MusicBrainz» y «💿 Discogs», para buscar y poner las etiquetas de la canción.',
    ]),
    ('1.12', [
        'Al actualizar, aparece una pantallita con las novedades de la versión (Ayuda ▸ «Novedades de esta versión» para verla cuando quieras).',
    ]),
    ('1.11', [
        'Actualización automática más robusta: descomprime antes de cerrar, cierra el proceso por completo, reintenta si hay archivos en uso y avisa al abrir si salió bien o mal.',
    ]),
    ('1.10', [
        'Clic derecho en el artista: ahora también «Buscar en Tidal» y «Buscar en Qobuz».',
    ]),
    ('1.09', [
        'Volumen: la barra aparece hacia arriba, flotando (no mueve nada).',
        'Botón flotante ☰ al costado: despliega por encima de portada, géneros y letra la lista de reproducción; arriba muestra lo que suena ahora, y puedes arrastrar canciones y crear/guardar listas con nombre.',
        'Cuadritos de fondo en la barra de posición que bailan con el ritmo real de la canción y caen al detenerla.',
    ]),
    ('1.08', [
        'Actualización desde el propio programa: Ayuda ▸ «Buscar actualizaciones…» descarga la versión nueva y se reemplaza sola (también avisa al abrir).',
    ]),
    ('1.07', [
        '✨ Portada automática: muestra varias opciones (iTunes y Deezer) para elegir; Google Imágenes solo si no hay ninguna.',
        'Volumen en una sola barrita que se despliega al pasar el ratón, y un disco que gira con la portada que suena.',
        'Metadatos: solo «Deshacer cambios» y «Guardar cambios»; se quitó la palabra «Portada» sobre la imagen.',
        'Lista de reproducción propia: arrastra canciones o carpetas, ordénalas, guárdala o cárgala (.m3u8). «Reproducir carpeta» con clic derecho. Canciones separadas y legibles.',
        'El espectrograma aparece solo en el panel de abajo (no agranda la ventana).',
    ]),
    ('1.06', [
        'El espectrograma, la comparación y el análisis de calidad ahora reemplazan a los metadatos y la letra en la misma ventana; un botón «Volver» los recupera.',
        'Reproductor: botones de lista de reproducción, anterior, siguiente y detener junto a reproducir.',
        'Los colores del programa se adaptan a la portada de la canción que suena (se puede desactivar en Ver).',
        'Si no se encuentra una portada, se abre Google Imágenes con «artista título portada» y el programa ofrece ponerla al copiar la imagen.',
    ]),
    ('1.05', [
        'Botón ✨ de portada automática: busca en iTunes y Deezer la portada en alta calidad (hasta 1200 px) y la pone sola en las canciones seleccionadas.',
    ]),
    ('1.04', [
        'Géneros y Letra comparten el panel derecho con dos botones: se acabó el desbordamiento lateral de la ventana.',
    ]),
    ('1.03', [
        'El panel de carpetas ya no se puede aplastar al abrir la letra.',
        'LRCLIB: reintentos automáticos si el servicio está saturado (error 503).',
        'Panel de portada más cuidado: esquinas redondeadas, sombra y botones con iconos.',
        'Botón «📊 Espectro» junto a los datos técnicos de la canción.',
    ]),
    ('1.02', [
        'Letras sincronizadas desde LRCLIB (con los minutos de cada línea y archivo .lrc); se quitó la letra con IA.',
        'Botones de portada (cambiar, guardar, quitar, ver) y datos de la imagen.',
        'Se quitaron títulos y textos repetidos del panel de metadatos y de la portada.',
    ]),
    ('1.01', [
        'Menús en lugar de barra de herramientas; reproductor compacto en la línea de estado.',
        'Botones atrás / adelante / subir para navegar por las carpetas.',
        'Árboles de carpetas con barra horizontal, destino resaltado y copiar con Ctrl.',
        'Espectrograma y análisis de calidad (comparación de varias canciones).',
        'Convertir formatos: MP3, FLAC, M4A, OGG, Opus y WAV.',
        'Fuentes de etiquetas: MusicBrainz y Discogs.',
        'Información técnica del archivo (códec, tasa de bits, frecuencia…).',
        'Clic derecho en el artista: Wikipedia, YouTube, Spotify, Tidal y Qobuz.',
        'Ajustes con categorías, tema y color de acento, y 3 idiomas (ES / EN / RU).',
        'Volumen: silenciar, rueda del ratón y globos con el minuto y el volumen.',
    ]),
    ('1.0', [
        'Explorador con arrastrar y soltar entre dos árboles.',
        'Editor de etiquetas, portadas (copiar, pegar, redimensionar) y letras.',
        'IA (Claude, ChatGPT, Gemini) para géneros y letras.',
        'Reproductor integrado y búsqueda en YouTube.',
    ]),
]


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
                    "url": asset["browser_download_url"] if asset else "", "size": asset.get("size", 0) if asset else 0}
        except urllib.error.HTTPError as e:
            info = {"ok": e.code == 404, "none": e.code == 404, "error": f"GitHub respondió {e.code}"}
        except Exception as e:
            info = {"ok": False, "error": str(getattr(e, "reason", e))}
        self.result.emit(info)


class UpdateDownloadWorker(QThread):
    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, url, dest):
        super().__init__()
        self.url, self.dest = url, dest

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
            self.done.emit(self.dest)
        except Exception as e:
            self.failed.emit(str(getattr(e, "reason", e)))


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
    UA = "MusicManager/1.49 (https://github.com/PandxMax/MusicManager)"

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
                    pass
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


class LrclibWorker(QThread):
    """Busca letras en LRCLIB (https://lrclib.net), gratis y sin clave. Prefiere la letra sincronizada."""
    got = pyqtSignal(str, str)  # ruta, letra ("" si no hubo)
    finished_all = pyqtSignal()
    failed = pyqtSignal(str)
    UA = "MusicManager/1.05 (https://github.com/PandxMax/MusicManager)"

    def __init__(self, jobs, prefer_synced=True):
        super().__init__()
        self.jobs, self.prefer_synced = jobs, prefer_synced  # jobs: [(ruta, artista, título, álbum, segundos)]

    def fetch(self, url):
        """Pide una dirección con reintentos (LRCLIB a veces responde 503 / 429 por saturación)."""
        req = urllib.request.Request(url, headers={"User-Agent": self.UA})
        last = ""
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                last = f"LRCLIB respondió «{e.reason}» ({e.code})"
                if e.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = f"No hay conexión con LRCLIB ({getattr(e, 'reason', e)})"
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(last + ". El servicio puede estar saturado: inténtalo de nuevo en unos minutos.")

    def pick(self, d):
        if not d or d.get("instrumental"):
            return ""
        synced, plain = d.get("syncedLyrics") or "", d.get("plainLyrics") or ""
        return (synced or plain) if self.prefer_synced else (plain or synced)

    def find(self, artist, title, album, dur):
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
        if self.prefer_synced:
            res.sort(key=lambda r: not r.get("syncedLyrics"))
        for r in res:
            text = self.pick(r)
            if text:
                return text
        return ""

    def run(self):
        errors, last = 0, ""
        for path, artist, title, album, dur in self.jobs:
            try:
                self.got.emit(path, self.find(artist, title, album, dur))
            except Exception as e:  # una canción que falla no cancela las demás
                errors += 1
                last = str(e)
                self.got.emit(path, "")
        if errors and errors == len(self.jobs):
            self.failed.emit(last)
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
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)

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

    def refresh(self):
        exp = {it.data(0, PATH_ROLE) for it in self.all_items() if it.isExpanded()}
        cur = self.currentItem()
        curp = cur.data(0, PATH_ROLE) if cur else None
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

    def __init__(self, provider, model, key, title, artist):
        super().__init__(provider, model, key)
        self.title, self.artist = title, artist

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
        except Exception:
            pass
        if not out.get("album"):
            try:
                q = quote_plus(f'artist:"{self.artist}" track:"{self.title}"' if self.artist else self.title)
                d = self._get(f"https://api.deezer.com/search?q={q}&limit=5")
                hit = (d.get("data") or [None])[0]
                if hit:
                    tr = self._get(f"https://api.deezer.com/track/{hit['id']}")
                    out.update({k: v for k, v in {
                        "title": tr.get("title", ""), "artist": (tr.get("artist") or {}).get("name", ""),
                        "album": (tr.get("album") or {}).get("title", ""),
                        "albumartist": (tr.get("artist") or {}).get("name", ""),
                        "date": (tr.get("release_date") or "")[:4],
                        "tracknumber": str(tr.get("track_position") or ""),
                        "discnumber": str(tr.get("disk_number") or "")}.items() if v and not out.get(k)})
            except Exception:
                pass
        return {k: v for k, v in out.items() if v}

    def run(self):
        found = self.catalog()
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
        if not data and err:
            self.failed.emit(err)
        else:
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
            le = QLineEdit()
            self.res[k] = le
            rf.addRow(n, le)
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
        self.status.setText("Buscando en iTunes/Deezer y con la IA…")
        prov, model, key = self.settings
        self.worker = MetaAIWorker(prov, model, key, t, a)
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
        for k, le in self.res.items():
            le.setText(data.get(k, ""))
        self.res_box.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.status.setText("Revisa los datos. Solo se aplican los campos que no estén vacíos.")

    def apply(self):
        vals = {k: le.text().strip() for k, le in self.res.items() if le.text().strip()}
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
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.overlay.setGeometry(self.viewport().rect())

    def mimeData(self, items):
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(i.data(PATH_ROLE)) for i in items])
        return md

    def reset_state(self):
        """Tras un arrastre propio, Qt puede quedarse «seleccionando» (recuadro fantasma y selección pegada). Lo limpia."""
        try:
            self.setState(QAbstractItemView.State.NoState)
        except Exception:
            pass
        for rb in self.findChildren(QRubberBand):
            rb.hide()
        self._selecting = False
        self.viewport().update()

    # ---- iniciar el arrastre
    def mousePressEvent(self, e):
        if not (QApplication.mouseButtons() & ~Qt.MouseButton.LeftButton) and self.state() != QAbstractItemView.State.NoState:
            self.reset_state()
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position().toPoint()
            self._press_item = self.itemAt(self._press)
            self._selecting = True
        else:
            self._press, self._press_item = None, None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press is not None and self._press_item is not None
                and e.buttons() & Qt.MouseButton.LeftButton
                and (e.position().toPoint() - self._press).manhattanLength() >= QApplication.startDragDistance()):
            item, self._press, self._press_item = self._press_item, None, None
            self.begin_drag(item)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press, self._press_item = None, None
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
            result = drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)
            hover_timer.stop()
            if result == Qt.DropAction.IgnoreAction:   # Qt no aceptó el soltar: lo resolvemos nosotros
                lp = self.viewport().mapFromGlobal(QCursor.pos())
                it = self._dir_at(lp) if self.viewport().rect().contains(lp) else None
                if it is not None and it.data(PATH_ROLE) not in paths:
                    self.dropped.emit(paths, it.data(PATH_ROLE))
        finally:
            hover_timer.stop()
            self._selecting = False
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
        self.thumbs = thumbs.ThumbWorker(THUMB_GEN, inspect_file, read_tags, find_folder_image)
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
                pass
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
        self.search.textChanged.connect(self.apply_filter)
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
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setUniformItemSizes(True)
        self.sel_timer = QTimer(self)
        self.sel_timer.setSingleShot(True)
        self.sel_timer.setInterval(150)
        self.sel_timer.timeout.connect(self.on_select)
        self.list.itemSelectionChanged.connect(self.schedule_select)
        self.list.selection_done.connect(self.on_select)
        self.list.dropped.connect(self.defer_move)
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
        tbl = FlowLayout(chips_w, 4, 4)
        tbl.setContentsMargins(0, 0, 0, 0)
        for k in ("codec", "enc", "tag", "bitrate", "freq", "dur", "mode", "size"):
            chip = QLabel("")
            chip.setObjectName("techchip")
            self.tech[k] = chip
            tbl.addWidget(chip)
        self.fill_tech([])
        tb_l.addWidget(chips_w, 1, Qt.AlignmentFlag.AlignTop)
        self.save_btn = QPushButton("💾")
        self.save_btn.setObjectName("accent")
        self.save_btn.setToolTip("Guardar cambios (Ctrl+S)")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setFixedSize(34, 26)
        self.save_btn.clicked.connect(self.save_all)
        self.save_btn.setEnabled(False)
        tb_l.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.tech_bar.setFixedHeight(52)      # sitio para dos filas de etiquetas: nada de lo de abajo sube ni baja
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
        self.btn_lyr = QPushButton("🔎 Buscar letra en LRCLIB (sincronizada)")
        self.btn_lyr.clicked.connect(self.run_lyrics)
        lv.addWidget(self.btn_lyr)

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
        for src, text, tip in (("spec", "📊 Espectro", "Espectrograma y análisis de calidad de las canciones seleccionadas"),
                               ("musicbrainz", "🎼 MusicBrainz", "Buscar las etiquetas de esta canción en MusicBrainz (gratis)"),
                               ("discogs", "💿 Discogs", "Buscar las etiquetas de esta canción en Discogs (necesita tu token)")):
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
        lpv.addLayout(navbar)
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
        ch.addStretch(1)
        ch.addLayout(left)
        ch.addWidget(self.cover_lbl)
        ch.addStretch(1)
        cv.setContentsMargins(6, 4, 6, 4)
        cv.setSpacing(3)
        cv.addLayout(ch)
        cv.addSpacing(8)
        self.info_lbl.setFixedHeight(24)
        sp_i = self.info_lbl.sizePolicy()
        sp_i.setRetainSizeWhenHidden(True)      # su sitio queda reservado: la portada no se mueve ni se tapa
        self.info_lbl.setSizePolicy(sp_i)
        cv.addWidget(self.info_lbl, 0, Qt.AlignmentFlag.AlignHCenter)
        self.status_lbl.hide()
        cover_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

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
        self.btn_chat = QPushButton("💬 Hablar con la IA sobre este género")
        self.btn_chat.clicked.connect(self.open_chat)
        for w in (self.btn_ai, self.sug_label, self.sug_list, self.btn_chat):
            av.addWidget(w)
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
        web_w = QWidget()
        web_l = FlowLayout(web_w, 6, 6)
        web_l.setContentsMargins(6, 8, 6, 0)
        for kind, label, tip in (("youtube", "▶ YouTube", "Buscar esta canción en YouTube"),
                                 ("spotify", "🟢 Spotify", "Buscar esta canción en Spotify"),
                                 ("tidal", "🌊 Tidal", "Buscar esta canción en Tidal"),
                                 ("qobuz", "🎧 Qobuz", "Buscar esta canción en Qobuz"),
                                 ("wiki", "📖 Wikipedia", "Buscar esta canción o artista en Wikipedia")):
            wb = QPushButton(label)
            wb.setObjectName("tabbtn")
            wb.setCursor(Qt.CursorShape.PointingHandCursor)
            wb.setToolTip(tip)
            wb.clicked.connect(lambda _=False, k=kind: self.web_song(k))
            web_l.addWidget(wb)
        cvw.addWidget(web_w)
        cvw.addStretch(1)
        coverw.setMinimumWidth(330)
        self.cover_col = coverw

        top_split = QSplitter(Qt.Orientation.Horizontal)       # fila de arriba: lista | portada
        top_split.addWidget(self.list_pane)
        top_split.addWidget(coverw)
        bottom_split = QSplitter(Qt.Orientation.Horizontal)    # fila de abajo: metadatos | géneros/letra
        bottom_split.addWidget(bottom)
        bottom_split.addWidget(rightlow)
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
        middle = QSplitter(Qt.Orientation.Vertical)
        middle.addWidget(top_split)
        middle.addWidget(self.bottom_stack)
        middle.setCollapsible(0, False)
        middle.setCollapsible(1, False)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 1)
        middle.setSizes([430, 300])

        main = QSplitter()
        main.addWidget(self.left_split)
        main.addWidget(middle)
        main.setStretchFactor(1, 1)
        self.left_split.setMinimumWidth(210)
        for i in range(2):
            main.setCollapsible(i, False)
        main.setSizes([280, 1230])
        self.main_split, self.mid_split = main, middle
        for sp in (main, middle, top_split, bottom_split, self.left_split):
            self.style_splitter(sp)
        self.set_rows_locked(True)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        sa = NoWheelScroll()          # si la ventana es muy pequeña, aparecen barras en vez de cortar el contenido
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        sa.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        sa.setWidget(main)
        cl.addWidget(sa, 1)
        self.setCentralWidget(central)
        self.build_pl_panel(central)
        self.statusBar().addPermanentWidget(self.player_bar)   # reproductor en la línea de estado, a la derecha
        self.statusBar().setSizeGripEnabled(False)
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
            pass

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
        return w

    def pinned(self):
        try:
            return json.loads(self.cfg.value("pinned", "[]"))
        except Exception:
            return []

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

    def toggle_tree2(self, on):
        self.tree2_box.setVisible(on)
        self.cfg.setValue("tree2", 1 if on else 0)
        if on:
            self.left_split.setSizes([400, 400])
        elif self.active_tree is self.tree2:
            self.active_tree = self.tree
        self.statusBar().showMessage(
            "Segundo árbol activado: arrastra carpetas de un árbol al otro." if on else "Segundo árbol oculto.")

    def on_tree_current(self, tree, cur):
        if cur is None:
            return
        self.active_tree = tree
        self.load_folder(cur.data(0, PATH_ROLE))

    def on_tree_click(self, tree, item):
        self.active_tree = tree
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
            try:
                os.makedirs(os.path.join(base, name.strip()), exist_ok=False)
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))
                return
            self.refresh_trees()

    def rename_folder(self, path):
        if self.is_protected(path):
            QMessageBox.information(self, "Carpeta principal", "Las carpetas principales no se pueden renombrar.")
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

    def rename_tree_current(self, tree):
        it = tree.currentItem()
        if it is not None and it.data(0, PATH_ROLE):
            self.rename_folder(it.data(0, PATH_ROLE))

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
        """Windows bloquea el archivo que se está reproduciendo: lo suelta antes de tocarlo."""
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

    def move_items(self, paths, target):
        target = os.path.normpath(target)
        moved, errors = 0, []
        for src in paths:
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
                self.release_if([src])
                shutil.move(src, dst)
                moved += 1
                if os.path.isfile(dst):
                    self.retarget(src, dst)
            except Exception as e:
                errors.append(f"{name}: {e}")
        self.statusBar().showMessage(f"{moved} elemento(s) movido(s) a {target}")
        if errors:
            QMessageBox.warning(self, "Algunos elementos no se movieron", "\n".join(errors))
        QApplication.processEvents()
        self.after_fs_change()

    def reload_all(self):
        find_folder_image.cache_clear()
        self.meta.clear()
        self.tags_cache.clear()
        self.refresh_trees()
        self.load_folder(self.current_dir)

    # ---------------------------------------------------- Lista de canciones
    def toggle_view(self):
        self.set_view(not self.icons_mode)

    def set_view(self, icons):
        self.icons_mode = icons
        if icons:
            self.list.setViewMode(QListView.ViewMode.IconMode)
            self.list.setIconSize(QSize(self.icon_px, self.icon_px))
            self.list.setGridSize(QSize(self.icon_px + 38, self.icon_px + 60))
            self.list.setSpacing(6)
            self.list.setWordWrap(True)
            self.act_view.setText("☰ Lista"); i18n.deco(self.act_view)
        else:
            self.list.setViewMode(QListView.ViewMode.ListMode)
            self.list.setIconSize(QSize(self.list_px, self.list_px))
            self.list.setGridSize(QSize())
            self.list.setSpacing(2)
            self.list.setWordWrap(False)
            self.act_view.setText("🔳 Iconos"); i18n.deco(self.act_view)
        self.list.setMovement(QListView.Movement.Static)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(48)

    def eventFilter(self, obj, ev):
        # botones laterales del ratón = atrás / adelante, como en el Explorador
        if obj is self.centralWidget() and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.layout_overlay()
        if obj is self.list.viewport() and ev.type() == QEvent.Type.Wheel and (ev.modifiers() & Qt.KeyboardModifier.ControlModifier):
            d = ev.angleDelta().y()
            if d:
                step = 12 if self.icons_mode else 4
                if self.icons_mode:
                    self.icon_px = max(40, min(160, self.icon_px + (step if d > 0 else -step)))
                    self.cfg.setValue("icon_px", self.icon_px)
                else:
                    self.list_px = max(20, min(80, self.list_px + (step if d > 0 else -step)))
                    self.cfg.setValue("list_px", self.list_px)
                self.set_view(self.icons_mode)
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
        keep_paths = set(select) if select else (
            set(self.selected_paths()) if keep and path == self.current_dir else set())
        self.current_dir = path
        if self.chk_sub.isChecked():
            files = [os.path.join(dp, f) for dp, _, fn in os.walk(path) for f in fn]
        else:
            try:
                files = [os.path.join(path, f) for f in os.listdir(path)]
            except OSError:
                files = []
        files = sorted((f for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT and os.path.isfile(f)),
                       key=lambda f: f.lower())
        self.gen += 1
        self.thumb_queue = []
        self._loading_dir = True
        self.list.clear()
        if not self.chk_sub.isChecked():
            for name, dp in subdirs(path):
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
            if m is None:
                self.thumb_queue.append(f)
        self.row_index = {self.list.item(r).data(PATH_ROLE): r for r in range(self.list.count())}
        self._loading_dir = False
        self.update_nav()
        if keep_paths:
            self.list.blockSignals(True)
            for p in keep_paths:
                if p in self.row_index:
                    self.list.item(self.row_index[p]).setSelected(True)
            self.list.blockSignals(False)
            self.on_select()
        self.mark_items()
        self.apply_filter(self.search.text())
        self.list.overlay.setText("Aquí no hay música todavía.\n\nElige otra carpeta a la izquierda o pega archivos con Ctrl+V.")
        self.list.overlay.setGeometry(self.list.viewport().rect())
        self.list.overlay.setVisible(self.list.count() == 0)
        self.thumbs.request(self.gen, self.thumb_queue)
        self.statusBar().showMessage(f"{path} — {len(files)} canciones")

    def on_thumb(self, gen, f, img, lyrics, tags):
        """Llega una miniatura generada (o leída de la caché) en segundo plano."""
        icon = QIcon(QPixmap.fromImage(img)) if img is not None and not img.isNull() else None
        self.meta[f] = {"icon": icon, "has_lyrics": bool(lyrics)}
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
        self.vol.setValue(70)
        self.vol.wheel_step = 5
        self.vol.tip_fn = lambda v: f"Volumen: {v}%"
        self.seek.tip_fn = lambda v: f"{fmt_ms(v)} / {fmt_ms(self.seek.maximum())}"
        for w in (self.now_cover, infow):
            w.setParent(bar)   # siguen existiendo para el resto del código, pero ocultos
            w.hide()
        self.btn_list = GlyphButton("list")
        self.btn_list.setToolTip("Lista de reproducción")
        self.btn_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_list.clicked.connect(self.show_playlist)
        self.btn_fx = GlyphButton("fx")
        self.btn_fx.setToolTip("Ajustes de la canción: graves, agudos, tempo, tono, velocidad, bucle, eco…")
        self.btn_fx.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fx.clicked.connect(self.open_fx)
        h.addWidget(self.btn_list)
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
            self.audio.setVolume(0.7)
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

    def play_item(self, item):
        path = item.data(PATH_ROLE) if item is not None else None
        if not path:
            return
        self.pl_active = False   # reproducir desde la carpeta: sigue el orden de la carpeta
        self.play_file(path)

    def play_file(self, path):
        if self.player is None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        self.playing_path = path
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
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
        fab.setToolTip("Lista de reproducción")
        sh = QGraphicsDropShadowEffect(fab)
        sh.setBlurRadius(18)
        sh.setOffset(0, 3)
        sh.setColor(QColor(0, 0, 0, 150))
        fab.setGraphicsEffect(sh)
        fab.clicked.connect(self.show_playlist)
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
        self.pl_fab.move(c.width() - self.pl_fab.width() - 16, c.height() - self.pl_fab.height() - 12)
        if self.pl_panel.isVisible():
            self.pl_panel.raise_()
        self.pl_fab.raise_()

    def show_playlist(self):
        """Muestra u oculta el panel flotante de la lista de reproducción."""
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

    def step_play(self, d):
        if self.player is not None and self.pl_active and self.playlist:
            try:
                idx = self.playlist.index(self.playing_path)
            except ValueError:
                idx = -1 if d > 0 else len(self.playlist)
            n = idx + d
            if 0 <= n < len(self.playlist):
                self.play_file(self.playlist[n])
            return
        if self.player is None or self.list.count() == 0:
            return
        r = self.row_index.get(self.playing_path, -1 if d > 0 else self.list.count())
        n = r + d
        while 0 <= n < self.list.count() and self.list.item(n).data(KIND_ROLE) == "dir":
            n += d
        if 0 <= n < self.list.count():
            it = self.list.item(n)
            self.list.scrollToItem(it)
            self.play_item(it)

    def on_vol(self, x):
        if self.player is None:
            return
        if x > 0 and self.audio.isMuted():
            self.audio.setMuted(False)
        self.audio.setVolume(x / 100)
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
        self.btn_play.set_playing(st == QMediaPlayer.PlaybackState.PlayingState)
        self.disc.set_playing(st == QMediaPlayer.PlaybackState.PlayingState)
        self.viz.set_state({QMediaPlayer.PlaybackState.PlayingState: "playing",
                            QMediaPlayer.PlaybackState.PausedState: "paused"}.get(st, "stopped"))
        self.pl_update_np()

    def on_media_status(self, st):
        if st == QMediaPlayer.MediaStatus.EndOfMedia and int(self.cfg.value("autonext", 1) or 0):
            self.step_play(1)  # pasa a la siguiente canción de la lista

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
        self.apply_form()
        paths = list(self.cur_paths)
        if not paths:
            return
        if len(paths) == 1:
            p = paths[0]
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

    def do_renames(self, res):
        done, errors, newpaths = 0, [], []
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
                os.rename(old, new)
                self.retarget(old, new)
                newpaths.append(new)
                done += 1
            except Exception as e:
                errors.append(f"{oname}: {e}")
                newpaths.append(old)
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
        big = len(paths) > 60 and any(p not in self.tags_cache for p in paths)  # selección enorme: no leas todo
        for k, le in self.inputs.items():
            if big:
                le.setText("")
                le.setPlaceholderText("‹varios valores›")
                le.setEnabled(True)
                continue
            vs = {self.val(p, k) for p in paths}
            multi = len(vs) > 1
            le.setText("" if multi or not vs else next(iter(vs)))
            le.setPlaceholderText("‹varios valores›" if multi else ("" if paths else "-"))
            le.setEnabled(bool(paths))
        self.fill_tech(paths)
        dirs = {os.path.dirname(p) for p in paths}
        self.dir_le.setText(next(iter(dirs)) if len(dirs) == 1 else ("‹varios›" if dirs else ""))
        self.dir_le.setCursorPosition(0)
        self.show_current(self.current_path(), len(paths))
        self.update_suggestions()

    def fill_tech(self, paths):
        icons = {"codec": "🎵", "enc": "🧩", "tag": "🏷", "bitrate": "⚡", "freq": "🔊", "dur": "⏱", "mode": "⚙", "size": "💾"}
        if not paths:
            for k, chip in self.tech.items():
                chip.setText(f"{icons[k]} -")
                chip.show()
            return
        infos = [tech_info(p) for p in paths[:150]]
        for k, chip in self.tech.items():
            vs = {i[k] for i in infos}
            v = next(iter(vs)) if len(vs) == 1 else "‹varios›"
            chip.setText(f"{icons[k]} {v}")
            chip.setToolTip(infos[0].get("enc_full", "") if (k == "enc" and len(infos) == 1) else "")
            chip.show()

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
            self.info_lbl.setText(f"{kind}  ·  {pm.width()}×{pm.height()} px  ·  {len(data) // 1024} KB")
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
        for path, ch in list(self.pending.items()):
            try:
                easy = {k: v for k, v in ch.items() if k in EASY_KEYS}
                if easy:
                    skipped |= set(write_tags(path, easy))
                if "lyrics" in ch or "_cover" in ch:
                    write_extra(path, ch.get("lyrics"), ch.get("_cover"))
                if ch.get("lyrics") and is_lrc(ch["lyrics"]) and int(self.cfg.value("save_lrc_v2", 0) or 0):
                    try:  # archivo .lrc junto a la canción: lo leen casi todos los reproductores
                        with open(os.path.splitext(path)[0] + ".lrc", "w", encoding="utf-8") as fh:
                            fh.write(ch["lyrics"])
                    except OSError:
                        pass
                ok += 1
                saved_paths.append(path)
                del self.pending[path]
                self.meta.pop(path, None)
                self.tags_cache.pop(path, None)
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
            pass

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
        self.key_le.setText(self.cfg.value(f"key_{name}", ""))

    def run_ai(self):
        prov = self.provider.currentText()
        key, model = self.key_le.text().strip(), self.model_cb.currentText().strip()
        if not key:
            self.no_key_help(prov)
            return
        self.cfg.setValue("provider", prov)
        self.cfg.setValue(f"key_{prov}", key)
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
        if n and cur not in self.suggestions:  # salta a la primera canción con opciones
            for r in range(self.list.count()):
                if self.list.item(r).data(PATH_ROLE) in self.suggestions:
                    self.go_to_row(r)
                    break
        self.update_suggestions()
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
        self.cfg.setValue(f"key_{prov}", key)
        self.cfg.setValue(f"model_{prov}", model)
        return prov, model, key

    def run_lyrics(self):
        paths = list(self.cur_paths)
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
        self.statusBar().showMessage(
            f"Letra puesta en {self.lyr_ok} de {self.lyr_total} canciones (en naranja). "
            "Revísalas y pulsa «Guardar». En las demás, LRCLIB no tiene la letra.")

    def lyrics_failed(self, msg):
        self.btn_lyr.setEnabled(True)
        self.statusBar().showMessage("Falló la consulta de letras.")
        QMessageBox.warning(self, "Error de LRCLIB", msg)

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
        if not self.cur_paths:
            QMessageBox.information(self, "Redimensionar", "Selecciona una o varias canciones.")
            return
        self.apply_form()
        done, skipped, last = 0, 0, ""
        for p in self.cur_paths:
            pend = self.pending.get(p, {})
            data = pend["_cover"] if "_cover" in pend else inspect_file(p)["cover"]
            if not data:
                skipped += 1
                continue
            new = prepare_cover(data, side)
            if new is None or new == data:  # sin portada válida o ya es más pequeña
                skipped += 1
                continue
            b, a = cover_dims(data), cover_dims(new)
            last = f"{b[0]}×{b[1]} → {a[0]}×{a[1]} px"
            self.pending.setdefault(p, {})["_cover"] = new
            done += 1
        self.mark_items()
        self.show_current(self.current_path(), len(self.cur_paths))
        msg = f"{done} portada(s) redimensionada(s) a máx. {side} px (pendiente de guardar)"
        if done == 1:
            msg += f": {last}"
        if skipped:
            msg += f". {skipped} sin cambios (sin portada o ya eran más pequeñas)"
        self.statusBar().showMessage(msg + ".")

    def toggle_orient(self):
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
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        QApplication.clipboard().setMimeData(md)
        self.statusBar().showMessage(
            f"{len(paths)} elemento(s) {'cortado(s)' if mode == 'cut' else 'copiado(s)'}. "
            "Elige la carpeta de destino y pega (Ctrl+V).")

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
        self.release_if(paths)
        for p in paths:
            try:
                p = os.path.normpath(p)
                if send2trash:
                    send2trash(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"{p}\n{e}")
                continue
            for d in (self.pending, self.meta, self.tags_cache, self.suggestions):
                d.pop(p, None)
            self.chosen.discard(p)
        self.after_fs_change()

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
                m.addAction("✏️ Renombrar (F2)", lambda: self.rename_folder(p))
                m.addAction("🗑 Eliminar", self.delete_selected)
        m.exec(tree.viewport().mapToGlobal(pos))

    def list_menu(self, pos):
        self.list.setFocus()
        it = self.list.itemAt(pos)
        if it is not None and not it.isSelected():
            self.list.clearSelection()
            it.setSelected(True)
        m = TMenu(self)
        m.addAction("⟳ Actualizar (F5)", self.refresh_dir)
        m.addSeparator()
        if it is not None:
            if it.data(KIND_ROLE) == "dir":
                m.addAction("📂 Abrir carpeta", lambda: self.open_dir(it.data(PATH_ROLE)))
                m.addAction("▶ Reproducir carpeta", lambda: self.play_folder(it.data(PATH_ROLE)))
                m.addAction("➕ Añadir carpeta a la lista", lambda: self.pl_add([it.data(PATH_ROLE)]))
            else:
                m.addAction("▶ Reproducir", lambda: self.play_item(it))
                m.addAction("➕ Añadir a la lista de reproducción", lambda: self.pl_add(self.selected_paths()))
                m.addAction("▶️ Buscar en YouTube (abre el navegador)", lambda: self.open_youtube(it.data(PATH_ROLE)))
                m.addAction("📊 Espectrograma / calidad (varias = comparar)", self.open_spectrum)
                m.addAction("🔄 Convertir formato…", self.convert_selected)
                self.add_person_actions(m, self.val(it.data(PATH_ROLE), "artist"))
                m.addAction("✏️ Renombrar archivo (F2)", self.rename_selected)
            m.addSeparator()
            m.addAction("✂️ Cortar (Ctrl+X)", lambda: self.clip_set("cut"))
            m.addAction("📋 Copiar (Ctrl+C)", lambda: self.clip_set("copy"))
        m.addAction("📥 Pegar aquí (Ctrl+V)", self.paste_here)
        m.addAction("➕ Nueva carpeta aquí", lambda: self.new_folder(self.current_dir))
        if it is not None:
            m.addSeparator()
            m.addAction("🗑 Eliminar (Supr)", lambda: self.delete_paths(self.selected_all_paths()))
        m.addSeparator()
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

    def apply_filter(self, text=""):
        t = (text or "").strip().lower()
        for r in range(self.list.count()):
            it = self.list.item(r)
            if it.data(KIND_ROLE) == "dir":
                it.setHidden(bool(t))
                continue
            tags = self.tags_cache.get(it.data(PATH_ROLE), {})
            hay = (it.text() + " " + " ".join(tags.values())).lower()
            it.setHidden(bool(t) and t not in hay)

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
            hgt = max(self.bottom_w.sizeHint().height() + 6, 290)
            self.bottom_stack.setFixedHeight(hgt)
        else:
            self.bottom_stack.setMinimumHeight(0)
            self.bottom_stack.setMaximumHeight(16777215)

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
        self.cfg.setValue("split_cols2", self.top_split.saveState())
        if self.player is not None:
            self.player.stop()
        try:
            self.thumbs.stop()
        except Exception:
            pass
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
            pass
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
        p.addAction(self.act("➕ Añadir selección a la lista", lambda: self.pl_add(self.selected_paths())))

        t = mb.addMenu("&Herramientas")
        t.addAction(self.act("📊 Espectrograma y calidad…", self.open_spectrum,
                             "Espectrograma y análisis de calidad de las canciones seleccionadas (varias = comparar)"))
        t.addAction(self.act("✨ Portadas automáticas (alta calidad)", self.auto_cover,
                             "Busca en iTunes/Deezer la portada de las canciones seleccionadas"))
        t.addAction(self.act("🔄 Convertir formato…", self.convert_selected))
        t.addAction(self.act("🎚 Ajustes de la canción…", self.open_fx,
                             "Graves, agudos, tempo, tono, velocidad, bucle, eco… y guardar como canción nueva o reemplazar"))
        t.addAction(self.act("▶️ Buscar en YouTube (navegador)", self.youtube_current))
        t.addAction(self.act("⬇ Descargar de YouTube / SoundCloud a MP3…", self.open_ytdl,
                             "Descarga el audio de un enlace de YouTube o SoundCloud como MP3 para luego editarlo"))

        fs = mb.addMenu("&Fuente de etiquetas")
        fs.addAction(self.act("🎼 Buscar en MusicBrainz…", lambda: self.open_tag_source("musicbrainz")))
        fs.addAction(self.act("💿 Buscar en Discogs…", lambda: self.open_tag_source("discogs")))
        fs.addSeparator()
        fs.addAction(self.act("🔑 Token de Discogs…", lambda: self.open_settings(3)))

        st = mb.addMenu("&Ajustes")
        st.addAction(self.act("⚙ Opciones…", lambda: self.open_settings("general")))
        st.addSeparator()
        st.addAction(self.act("🤖 Ajustes de IA…", lambda: self.open_settings(0)))
        st.addAction(self.act("🎨 Apariencia (tema y color)…", lambda: self.open_settings(1)))
        st.addAction(self.act("🌍 Idioma…", lambda: self.open_settings(2)))

        a = mb.addMenu("A&yuda")
        a.addAction(self.act("❓ Guía rápida", self.show_guide))
        a.addAction(self.act("🔄 Buscar actualizaciones…", self.check_updates))
        self.act_autoupd = self.act("Buscar actualizaciones al abrir el programa", self.toggle_auto_update, "", True)
        self.act_autoupd.setChecked(bool(int(self.cfg.value("auto_update", 1) or 0)))
        a.addAction(self.act_autoupd)
        a.addSeparator()
        a.addAction(self.act("🆕 Novedades de esta versión", lambda: self.show_whats_new(True)))
        a.addAction(self.act("ℹ️ Acerca de Music Manager", self.show_about))
        mb.setCornerWidget(self._corner, Qt.Corner.TopRightCorner)
        i18n.set_lang(str(self.cfg.value("lang", "es")))
        i18n.retranslate(self)
        self.update_lang_btn()
        QTimer.singleShot(5000, self.auto_check_updates)

    def auto_check_updates(self):
        self.report_update_result()
        self.show_whats_new()
        if int(self.cfg.value("auto_update", 1) or 0):
            self.check_updates(manual=False)

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
        token = str(self.cfg.value("discogs_token", "") or "").strip()
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
        try:
            self.update_vol_icon()
        except Exception:
            pass
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
        add_page("general", "General", page(
            chk("Abrir la última carpeta al iniciar", "open_last", 1),
            chk("Confirmar antes de eliminar (con papelera)", "confirm_delete", 1),
            chk("Mostrar la guía rápida cada vez que se inicia", "guide_every", 0)))
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
        tok = QLineEdit(str(self.cfg.value("discogs_token", "") or ""))
        tok.setEchoMode(QLineEdit.EchoMode.Password)
        tok.setPlaceholderText("Token de Discogs")
        apply_fns.append(lambda: self.cfg.setValue("discogs_token", tok.text().strip()))
        lnk = QLabel('<a href="https://www.discogs.com/settings/developers">Conseguir mi token (discogs.com/settings/developers)</a>')
        lnk.setOpenExternalLinks(True)
        add_page("fuentes", "Fuentes de etiquetas", page(
            QLabel("MusicBrainz no necesita clave. Discogs necesita un token personal gratuito:"), tok, lnk))
        # Inteligencia artificial (los campos que usa el resto del programa)
        self.ai_cfg.show()
        add_page("ia", "Inteligencia artificial", page(QLabel("Elige el proveedor, el modelo y pega tu clave."), self.ai_cfg))
        # Reproductor
        add_page("reproductor", "Reproductor", page(chk("Pasar a la siguiente canción al terminar", "autonext", 1)))

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
            self.cfg.setValue(f"key_{prov}", self.key_le.text().strip())
            self.cfg.setValue(f"model_{prov}", self.model_cb.currentText().strip())
        else:
            if snap[0] != self.theme:
                self.set_theme(snap[0])
            if snap[1] != self.accent:
                self.set_accent(snap[1])
            if snap[2] != i18n.CUR:
                self.set_language(snap[2])
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
        w = UpdateDownloadWorker(info["url"], dest)
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

    def pick_suggestion(self, item):
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


if __name__ == "__main__":
    if sys.platform == "win32":
        try:  # para que Windows muestre el icono propio en la barra de tareas
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MusicManager.App")
        except Exception:
            pass
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Music Manager")
    i18n.install_hooks()
    _deco = icons.IconDeco(app)
    app.installEventFilter(_deco)
    w = Main()
    w.show()
    sys.exit(app.exec())

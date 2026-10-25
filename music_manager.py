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
                          QTimer, QRectF, QStandardPaths, QBuffer, QByteArray, QIODevice, QEvent, QPointF)
from PyQt6.QtGui import (QAction, QColor, QBrush, QIcon, QPixmap, QPainter, QImage,
                         QFont, QDesktopServices, QShortcut, QKeySequence, QDrag, QPalette, QLinearGradient, QPainterPath, QPolygonF, QCursor, QMouseEvent)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem,
    QListWidget, QListWidgetItem, QListView, QAbstractItemView, QVBoxLayout,
    QHBoxLayout, QGridLayout, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QComboBox, QGroupBox, QCheckBox, QFileDialog, QMessageBox,
    QInputDialog, QGraphicsDropShadowEffect, QToolTip, QStackedWidget, QStyle, QStyleOptionSlider, QHeaderView, QMenu, QToolBar, QTabWidget, QColorDialog, QSizePolicy, QScrollArea, QFileIconProvider, QFrame, QSlider, QDialog, QTextBrowser,
)
import mutagen
import i18n
from i18n import tr as T
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.flac import FLAC, Picture
from mutagen.id3 import USLT, APIC, SYLT

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
FIELDS = [("title", "Título"), ("artist", "Artista"), ("album", "Álbum"),
          ("albumartist", "Artista del álbum"), ("composer", "Compositor"),
          ("genre", "Género"), ("date", "Año"), ("tracknumber", "Pista"),
          ("discnumber", "Disco"), ("bpm", "BPM")]
EASY_KEYS = {k for k, _ in FIELDS}
PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole.value + 1
THUMB, COVER = 96, 200
APP_VERSION = "1.04"


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
    f.save()
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
    out = {"codec": "—", "bitrate": "—", "freq": "—", "dur": "—", "mode": "—", "size": "—"}
    try:
        out["size"] = f"{os.path.getsize(path) / 1048576:.2f} MB"
        f = mutagen.File(path)
        i = f.info
        kind = type(f).__name__
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
                t.add(USLT(encoding=3, lang="eng", desc="", text=lyrics))
                sy = parse_lrc(lyrics)
                if len(sy) >= 2:  # letra con tiempos: también como SYLT (letra sincronizada de ID3)
                    t.add(SYLT(encoding=3, lang="eng", format=2, type=1, desc="", text=sy))
        if cover is not None:
            t.delall("APIC")
            if cover:
                t.add(APIC(encoding=3, mime=mime_of(cover), type=3, desc="Cover", data=cover))
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
    f.save()


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
QToolBar QLineEdit { min-width: 200px; }
QLabel#title { font-size: 15px; font-weight: 700; }
QLabel#hint { color: @muted; font-size: 11px; }
QLabel#chip { background: @surface2; border: 1px solid @border; border-radius: 10px; padding: 2px 8px; font-size: 11px; }
QPushButton#tabbtn { border-radius: 10px; padding: 7px 10px; }
QPushButton#tabbtn:checked { background: @accent; color: white; border-color: @accent; font-weight: 600; }
QPushButton#chipbtn { background: @accent_soft; border: 1px solid @accent; border-radius: 10px; padding: 2px 10px; font-size: 11px; }
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


def note_icon(size=THUMB):
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
    return QIcon(pm.scaled(THUMB, THUMB, Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation))


SIZE_PRESETS = ["Original", "300", "500", "600", "800", "1000", "1200"]


def parse_side(text):
    """'600' o '600 px' -> 600. 'Original' (o algo inválido) -> None = no redimensionar."""
    t = (text or "").strip().lower().replace("px", "").strip()
    return int(t) if t.isdigit() and int(t) >= 50 else None


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


class LrclibWorker(QThread):
    """Busca letras en LRCLIB (https://lrclib.net), gratis y sin clave. Prefiere la letra sincronizada."""
    got = pyqtSignal(str, str)  # ruta, letra ("" si no hubo)
    finished_all = pyqtSignal()
    failed = pyqtSignal(str)
    UA = "MusicManager/1.04 (https://github.com/PandxMax/MusicManager)"

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

    def value_at(self, x):
        h = self._handle()
        span = max(1, self.width() - h.width())
        px = max(0, min(span, int(x) - h.width() // 2))
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), px, span)

    def show_tip(self, value, gpos):
        if self.tip_fn:
            QToolTip.showText(gpos, self.tip_fn(value), self)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._handle().contains(e.position().toPoint()):
            v = self.value_at(e.position().x())
            self.setValue(v)
            self.seekTo.emit(v)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        self.show_tip(self.value_at(e.position().x()), e.globalPosition().toPoint())

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
            item.addChild(QTreeWidgetItem(["…"]))

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

    # ---- iniciar el arrastre
    def mousePressEvent(self, e):
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
        try:
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.CopyAction)
        finally:
            self._selecting = False

    # ---- recibir: solo se puede soltar sobre una carpeta de la lista
    def _dir_at(self, pos):
        it = self.itemAt(pos)
        return it if it is not None and it.data(KIND_ROLE) == "dir" else None

    def _set_hover(self, it):
        if self._hover is not None and self._hover is not it:
            self._hover.setData(Qt.ItemDataRole.BackgroundRole, None)
        self._hover = it
        if it is not None:
            it.setBackground(QBrush(QColor(124, 92, 255, 90)))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        it = self._dir_at(e.position().toPoint())
        self._set_hover(it)
        if it is not None and e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._set_hover(None)
        e.accept()

    def dropEvent(self, e):
        it = self._dir_at(e.position().toPoint())
        self._set_hover(None)
        if it is None:
            e.ignore()
            return
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        e.setDropAction(Qt.DropAction.CopyAction)
        e.accept()
        self.dropped.emit(paths, it.data(PATH_ROLE))


# ------------------------------------------------------------- Ventana principal
class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Music Manager {APP_VERSION}")
        self.resize(1500, 840)
        self.setMinimumSize(1100, 640)
        self.cfg = QSettings("MusicManager", "MusicManager")
        self.pending, self.edited, self.lyrics_edited, self._loading = {}, set(), False, False
        self.cur_paths, self.current_dir = [], ""
        self.gen, self.thumb_queue = 0, []
        self.meta, self.tags_cache = {}, {}
        self.suggestions, self.chosen, self.ai_rows = {}, set(), []
        self.protected, self.worker, self.icons_mode = set(), None, True
        self.row_index = {}
        self.playing_path, self.lyr_worker, self.player = None, None, None
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
        cwl.addWidget(self.search)
        cwl.addWidget(self.chk_sub)

        self.pend_lbl = QLabel("")
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
            le.textEdited.connect(lambda _, key=k: self.edited.add(key))
            self.inputs[k] = le
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
        tbl = QHBoxLayout(self.tech_bar)
        tbl.setContentsMargins(0, 0, 0, 4)
        tbl.setSpacing(4)
        for k in ("codec", "bitrate", "freq", "dur", "mode", "size"):
            chip = QLabel("")
            chip.setObjectName("chip")
            chip.hide()
            self.tech[k] = chip
            tbl.addWidget(chip)
        tbl.addStretch(1)
        self.btn_spec = QPushButton("📊 Espectro")
        self.btn_spec.setObjectName("chipbtn")
        self.btn_spec.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_spec.setToolTip("Espectrograma y análisis de calidad de las canciones seleccionadas")
        self.btn_spec.clicked.connect(self.open_spectrum)
        tbl.addWidget(self.btn_spec)
        grid.addWidget(self.tech_bar, 0, 0, 1, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        b1 = QPushButton("Aplicar a selección")
        b1.clicked.connect(self.apply_form)
        b2 = QPushButton("💾 Guardar cambios")
        b2.setObjectName("accent")
        b2.setToolTip("Escribe los cambios en los archivos (Ctrl+S)")
        b2.clicked.connect(self.save_all)
        b3 = QPushButton("✏️ Renombrar archivo…")
        b3.clicked.connect(self.rename_selected)
        row = QHBoxLayout()
        row.addWidget(b1)
        row.addWidget(b3)
        row.addWidget(b2)
        grid.addLayout(row, 6, 0, 1, 4)

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
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(meta_box)

        middle = QSplitter(Qt.Orientation.Vertical)
        self.list_pane = QWidget()
        lpv = QVBoxLayout(self.list_pane)
        lpv.setContentsMargins(0, 0, 0, 0)
        lpv.setSpacing(4)
        navbar = QHBoxLayout()
        navbar.setSpacing(2)
        self.btn_back, self.btn_fwd, self.btn_up = QPushButton("◀"), QPushButton("▶"), QPushButton("▲")
        for b, tip, fn in ((self.btn_back, "Atrás (Alt+←)", self.nav_back), (self.btn_fwd, "Adelante (Alt+→)", self.nav_fwd),
                           (self.btn_up, "Subir a la carpeta superior (Alt+↑)", self.nav_up)):
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
        lpv.addLayout(navbar)
        lpv.addWidget(self.list, 1)
        middle.addWidget(self.list_pane)
        QShortcut(QKeySequence("Alt+Left"), self, activated=self.nav_back)
        QShortcut(QKeySequence("Alt+Right"), self, activated=self.nav_fwd)
        QShortcut(QKeySequence("Alt+Up"), self, activated=self.nav_up)
        self.list.viewport().installEventFilter(self)
        middle.addWidget(bottom)
        middle.setSizes([430, 300])

        # ---------- columna derecha: portada + IA
        cover_box = QGroupBox("Portada")
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
        ch.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(6)
        for text, tip, fn in (("🖼", "Cambiar portada…", self.set_cover), ("💾", "Guardar portada como imagen…", self.save_cover_as),
                              ("🗑", "Quitar portada", self.remove_cover), ("🔍", "Ver la portada en grande", self.view_cover)):
            b = QPushButton(text)
            b.setObjectName("iconbtn")
            b.setFixedSize(38, 38)
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
        cv.addLayout(ch)
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
        rightw = QWidget()
        rv = QVBoxLayout(rightw)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.addWidget(cover_box)        # fija: no se mueve
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
        rightw.setMinimumWidth(360)

        main = QSplitter()
        main.addWidget(self.left_split)
        main.addWidget(middle)
        main.addWidget(rightw)
        main.setStretchFactor(1, 1)
        self.left_split.setMinimumWidth(210)
        for i in range(3):
            main.setCollapsible(i, False)
        main.setSizes([290, 860, 370])
        self.main_split, self.mid_split = main, middle
        for sp in (main, middle, self.left_split):
            self.style_splitter(sp)
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(main, 1)
        self.setCentralWidget(central)
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
            for key, sp in (("split_main", self.main_split), ("split_mid", self.mid_split)):
                st = self.cfg.value(key)
                if st:
                    sp.restoreState(st)
            sz = self.main_split.sizes()  # si una sesión anterior dejó el árbol aplastado, lo restaura
            if sz and sz[0] < 210:
                self.main_split.setSizes([290, max(600, sz[1] - 290 + sz[0]), sz[2]])
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
            self.list.setIconSize(QSize(THUMB, THUMB))
            self.list.setGridSize(QSize(134, 156))
            self.list.setSpacing(6)
            self.list.setWordWrap(True)
            self.act_view.setText("☰ Lista")
        else:
            self.list.setViewMode(QListView.ViewMode.ListMode)
            self.list.setIconSize(QSize(44, 44))
            self.list.setGridSize(QSize())
            self.list.setSpacing(2)
            self.list.setWordWrap(False)
            self.act_view.setText("🔳 Iconos")
        self.list.setMovement(QListView.Movement.Static)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.verticalScrollBar().setSingleStep(48)

    def eventFilter(self, obj, ev):
        # botones laterales del ratón = atrás / adelante, como en el Explorador
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

    def nav_up(self):
        par = os.path.dirname(self.current_dir.rstrip("\\/")) if self.current_dir else ""
        if par and par != self.current_dir and os.path.isdir(par):
            self.open_dir(par)

    def load_folder(self, path, keep=True, select=None):
        if not path or not os.path.isdir(path):
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
        gen = self.gen
        QTimer.singleShot(0, lambda: self.thumb_tick(gen))
        self.statusBar().showMessage(f"{path} — {len(files)} canciones")

    def thumb_tick(self, gen):
        """Carga las portadas poco a poco para no congelar la ventana."""
        if gen != self.gen:
            return
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:  # no estorbes mientras seleccionas o arrastras
            QTimer.singleShot(200, lambda: self.thumb_tick(gen))
            return
        t0 = time.time()
        index = self.row_index
        while self.thumb_queue and time.time() - t0 < 0.03:
            f = self.thumb_queue.pop(0)
            d = inspect_file(f)
            if f not in self.tags_cache:
                self.tags_cache[f] = read_tags(f)
            data = d["cover"]
            if data is None:
                fi = find_folder_image(os.path.dirname(f))
                if fi:
                    try:
                        with open(fi, "rb") as fh:
                            data = fh.read()
                    except OSError:
                        data = None
            icon = make_icon(data)
            self.meta[f] = {"icon": icon, "has_lyrics": bool(d["lyrics"].strip())}
            r = index.get(f)
            if icon is not None and r is not None:
                self.list.item(r).setIcon(icon)
        if self.thumb_queue:
            QTimer.singleShot(25, lambda: self.thumb_tick(gen))

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
        self.btn_prev, self.btn_play = QPushButton("⏮"), PlayButton()
        self.btn_stop, self.btn_next = QPushButton("⏹"), QPushButton("⏭")
        for b, tip in ((self.btn_prev, "Anterior"), (self.btn_play, "Reproducir / pausa (Espacio)"),
                       (self.btn_stop, "Detener"), (self.btn_next, "Siguiente")):
            if b is not self.btn_play:
                b.setObjectName("tbtn")
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.seek = ClickSlider(Qt.Orientation.Horizontal)
        self.time_lbl = QLabel("0:00 / 0:00")
        self.time_lbl.setObjectName("hint")
        self.btn_mute = QPushButton("🔊")
        self.btn_mute.setObjectName("tbtn")
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mute.setToolTip("Silenciar")
        self.btn_mute.installEventFilter(self)
        self.vol = ClickSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(70)
        self.vol.setFixedWidth(90)
        self.vol.wheel_step = 5
        self.vol.tip_fn = lambda v: f"Volumen: {v}%"
        self.seek.tip_fn = lambda v: f"{fmt_ms(v)} / {fmt_ms(self.seek.maximum())}"
        for w in (self.now_cover, infow, self.btn_prev, self.btn_next, self.btn_stop):
            w.setParent(bar)   # siguen existiendo para el resto del código, pero ocultos
            w.hide()
        h.addWidget(self.btn_play)
        self.seek.setFixedWidth(260)
        h.addWidget(self.seek)
        h.addWidget(self.time_lbl)
        h.addWidget(self.btn_mute)
        h.addWidget(self.vol)
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
            for w in (self.btn_prev, self.btn_play, self.btn_stop, self.btn_next, self.seek, self.vol):
                w.setEnabled(False)
        return bar

    def play_item(self, item):
        path = item.data(PATH_ROLE) if item is not None else None
        if not path:
            return
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
        else:
            self.now_cover.setPixmap(self.default_icon.pixmap(52, 52))
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

    def step_play(self, d):
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
        self.btn_mute.setText("🔇" if muted or v == 0 else ("🔈" if v < 34 else "🔉" if v < 67 else "🔊"))
        self.btn_mute.setToolTip(T("Quitar silencio") if muted else T("Silenciar"))

    def on_state(self, st):
        self.btn_play.set_playing(st == QMediaPlayer.PlaybackState.PlayingState)

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

    def on_select(self):
        self.sel_timer.stop()
        if (self.edited or self.lyrics_edited) and self.cur_paths:
            self.apply_form()  # no pierdas lo que escribiste al cambiar de canción
        paths = self.selected_paths()
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
            le.setPlaceholderText("‹varios valores›" if multi else "")
            le.setEnabled(bool(paths))
        self.fill_tech(paths)
        self.show_current(self.current_path(), len(paths))
        self.update_suggestions()

    def fill_tech(self, paths):
        icons = {"codec": "🎵", "bitrate": "⚡", "freq": "🔊", "dur": "⏱", "mode": "⚙", "size": "💾"}
        if not paths:
            for chip in self.tech.values():
                chip.hide()
            return
        infos = [tech_info(p) for p in paths[:150]]
        for k, chip in self.tech.items():
            vs = {i[k] for i in infos}
            v = next(iter(vs)) if len(vs) == 1 else "‹varios›"
            chip.setText(f"{icons[k]} {v}")
            chip.setVisible(v != "—")

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
        for path, ch in list(self.pending.items()):
            try:
                easy = {k: v for k, v in ch.items() if k in EASY_KEYS}
                if easy:
                    skipped |= set(write_tags(path, easy))
                if "lyrics" in ch or "_cover" in ch:
                    write_extra(path, ch.get("lyrics"), ch.get("_cover"))
                if ch.get("lyrics") and is_lrc(ch["lyrics"]) and int(self.cfg.value("save_lrc", 1) or 0):
                    try:  # archivo .lrc junto a la canción: lo leen casi todos los reproductores
                        with open(os.path.splitext(path)[0] + ".lrc", "w", encoding="utf-8") as fh:
                            fh.write(ch["lyrics"])
                    except OSError:
                        pass
                ok += 1
                del self.pending[path]
                self.meta.pop(path, None)
                self.tags_cache.pop(path, None)
                self.suggestions.pop(path, None)
                self.chosen.discard(path)
            except Exception as e:
                errors.append(f"{os.path.basename(path)}: {e}")
        self.load_folder(self.current_dir)
        msg = f"{ok} archivo(s) guardado(s)."
        if skipped:
            msg += f" Campos no soportados por algún formato: {', '.join(sorted(skipped))}."
        self.statusBar().showMessage(msg)
        if errors:
            QMessageBox.warning(self, "Errores al guardar", "\n".join(errors))

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
            QMessageBox.information(self, "Falta la API key", f"Pega tu API key de {prov} en Ajustes → Ajustes de IA.")
            self.open_settings(0)
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

    def ai_settings(self):
        prov = self.provider.currentText()
        key, model = self.key_le.text().strip(), self.model_cb.currentText().strip()
        if not key:
            QMessageBox.information(self, "Falta la API key", f"Pega tu API key de {prov} en Ajustes → Ajustes de IA.")
            self.open_settings(0)
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
        sizes = self.main_split.sizes()
        left = 620 if (horiz and self.tree2_box.isVisible()) else 290
        self.main_split.setSizes([left, max(300, sum(sizes) - left - sizes[2]), sizes[2]])

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
        if it is not None:
            if it.data(KIND_ROLE) == "dir":
                m.addAction("📂 Abrir carpeta", lambda: self.open_dir(it.data(PATH_ROLE)))
            else:
                m.addAction("▶ Reproducir", lambda: self.play_item(it))
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

    def set_accent(self, color):
        self.accent = color or ""
        self.cfg.setValue("accent", self.accent)
        apply_theme(QApplication.instance(), self.theme, self.accent or None)

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

    def style_splitter(self, sp):
        sp.setHandleWidth(9)
        sp.setChildrenCollapsible(False)

    def closeEvent(self, e):
        self.apply_form()
        if any(self.pending.values()):
            r = QMessageBox.question(
                self, "Cambios sin guardar", "Tienes cambios sin guardar. ¿Quieres guardarlos antes de salir?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                e.ignore()
                return
            if r == QMessageBox.StandardButton.Save:
                self.save_all()
        self.cfg.setValue("geometry", self.saveGeometry())
        self.cfg.setValue("split_main", self.main_split.saveState())
        self.cfg.setValue("split_mid", self.mid_split.saveState())
        if self.player is not None:
            self.player.stop()
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
        dlg = spectro.SpectrumDialog(paths[:12], self)
        i18n.retranslate(dlg)
        dlg.show()
        self._spec = dlg

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
        v.addSeparator()
        v.addAction(self.act("🔄 Recargar carpetas", self.reload_all))

        p = mb.addMenu("&Reproducción")
        p.addAction(self.act("▶ Reproducir / pausa\tEspacio", self.toggle_play))
        p.addAction(self.act("⏮ Anterior", lambda: self.step_play(-1)))
        p.addAction(self.act("⏭ Siguiente", lambda: self.step_play(1)))
        p.addAction(self.act("⏹ Detener", self.stop_play))

        t = mb.addMenu("&Herramientas")
        t.addAction(self.act("📊 Espectrograma y calidad…", self.open_spectrum,
                             "Espectrograma y análisis de calidad de las canciones seleccionadas (varias = comparar)"))
        t.addAction(self.act("🔄 Convertir formato…", self.convert_selected))
        t.addAction(self.act("▶️ Buscar en YouTube (navegador)", self.youtube_current))

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
        a.addAction(self.act("ℹ️ Acerca de Music Manager", self.show_about))
        mb.setCornerWidget(self._corner, Qt.Corner.TopRightCorner)
        i18n.set_lang(str(self.cfg.value("lang", "es")))
        i18n.retranslate(self)

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
        else:
            url = "https://open.spotify.com/search/" + quote(name)
        QDesktopServices.openUrl(QUrl(url))
        self.statusBar().showMessage(f"Abriendo «{name}» en el navegador…")

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
        for code, name in i18n.LANGS:
            lang_cb.addItem(name, code)
        lang_cb.setCurrentIndex(max(0, [c for c, _ in i18n.LANGS].index(i18n.CUR)))
        add_page("idioma", "Idioma", page(QLabel("Idioma de la interfaz"), lang_cb,
                                          QLabel("Algunos mensajes emergentes siguen en español.")))
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
            chk("Guardar también un archivo .lrc junto a la canción", "save_lrc", 1)), grp)
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
            i18n.set_lang(lang_cb.currentData())
            self.cfg.setValue("lang", lang_cb.currentData())
            i18n.retranslate(self)
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
                i18n.set_lang(snap[2])
                self.cfg.setValue("lang", snap[2])
                i18n.retranslate(self)
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
        box.setText(
            "<h3>🎵 Guía rápida</h3><ul>"
            "<li><b>Mover:</b> arrastra canciones o carpetas sobre otra carpeta (también entre los dos árboles).</li>"
            "<li><b>Copiar / cortar / pegar:</b> Ctrl+C, Ctrl+X y Ctrl+V.</li>"
            "<li><b>Reproducir:</b> doble clic en una canción; los controles están abajo.</li>"
            "<li><b>Editar etiquetas:</b> selecciona canciones, cambia los campos y pulsa "
            "<b>Guardar cambios</b> (Ctrl+S).</li>"
            "<li><b>Portada:</b> clic derecho sobre la portada grande.</li>"
            "<li><b>Géneros con IA:</b> abre «Ajustes de IA», pega tu clave y pulsa «Sugerir género».</li>"
            "<li><b>YouTube:</b> clic derecho en una canción → Buscar en YouTube.</li>"
            "</ul><p>Puedes volver a ver esto en <b>Ayuda → Guía rápida</b>.</p>")
        box.exec()

    def show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Acerca de Music Manager")
        dlg.resize(560, 560)
        v = QVBoxLayout(dlg)
        top = QHBoxLayout()
        pm = QLabel()
        pm.setPixmap(self.logo_pm.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        top.addWidget(pm)
        t = QLabel(f"<h2 style='margin:0'>Music Manager</h2><p style='margin:2px 0'>Versión <b>{APP_VERSION}</b></p>"
                   "<p>Organiza tu música: mueve carpetas, edita etiquetas, portadas y letras,<br>"
                   "analiza la calidad de tus archivos y deja que una IA te ayude con los géneros.</p>")
        t.setTextFormat(Qt.TextFormat.RichText)
        t.setWordWrap(True)
        top.addWidget(t, 1)
        v.addLayout(top)
        log = QTextBrowser()
        log.setOpenExternalLinks(True)
        log.setHtml(
            "<h3>📜 Historial de versiones</h3>"
            f"<h4>Versión {APP_VERSION} <small>(actual)</small></h4><ul>"
            "<li>Géneros y Letra comparten el panel derecho con dos botones: se acabó el desbordamiento lateral de la ventana.</li></ul>"
            "<h4>Versión 1.03</h4><ul>"
            "<li>El panel de carpetas ya no se puede aplastar al abrir la letra.</li>"
            "<li>LRCLIB: reintentos automáticos si el servicio está saturado (error 503).</li>"
            "<li>Panel de portada más cuidado: esquinas redondeadas, sombra y botones con iconos.</li>"
            "<li>Botón «📊 Espectro» junto a los datos técnicos de la canción.</li></ul>"
            "<h4>Versión 1.02</h4><ul>"
            "<li>Letras sincronizadas desde LRCLIB (con los minutos de cada línea y archivo .lrc); se quitó la letra con IA.</li>"
            "<li>Botones de portada (cambiar, guardar, quitar, ver) y datos de la imagen.</li>"
            "<li>Se quitaron títulos y textos repetidos del panel de metadatos y de la portada.</li></ul>"
            "<h4>Versión 1.01</h4><ul>"
            "<li>Menús en lugar de barra de herramientas; reproductor compacto en la línea de estado.</li>"
            "<li>Botones atrás / adelante / subir para navegar por las carpetas.</li>"
            "<li>Árboles de carpetas con barra horizontal, destino resaltado y copiar con Ctrl.</li>"
            "<li>Espectrograma y análisis de calidad (comparación de varias canciones).</li>"
            "<li>Convertir formatos: MP3, FLAC, M4A, OGG, Opus y WAV.</li>"
            "<li>Fuentes de etiquetas: MusicBrainz y Discogs.</li>"
            "<li>Información técnica del archivo (códec, tasa de bits, frecuencia…).</li>"
            "<li>Clic derecho en el artista: Wikipedia, YouTube y Spotify.</li>"
            "<li>Ajustes con categorías, tema y color de acento, y 3 idiomas (ES / EN / RU).</li>"
            "<li>Volumen: silenciar, rueda del ratón y globos con el minuto y el volumen.</li></ul>"
            "<h4>Versión 1.0</h4><ul>"
            "<li>Explorador con arrastrar y soltar entre dos árboles.</li>"
            "<li>Editor de etiquetas, portadas (copiar, pegar, redimensionar) y letras.</li>"
            "<li>IA (Claude, ChatGPT, Gemini) para géneros y letras.</li>"
            "<li>Reproductor integrado y búsqueda en YouTube.</li></ul>")
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
    app = QApplication(sys.argv)
    app.setApplicationName("Music Manager")
    w = Main()
    w.show()
    sys.exit(app.exec())

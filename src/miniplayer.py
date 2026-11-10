"""Modo reproductor: el editor se esconde y queda solo un reproductor pequeño que se puede mover a cualquier parte
de la pantalla. Tiene el diseño del reproductor de la app del celular (portada en tarjeta, título, calidad, barra de
avance, controles y barra de acciones: Cola, Letra, Ajustes, Editar, Calidad) con un fondo que mezcla y difumina los
colores de la portada. «Cola» abre la biblioteca: canciones, carpetas, artistas y géneros, con sus portadas."""
import os
import re
import html
import random
from PyQt6.QtCore import Qt, QRectF, QPointF, QRect, QPoint, QTimer, QSize, QThread, pyqtSignal
from PyQt6.QtGui import (QPainter, QPixmap, QImage, QColor, QLinearGradient, QRadialGradient, QBrush, QPainterPath,
                         QCursor, QGuiApplication, QFont, QFontMetrics)
from PyQt6.QtWidgets import (QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QTextBrowser, QListWidget,
                             QListWidgetItem, QFrame, QMenu, QSizePolicy, QLineEdit, QStyledItemDelegate, QStyle)
import icons
from i18n import tr as T

M = 16          # margen transparente alrededor (para la sombra)
RADIUS = 26     # esquinas redondeadas
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")


def fmt(ms):
    s = max(0, int((ms or 0) // 1000))
    return f"{s // 60}:{s % 60:02d}"


def envelope(arr, n=96):
    """Forma de onda (volumen a lo largo de la canción) a partir del análisis del visualizador."""
    try:
        import numpy as np
        a = np.asarray(arr, dtype=np.float32)
        if a.ndim != 2 or len(a) < 8:
            return []
        e = a.mean(axis=1)
        v = np.array([c.mean() if len(c) else 0.0 for c in np.array_split(e, n)], dtype=np.float32)
        lo, hi = float(np.percentile(v, 4)), float(v.max())
        v = np.clip((v - lo) / max(hi - lo, 1e-3), 0, 1) ** 1.3
        return [float(x) for x in v]
    except Exception:
        return []


def placeholder_wave(seed, n=96):
    """Onda de relleno (suave y siempre igual para la misma canción) mientras se analiza el audio."""
    rnd = random.Random(seed)
    out, v = [], 0.5
    for i in range(n):
        v = min(1.0, max(0.15, v + rnd.uniform(-0.22, 0.22)))
        edge = min(1.0, i / 8.0, (n - 1 - i) / 8.0)   # empieza y termina más bajito
        out.append(v * (0.35 + 0.65 * edge))
    return out


def resample(vals, n):
    if not vals:
        return [0.3] * n
    m = len(vals)
    out = []
    for i in range(n):
        a = int(i * m / n)
        b = max(a + 1, int((i + 1) * m / n))
        seg = vals[a:b]
        out.append(sum(seg) / len(seg))
    return out


def make_noise():
    """Pequeña textura de «grano» (como en la imagen de ejemplo) que se repite sobre el fondo."""
    img = QImage(96, 96, QImage.Format.Format_ARGB32)
    rnd = random.Random(7)
    for y in range(96):
        for x in range(96):
            g = rnd.randint(0, 255)
            img.setPixelColor(x, y, QColor(g, g, g, rnd.randint(0, 255)))
    return QPixmap.fromImage(img)


def pick_colors(img):
    """Colores del fondo sacados de la portada (como en la app del celular): el color que domina, más apagado
    arriba, y uno más oscuro para el medio. Devuelve (arriba, medio)."""
    if img is None or img.isNull():
        return QColor(42, 35, 64), QColor(21, 19, 31)
    small = img.scaled(20, 20, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    r = g = b = wsum = 0.0
    for y in range(20):
        for x in range(20):
            c = small.pixelColor(x, y)
            _h, s, v, _a = c.getHsvF()
            w = 0.12 + s * v * 1.6   # los colores vivos pesan más que los grises
            r, g, b, wsum = r + c.red() * w, g + c.green() * w, b + c.blue() * w, wsum + w
    base = QColor(int(r / wsum), int(g / wsum), int(b / wsum))
    h, s, l, _ = base.getHslF()
    h = max(h, 0.0)
    top = QColor.fromHslF(h, min(s * 1.1, 0.72), min(max(l, 0.20), 0.36))
    mid = QColor.fromHslF(h, min(s, 0.55), min(max(l * 0.45, 0.07), 0.15))
    return top, mid


QUALITY = {0: ("Hi-Res", QColor(0xB3, 0x88, 0xFF)), 1: ("Sin pérdida", QColor(0x2E, 0xCC, 0x71)),
           2: ("Alta", QColor(0x4F, 0xC3, 0xF7)), 3: ("Media", QColor(0xF3, 0x9C, 0x12)), 4: ("Baja", QColor(0xE7, 0x4C, 0x3C))}


def quality_of(info):
    """(formato, detalle, nivel) como en la app del celular: Hi-Res, Sin pérdida, Alta (≥256 kbps), Media, Baja."""
    info = info or {}
    codec = str(info.get("codec") or "—")
    bits = re.search(r"(\d+)\s*bits", str(info.get("enc", "")))
    bits = int(bits.group(1)) if bits else 0
    sr = re.match(r"([\d.]+)", str(info.get("freq", "")))
    sr = float(sr.group(1)) if sr else 0.0
    kb = re.match(r"(\d+)", str(info.get("bitrate", "")))
    kb = int(kb.group(1)) if kb else 0
    lossless = codec.upper() in ("FLAC", "ALAC", "WAV", "AIFF")
    parts = []
    if lossless and bits:
        parts.append(f"{bits} bit")
    if sr:
        parts.append(f"{sr:g} kHz")
    if kb:
        parts.append(f"{kb} kbps")
    if lossless and (bits > 16 or sr > 48):
        lvl = 0
    elif lossless:
        lvl = 1
    elif kb >= 256:
        lvl = 2
    elif kb >= 160:
        lvl = 3
    elif kb > 0:
        lvl = 4
    else:
        lvl = 5
    return ("" if codec == "—" else codec.upper()), " · ".join(parts), lvl


def parse_lyrics(text):
    lrc = []
    for ln in (text or "").splitlines():
        stamps = LRC_LINE.findall(ln)
        words = LRC_LINE.sub("", ln).strip()
        for mm, ss in stamps:
            try:
                lrc.append((int((int(mm) * 60 + float(ss.replace(":", "."))) * 1000), words))
            except ValueError:
                pass
    lrc.sort()
    return lrc, LRC_LINE.sub("", text or "").strip()


class IconBtn(QPushButton):
    """Botón redondo dibujado: «plain» (icono blanco) o «white» (círculo blanco con el icono oscuro y un brillo
    alrededor, como el botón grande de reproducir de la app del celular)."""

    def __init__(self, kind, size=36, style="plain", pad=0.27, parent=None):
        super().__init__(parent)
        self.kind, self.style_, self.pad, self.active = kind, style, pad, False
        self.glow = QColor(255, 255, 255)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_kind(self, kind):
        if kind != self.kind:
            self.kind = kind
            self.update()

    def set_active(self, on):
        self.active = bool(on)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        hov, down = self.underMouse(), self.isDown()
        p.setPen(Qt.PenStyle.NoPen)
        if self.style_ == "white":
            g = QRadialGradient(r.center(), r.width() / 2)   # brillo suave del color de la canción
            gc = QColor(self.glow)
            gc.setAlpha(120)
            g.setColorAt(0.62, gc)
            gc.setAlpha(0)
            g.setColorAt(1.0, gc)
            p.setBrush(QBrush(g))
            p.drawEllipse(r)
            r = r.adjusted(r.width() * 0.11, r.height() * 0.11, -r.width() * 0.11, -r.height() * 0.11)
            p.setBrush(QColor(225, 225, 230) if down else QColor(244, 244, 248) if hov else QColor(255, 255, 255))
            p.drawEllipse(r)
            col = QColor(20, 20, 28)
        else:
            if hov:
                p.setBrush(QColor(255, 255, 255, 30))
                p.drawEllipse(r)
            col = QColor(255, 255, 255) if (self.active or hov or self.kind in ("prev", "next")) else QColor(255, 255, 255, 165)
            if self.active:
                p.setBrush(QColor(255, 255, 255, 235))
                p.drawEllipse(QPointF(r.center().x(), r.bottom() - 2.5), 2, 2)
        pad = r.width() * self.pad
        gr = r.adjusted(pad, pad, -pad, -pad)
        if down:
            gr.translate(0, 0.7)
        if self.kind == "play":   # el triángulo se ve mejor un poquito a la derecha
            gr.translate(r.width() * 0.03, 0)
        p.save()
        icons.draw_glyph(p, self.kind, gr, col)
        p.restore()


class WaveSeek(QWidget):
    """Barra de avance con la forma de la canción (la onda): lo escuchado en blanco, lo que falta tenue, y un punto
    donde va la canción. Clic o arrastrar = ir a ese punto."""
    seek = pyqtSignal(int)
    BW, GAP = 3, 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.levels, self.pos, self.dur = [], 0, 0
        self.drag, self.hover = None, None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(42)

    def set_levels(self, lv):
        self.levels = list(lv or [])
        self.update()

    def set_pos(self, pos, dur):
        """Solo se repinta cuando el punto avanza al menos un píxel (no en cada aviso del reproductor)."""
        self.pos, self.dur = pos or 0, dur or 0
        _, x0, tw = self.geo()
        k = int(x0 + tw * (self.pos / self.dur if self.dur else 0.0))
        if k != getattr(self, "_k", None) or self.drag is not None:
            self._k = k
            self.update()

    def geo(self):
        w = self.width() - 12
        n = max(16, int((w + self.GAP) // (self.BW + self.GAP)))
        tw = n * self.BW + (n - 1) * self.GAP
        return n, (self.width() - tw) / 2.0, tw

    def frac_at(self, x):
        _, x0, tw = self.geo()
        return min(1.0, max(0.0, (x - x0) / max(1.0, tw)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        n, x0, tw = self.geo()
        lv = resample(self.levels, n)
        frac = self.drag if self.drag is not None else (self.pos / self.dur if self.dur else 0.0)
        hov = self.frac_at(self.hover) if self.hover is not None and self.drag is None else None
        cy, maxh = self.height() / 2.0, self.height() - 8
        for i, v in enumerate(lv):
            x = x0 + i * (self.BW + self.GAP)
            c = (x + self.BW / 2 - x0) / tw
            bh = max(4.0, maxh * (0.12 + 0.88 * v))
            if c <= frac:
                col = QColor(255, 255, 255, 235)
            elif hov is not None and c <= hov:
                col = QColor(255, 255, 255, 130)
            else:
                col = QColor(255, 255, 255, 64)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, cy - bh / 2, self.BW, bh), self.BW / 2, self.BW / 2)
        if self.dur:   # el punto (como la bolita de la barra del celular)
            fx = x0 + tw * frac
            p.setBrush(QColor(0, 0, 0, 70))
            p.drawEllipse(QPointF(fx, cy + 1), 8.5, 8.5)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(QPointF(fx, cy), 7.5, 7.5)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.dur:
            self.drag = self.frac_at(e.position().x())
            self.update()

    def mouseMoveEvent(self, e):
        n, x0, _ = self.geo()
        old = int((self.hover - x0) // (self.BW + self.GAP)) if self.hover is not None else None
        self.hover = e.position().x()
        if self.drag is not None:
            self.drag = self.frac_at(self.hover)
            self.update()
        elif int((self.hover - x0) // (self.BW + self.GAP)) != old:
            self.update()

    def mouseReleaseEvent(self, e):
        if self.drag is not None:
            ms = int(self.drag * self.dur)
            self.pos, self.drag = ms, None
            self.seek.emit(ms)
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()


class QualityRow(QWidget):
    """[MP3]  44.1 kHz · 320 kbps  (Alta)  — igual que en la app del celular."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fmt, self.detail, self.lvl = "", "", 5
        self.setFixedHeight(24)

    def set(self, fmt, detail, lvl):
        self.fmt, self.detail, self.lvl = fmt, detail, lvl
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fb = QFont(self.font())
        fb.setPixelSize(11)
        fb.setBold(True)
        fd = QFont(self.font())
        fd.setPixelSize(12)
        mb, md = QFontMetrics(fb), QFontMetrics(fd)
        parts = []
        if self.fmt:
            parts.append(("chip", self.fmt, mb.horizontalAdvance(self.fmt) + 14))
        if self.detail:
            parts.append(("text", self.detail, md.horizontalAdvance(self.detail) + 16))
        if self.lvl in QUALITY:
            lab = T(QUALITY[self.lvl][0])
            parts.append(("lvl", lab, mb.horizontalAdvance(lab) + 18))
        total = sum(w for _k, _t, w in parts)
        x = (self.width() - total) / 2
        h = self.height()
        for kind, text, w in parts:
            if kind == "chip":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 36))
                p.drawRoundedRect(QRectF(x, 3, w, h - 6), 5, 5)
                p.setPen(QColor("white"))
                p.setFont(fb)
                p.drawText(QRectF(x, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
            elif kind == "text":
                p.setPen(QColor(255, 255, 255, 170))
                p.setFont(fd)
                p.drawText(QRectF(x, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
            else:
                col = QUALITY[self.lvl][1]
                bg = QColor(col)
                bg.setAlpha(48)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(bg)
                p.drawRoundedRect(QRectF(x, 2, w, h - 4), (h - 4) / 2, (h - 4) / 2)
                p.setPen(col.lighter(115))
                p.setFont(fb)
                p.drawText(QRectF(x, 0, w, h), Qt.AlignmentFlag.AlignCenter, text)
            x += w + 4


class ActionBtn(QPushButton):
    """Botón de la barra de abajo: icono y texto debajo (Cola, Letra, Ajustes, Editar, Calidad)."""

    def __init__(self, kind, label):
        super().__init__()
        self.kind, self.label, self.active = kind, label, False
        self.setFixedSize(58, 50)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_active(self, on):
        self.active = bool(on)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.underMouse() or self.active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 40 if self.active else 24))
            p.drawRoundedRect(r, 14, 14)
        ic = QRectF(r.center().x() - 11, r.top() + 5 + (0.6 if self.isDown() else 0), 22, 22)
        p.save()
        icons.draw_glyph(p, self.kind, ic, QColor(255, 255, 255, 235 if (self.active or self.underMouse()) else 215))
        p.restore()
        f = QFont(self.font())
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 220 if self.active else 165))
        p.drawText(QRectF(r.left(), r.top() + 29, r.width(), 16), Qt.AlignmentFlag.AlignCenter,
                   QFontMetrics(f).elidedText(self.label, Qt.TextElideMode.ElideRight, int(r.width())))


class ActionBar(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 20))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 22, 22)


class Panel(QWidget):
    """Letra encima de la portada, sobre un vidrio oscuro."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        p.drawRoundedRect(QRectF(self.rect()), 18, 18)


KIND_R, KEY_R, TITLE_R, SUB_R, RIGHT_R, REP_R = (Qt.ItemDataRole.UserRole + i for i in range(6))


class LibraryWorker(QThread):
    """Busca todas las canciones de la carpeta (y de todas sus subcarpetas) y lee sus etiquetas en segundo plano."""
    listed = pyqtSignal(str, list)            # carpeta, archivos (en cuanto se encuentran)
    progress = pyqtSignal(str, int, int)      # carpeta, leídos, total
    done = pyqtSignal(str, dict)              # carpeta, {ruta: (título, artista, álbum, género)}

    def __init__(self, base, known, read_fn, exts):
        super().__init__()
        self.base, self.known, self.read_fn, self.exts = base, known, read_fn, exts

    def run(self):
        files = []
        for dp, dns, fns in os.walk(self.base):
            if self.isInterruptionRequested():
                return
            dns.sort(key=str.lower)
            for f in sorted(fns, key=str.lower):
                if os.path.splitext(f)[1].lower() in self.exts:
                    files.append(os.path.join(dp, f))
        self.listed.emit(self.base, files)
        tags = {}
        for i, f in enumerate(files):
            if self.isInterruptionRequested():
                return
            t = self.known.get(f)
            if t is None and self.read_fn is not None:
                try:
                    t = self.read_fn(f)
                except Exception:
                    t = None
            t = t or {}
            tags[f] = (str(t.get("title") or ""), str(t.get("artist") or t.get("albumartist") or ""),
                       str(t.get("album") or ""), str(t.get("genre") or ""))
            if i % 120 == 119:
                self.progress.emit(self.base, i + 1, len(files))
        self.done.emit(self.base, tags)


class RowDelegate(QStyledItemDelegate):
    """Fila de la biblioteca: portada (o icono), título, subtítulo y, a la derecha, cuántas canciones."""
    H = 56

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def sizeHint(self, opt, idx):
        return QSize(max(10, opt.rect.width()), self.H)

    def paint(self, p, opt, idx):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(opt.rect).adjusted(2, 1, -4, -1)
        kind = idx.data(KIND_R)
        playing = kind == "song" and idx.data(KEY_R) == self.page.main.playing_path
        if opt.state & QStyle.StateFlag.State_MouseOver or playing:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 34 if playing else 20))
            p.drawRoundedRect(r, 12, 12)
        ic = QRectF(r.left() + 5, r.center().y() - 21, 42, 42)
        pm = self.page.pix.get(idx.data(REP_R)) if idx.data(REP_R) else None
        path = QPainterPath()
        if kind == "artist":
            path.addEllipse(ic)
        else:
            path.addRoundedRect(ic, 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        if pm is not None and not pm.isNull():
            p.save()
            p.setClipPath(path)
            src = QRectF(pm.rect())
            side = min(src.width(), src.height())
            p.drawPixmap(ic, pm, QRectF(src.center().x() - side / 2, src.center().y() - side / 2, side, side))
            p.restore()
            if kind == "folder":   # carpetita sobre la portada, para distinguirla de una canción
                b = QRectF(ic.right() - 17, ic.bottom() - 17, 19, 19)
                p.setBrush(QColor(0, 0, 0, 185))
                p.drawRoundedRect(b, 5, 5)
                p.save()
                icons.draw_glyph(p, "folder", b.adjusted(3, 3, -3, -3), QColor(255, 255, 255, 230))
                p.restore()
        else:
            p.fillPath(path, QColor(255, 255, 255, 26))
            glyph = {"song": "note", "folder": "folder", "artist": "person", "genre": "tag", "info": "info"}.get(kind, "note")
            p.save()
            icons.draw_glyph(p, glyph, ic.adjusted(11, 11, -11, -11), QColor(255, 255, 255, 200))
            p.restore()
        if playing:   # sonando: barritas encima de la portada
            p.fillPath(path, QColor(0, 0, 0, 120))
            p.save()
            icons.draw_glyph(p, "eqbars", ic.adjusted(11, 11, -11, -11), QColor(255, 255, 255))
            p.restore()
        right = idx.data(RIGHT_R) or ""
        f = QFont(opt.font)
        f.setPixelSize(11)
        f.setBold(True)
        rw = QFontMetrics(f).horizontalAdvance(right) + 10 if right else 0
        if right:
            p.setFont(f)
            p.setPen(QColor(255, 255, 255, 150))
            p.drawText(QRectF(r.right() - rw - 6, r.top(), rw, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, right)
        tx = ic.right() + 11
        tw = r.right() - rw - 8 - tx
        title, sub = idx.data(TITLE_R) or "", idx.data(SUB_R) or ""
        ft = QFont(opt.font)
        ft.setPixelSize(13)
        ft.setBold(True)
        fs = QFont(opt.font)
        fs.setPixelSize(11)
        p.setFont(ft)
        p.setPen(QColor(255, 255, 255))
        if sub:
            p.drawText(QRectF(tx, r.top() + 8, tw, 19), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(ft).elidedText(title, Qt.TextElideMode.ElideRight, int(tw)))
            p.setFont(fs)
            p.setPen(QColor(255, 255, 255, 150))
            p.drawText(QRectF(tx, r.top() + 27, tw, 17), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(fs).elidedText(sub, Qt.TextElideMode.ElideRight, int(tw)))
        else:
            p.drawText(QRectF(tx, r.top(), tw, r.height()), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(ft).elidedText(title, Qt.TextElideMode.ElideRight, int(tw)))
        p.restore()


class NowStrip(QWidget):
    """Debajo de la biblioteca: lo que suena ahora (clic = volver al reproductor)."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setFixedHeight(54)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(58, 0, 8, 0)
        h.setSpacing(4)
        self.lbl = QLabel("")
        self.lbl.setStyleSheet("QLabel { color: white; font-size: 12px; background: transparent; }")
        self.lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        mini = page.mini
        self.b_play = IconBtn("play", 44, "white", 0.27)
        self.b_play.clicked.connect(mini.main.toggle_play)
        self.b_next = IconBtn("next", 34, pad=0.28)
        self.b_next.clicked.connect(lambda: mini.main.step_play(1))
        h.addWidget(self.lbl, 1)
        h.addWidget(self.b_play)
        h.addWidget(self.b_next)

    def update_now(self):
        m = self.page.main
        path = m.playing_path
        if not path:
            self.lbl.setText("<span style='color:rgba(255,255,255,160)'>" + html.escape(T("Nada sonando")) + "</span>")
        else:
            t = m.val(path, "title") or os.path.splitext(os.path.basename(path))[0]
            a = m.val(path, "artist")
            fm = self.lbl.fontMetrics()
            wmax = max(60, self.lbl.width() - 4)
            self.lbl.setText(f"<b>{html.escape(fm.elidedText(t, Qt.TextElideMode.ElideRight, wmax))}</b><br>"
                             f"<span style='color:rgba(255,255,255,160)'>"
                             f"{html.escape(fm.elidedText(a, Qt.TextElideMode.ElideRight, wmax))}</span>")
        pl = m.player
        playing = False
        if pl is not None:
            from PyQt6.QtMultimedia import QMediaPlayer
            playing = pl.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.b_play.set_kind("pause" if playing else "play")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawRoundedRect(r, 16, 16)
        cr = QRectF(r.left() + 8, r.center().y() - 19, 38, 38)
        path = QPainterPath()
        path.addRoundedRect(cr, 8, 8)
        p.setClipPath(path)
        img = self.page.mini.img
        if img is not None and not img.isNull():
            p.drawImage(cr, img)
        else:
            p.fillRect(cr, QColor(120, 90, 220))
        p.setClipping(False)

    def mouseReleaseEvent(self, e):
        self.page.mini.close_library()


class LibraryPage(QWidget):
    """Biblioteca dentro del modo reproductor: todas las canciones de la carpeta que se estaba editando (con todas
    sus subcarpetas), la estructura de carpetas, los artistas y los géneros."""
    TABS = (("songs", "Canciones"), ("folders", "Carpetas"), ("artists", "Artistas"), ("genres", "Géneros"))

    def __init__(self, mini):
        super().__init__(mini)
        self.mini, self.main = mini, mini.main
        self.base, self.files, self.tags, self.loaded = None, [], {}, False
        self.worker, self.tab, self.stack = None, "songs", []
        self.read_pct = 0
        self.pix, self.rep = {}, {}   # portadas pequeñas ya cargadas · canción que representa a cada carpeta
        import thumbs
        self.thumbs = thumbs.ThumbWorker(160, mini.inspect_file, mini.read_fn, mini.folder_img_fn)
        self.thumbs.ready.connect(self.on_thumb)
        self.thumbs.start()
        self._tgen = 1
        self._vis = QTimer(self)
        self._vis.setSingleShot(True)
        self._vis.setInterval(60)
        self._vis.timeout.connect(self.request_visible)
        self._repaint = QTimer(self)
        self._repaint.setSingleShot(True)
        self._repaint.setInterval(90)
        self._repaint.timeout.connect(lambda: self.list.viewport().update())
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 8)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(2)
        self.b_back = IconBtn("chevron_l", 32, pad=0.26)
        self.b_back.setToolTip(T("Atrás"))
        self.b_back.clicked.connect(self.go_back)
        self.h_title = QLabel(T("Biblioteca"))
        self.h_title.setStyleSheet("QLabel { color: white; font-size: 18px; font-weight: 800; background: transparent; }")
        self.h_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.b_ref = IconBtn("refresh", 32, pad=0.27)
        self.b_ref.setToolTip(T("Volver a leer la carpeta"))
        self.b_ref.clicked.connect(lambda: self.open_for(self.base, force=True))
        self.b_close = IconBtn("close", 32, pad=0.30)
        self.b_close.setToolTip(T("Cerrar la biblioteca (Esc)"))
        self.b_close.clicked.connect(self.mini.close_library)
        head.addWidget(self.b_back)
        head.addWidget(self.h_title, 1)
        head.addWidget(self.b_ref)
        head.addWidget(self.b_close)
        v.addLayout(head)
        self.h_sub = QLabel("")
        self.h_sub.setStyleSheet("QLabel { color: rgba(255,255,255,175); font-size: 11px; font-weight: 700; "
                                 "background: transparent; }")
        self.h_sub.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.h_sub.setWordWrap(True)   # si no cabe en una línea, pasa a dos (no se corta)
        v.addWidget(self.h_sub)
        chips = QHBoxLayout()
        chips.setSpacing(5)
        self.chips = {}
        for key, label in self.TABS:
            b = QPushButton(T(label))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setStyleSheet(
                "QPushButton { color: rgba(255,255,255,200); background: rgba(255,255,255,22); border: none; "
                "border-radius: 13px; padding: 5px 9px; font-size: 11px; font-weight: 800; }"
                "QPushButton:hover { background: rgba(255,255,255,40); }"
                "QPushButton:checked { background: white; color: #111; }")
            b.clicked.connect(lambda _c, k=key: self.set_tab(k))
            self.chips[key] = b
            chips.addWidget(b)
        chips.addStretch(1)
        v.addLayout(chips)
        self.search = QLineEdit()
        self.search.setPlaceholderText(T("Buscar…"))
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,22); color: white; border: 1px solid transparent; "
            "border-radius: 15px; padding: 5px 12px; font-size: 12px; selection-background-color: rgba(255,255,255,90); }"
            "QLineEdit:focus { border: 1px solid rgba(255,255,255,90); }")
        self._st = QTimer(self)
        self._st.setSingleShot(True)
        self._st.setInterval(200)
        self._st.timeout.connect(self.render)
        self.search.textChanged.connect(lambda _t: self._st.start())
        v.addWidget(self.search)
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setItemDelegate(RowDelegate(self))
        self.list.setStyleSheet(
            "QListWidget { background: transparent; border: none; outline: none; }"
            "QListWidget::item { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 6px; margin: 2px 0; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,80); border-radius: 3px; min-height: 30px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }")
        self.list.itemClicked.connect(self.on_click)
        self.list.verticalScrollBar().valueChanged.connect(lambda _v: self._vis.start())
        v.addWidget(self.list, 1)
        self.strip = NowStrip(self)
        v.addWidget(self.strip)
        self.chips["songs"].setChecked(True)

    # ------------------------------------------------------------ portadas de la lista
    def request_visible(self):
        """Pide las portadas de las filas que se ven (y unas cuantas más abajo), las primeras primero."""
        n = self.list.count()
        if not n or not self.isVisible():
            return
        vp = self.list.viewport()
        first = self.list.indexAt(QPoint(8, 4)).row()
        last = self.list.indexAt(QPoint(8, vp.height() - 4)).row()
        first = max(0, first)
        last = n - 1 if last < 0 else last
        want = []
        meta = getattr(self.main, "meta", {}) or {}
        for i in range(first, min(n, last + 14)):
            p = self.list.item(i).data(REP_R)
            if not p or p in self.pix or p in want:
                continue
            m = meta.get(p)
            if m and m.get("icon") is not None:   # el editor ya la tenía
                self.pix[p] = m["icon"].pixmap(84, 84)
                continue
            want.append(p)
        if want:
            self._tgen += 1
            self.thumbs.request(self._tgen, want)
        else:
            self.list.viewport().update()

    def on_thumb(self, gen, path, img, lyrics, tags):
        if img is not None and not img.isNull():
            self.pix[path] = QPixmap.fromImage(img.scaled(84, 84, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                          Qt.TransformationMode.SmoothTransformation))
        else:
            self.pix[path] = None
        if not self._repaint.isActive():
            self._repaint.start()

    def shutdown(self):
        for w in list(getattr(self, "_workers", ())):
            w.requestInterruption()
            w.wait(2000)
        self.thumbs.stop()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(QRectF(r.left(), r.top(), r.width(), r.height() + RADIUS), RADIUS, RADIUS)
        p.setClipPath(path)
        g = QLinearGradient(0, 0, 0, r.height())   # fondo opaco (antes se transparentaba lo de detrás)
        c1, c2 = QColor(self.mini.col), QColor(self.mini.col2)
        c1 = QColor.fromHslF(max(c1.hslHueF(), 0.0), c1.hslSaturationF(), c1.lightnessF() * 0.62)
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.fillRect(r, QBrush(g))

    def showEvent(self, e):
        self._vis.start()
        self.strip.update_now()
        QTimer.singleShot(0, self.strip.update_now)   # cuando ya tiene su ancho (para recortar bien los textos)
        super().showEvent(e)

    # ------------------------------------------------------------ datos
    def open_for(self, base, force=False):
        if not base or not os.path.isdir(base):
            self.base, self.files, self.tags, self.loaded = base, [], {}, True
            self.h_sub.setText(T("Abre una carpeta en el editor para ver su música aquí."))
            self.render()
            return
        if base == self.base and (self.loaded or self.worker is not None) and not force:
            self.render()
            return
        if self.worker is not None:
            self.worker.requestInterruption()
        self.base, self.files, self.tags, self.loaded, self.read_pct = base, [], {}, False, 0
        self.stack = []
        known = dict(getattr(self.main, "tags_cache", {}) or {})
        w = LibraryWorker(base, known, self.mini.read_fn, self.mini.exts)
        w.listed.connect(self.on_listed)
        w.progress.connect(self.on_progress)
        w.done.connect(self.on_done)
        w.finished.connect(lambda w=w: self._worker_done(w))
        self._workers = getattr(self, "_workers", set())
        self._workers.add(w)   # se guarda hasta que termine (no se destruye un hilo en marcha)
        self.worker = w
        w.start()
        self.render()

    def _worker_done(self, w):
        self._workers.discard(w)
        if self.worker is w:
            self.worker = None

    def on_listed(self, base, files):
        if base != self.base:
            return
        self.files = files
        self.index_folders()
        self.render()

    def on_progress(self, base, n, total):
        if base != self.base:
            return
        self.read_pct = int(n * 100 / max(1, total))
        self.update_sub()

    def on_done(self, base, tags):
        if base != self.base:
            return
        self.tags, self.loaded = tags, True
        self.render()

    def index_folders(self):
        """Cuántas canciones hay en cada carpeta (contando sus subcarpetas) y qué subcarpetas tiene cada una."""
        self.fcount, self.children, self.direct, self.rep = {}, {}, {}, {}
        base = os.path.normpath(self.base)
        for f in self.files:
            d = os.path.dirname(f)
            self.direct.setdefault(d, []).append(f)
            cur = d
            while True:
                self.fcount[cur] = self.fcount.get(cur, 0) + 1
                self.rep.setdefault(cur, f)   # la portada de la carpeta = la de su primera canción
                if os.path.normpath(cur) == base:
                    break
                par = os.path.dirname(cur)
                if par == cur or len(par) < len(base):
                    break
                self.children.setdefault(par, set()).add(cur)
                cur = par

    def info(self, f):
        t = self.tags.get(f)
        if t is None:
            mt = self.main.tags_cache.get(f) if hasattr(self.main, "tags_cache") else None
            if mt:
                t = (mt.get("title") or "", mt.get("artist") or "", mt.get("album") or "", mt.get("genre") or "")
        if t is None:
            t = ("", "", "", "")
        return t

    def groups(self, idx):
        out = {}
        for f in self.files:
            val = self.info(f)[idx].strip()
            names = [x.strip() for x in re.split(r"[;,]", val) if x.strip()] if idx == 3 else [val]
            for nm in names or [""]:
                out.setdefault(nm, []).append(f)
        return out

    # ------------------------------------------------------------ navegación
    def set_tab(self, key):
        self.tab = key
        self.stack = []
        for k, b in self.chips.items():
            b.setChecked(k == key)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.render()

    def go_back(self):
        if self.stack:
            self.stack.pop()
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.render()
        else:
            self.mini.close_library()

    def on_click(self, it):
        kind, key = it.data(KIND_R), it.data(KEY_R)
        if kind == "song":
            seq = [self.list.item(i).data(KEY_R) for i in range(self.list.count())
                   if self.list.item(i).data(KIND_R) == "song"]
            self.mini.play_from_library(key, seq)
            self.list.viewport().update()
        elif kind in ("folder", "artist", "genre"):
            self.stack.append((kind, key))
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
            self.render()
            self.list.scrollToTop()

    def song_row(self, f, show_folder=False):
        t, a, al, _g = self.info(f)
        title = t or os.path.splitext(os.path.basename(f))[0]
        sub = " · ".join(x for x in (a, al) if x)
        if not sub or show_folder:
            sub = sub or os.path.basename(os.path.dirname(f))
        return ("song", f, title, sub, "", f)

    def update_sub(self):
        n = len(self.files)
        if not self.base:
            return
        if not self.files and not self.loaded:
            txt = T("Buscando canciones…")
        else:
            txt = f"📁 {os.path.basename(os.path.normpath(self.base)) or self.base}  ·  " + T(f"{n} canciones cargadas")
            if not self.loaded:
                txt += "  ·  " + T(f"leyendo etiquetas {self.read_pct} %")
        top = self.stack[-1] if self.stack else None
        if top is not None:
            cnt = getattr(self, "_shown_songs", 0)
            txt = T(f"{cnt} canciones")
            if top[0] == "folder":
                rel = os.path.relpath(top[1], self.base)
                txt = f"📁 {rel}  ·  " + txt
        elif self.tab in ("artists", "genres", "folders") and self.files:
            g = getattr(self, "_shown_groups", 0)
            what = {"artists": T(f"{g} artistas"), "genres": T(f"{g} géneros"), "folders": T(f"{g} carpetas")}[self.tab]
            txt = txt + f"  ·  {what}"
        if self.search.text().strip():
            txt = T(f"{getattr(self, '_shown_rows', 0)} resultados") + "  ·  " + txt
        self.h_sub.setText(txt)

    def render(self):
        q = self.search.text().strip().lower()
        top = self.stack[-1] if self.stack else None
        rows = []
        self._shown_groups = 0
        if top is None:
            self.h_title.setText(T("Biblioteca"))
        else:
            self.h_title.setText(os.path.basename(top[1]) if top[0] == "folder" else (top[1] or T("(sin nombre)")))
        self.b_back.setVisible(top is not None)
        if self.files:
            if self.tab == "songs" and top is None:
                rows = [self.song_row(f) for f in self.files]
                rows.sort(key=lambda r: r[2].lower())
            elif top is not None and top[0] in ("artist", "genre"):
                members = self.groups(1 if top[0] == "artist" else 3).get(top[1], [])
                rows = [self.song_row(f) for f in members]
                rows.sort(key=lambda r: (r[3].lower(), r[2].lower()))
            elif self.tab == "folders":
                folder = top[1] if top is not None else self.base
                subs = sorted(self.children.get(folder, ()), key=lambda d: os.path.basename(d).lower())
                self._shown_groups = len(subs)
                for d in subs:
                    rows.append(("folder", d, os.path.basename(d), "", str(self.fcount.get(d, 0)), self.rep.get(d)))
                rows += [self.song_row(f) for f in self.direct.get(folder, [])]
            else:
                idx = 1 if self.tab == "artists" else 3
                gr = self.groups(idx)
                self._shown_groups = len(gr)
                for name in sorted(gr, key=lambda n: (n == "", n.lower())):
                    rows.append(("artist" if idx == 1 else "genre", name,
                                 name or (T("(sin artista)") if idx == 1 else T("(sin género)")), "", str(len(gr[name])),
                                 gr[name][0]))
                if not self.loaded:
                    rows.insert(0, ("info", "", T("Leyendo etiquetas…"), T(f"{self.read_pct} % — la lista se completa sola"),
                                    "", None))
        if q:
            rows = [r for r in rows if r[0] == "info" or q in r[2].lower() or q in r[3].lower()
                    or (r[0] == "song" and q in os.path.basename(r[1]).lower())]
        self._shown_songs = sum(1 for r in rows if r[0] == "song")
        self._shown_rows = sum(1 for r in rows if r[0] != "info")
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for kind, key, title, sub, right, rp in rows:
            it = QListWidgetItem()
            it.setData(REP_R, rp)
            it.setData(KIND_R, kind)
            it.setData(KEY_R, key)
            it.setData(TITLE_R, title)
            it.setData(SUB_R, sub)
            it.setData(RIGHT_R, right)
            if kind == "song":
                it.setToolTip(key)
            self.list.addItem(it)
        self.list.setUpdatesEnabled(True)
        self.update_sub()
        self._vis.start()
        if not self.files:
            empty = QListWidgetItem()
            empty.setData(KIND_R, "info")
            empty.setData(TITLE_R, T("Buscando canciones…") if not self.loaded else T("No hay canciones aquí."))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)


class MiniPlayer(QWidget):
    """Diseño como el reproductor de la app del celular (portada en tarjeta, título, calidad, barra de avance,
    controles y barra de acciones), con el fondo que mezcla y difumina los colores de la portada."""
    BASE_W = 330
    EXTRA = 386   # alto que no es la portada (barra de arriba, textos, onda, controles, acciones)

    def __init__(self, main, inspect_file=None, tech_fn=None, read_fn=None, exts=None, folder_img_fn=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.main, self.inspect_file, self.tech_fn = main, inspect_file, tech_fn
        self.read_fn, self.folder_img_fn = read_fn, folder_img_fn
        self.exts = set(exts or {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4"})
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowTitle("Music Manager")
        try:
            self.setWindowIcon(main.windowIcon())
        except Exception:
            pass
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.path, self.img = None, None
        self.col, self.col2 = pick_colors(None)
        self.blur, self._bg, self._bg_key = None, None, None
        self.noise = make_noise()
        self.lrc, self.lrc_idx, self.plain = [], -1, ""
        self._press, self._moved, self._drag_off = None, False, None
        self.tech_text = ""
        self.top = bool(int(main.cfg.value("mini_top", 0) or 0))
        if self.top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        scr = QGuiApplication.primaryScreen()
        ah = scr.availableGeometry().height() if scr is not None else 900
        self.W = max(270, min(self.BASE_W, ah - 2 * M - 8 - self.EXTRA + 52))
        self.S = self.W - 52                       # lado de la portada
        self.H = self.S + self.EXTRA
        self.setFixedSize(self.W + 2 * M, self.H + 2 * M)
        self.cover_rect = QRectF(M + 26, M + 8 + 46 + 6, self.S, self.S)

        v = QVBoxLayout(self)
        v.setContentsMargins(M + 12, M + 8, M + 12, M + 12)
        v.setSpacing(0)
        # ---- barra de arriba
        topw = QWidget()
        topw.setFixedHeight(46)
        th = QHBoxLayout(topw)
        th.setContentsMargins(0, 0, 0, 0)
        self.b_down = IconBtn("chevron_d", 40, pad=0.25)
        self.b_down.setToolTip(T("Volver al editor (Esc)"))
        self.b_down.clicked.connect(self.main.exit_mini)
        cap = QVBoxLayout()
        cap.setSpacing(0)
        self.cap1 = QLabel(T("REPRODUCIENDO"))
        self.cap1.setStyleSheet("QLabel { color: rgba(255,255,255,160); font-size: 11px; letter-spacing: 2px; "
                                "background: transparent; }")
        self.cap2 = QLabel("")
        self.cap2.setStyleSheet("QLabel { color: rgba(255,255,255,220); font-size: 12px; font-weight: 600; "
                                "background: transparent; }")
        for l in (self.cap1, self.cap2):
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            cap.addWidget(l)
        self.b_more = IconBtn("morev", 40, pad=0.27)
        self.b_more.setToolTip(T("Más opciones"))
        self.b_more.clicked.connect(lambda: self.show_menu(self.b_more.mapToGlobal(QPoint(0, self.b_more.height()))))
        th.addWidget(self.b_down)
        th.addLayout(cap, 1)
        th.addWidget(self.b_more)
        v.addWidget(topw)
        v.addSpacing(6 + self.S + 18)   # la portada se dibuja en el fondo (así no se redibuja a cada rato)
        # ---- título, artista y calidad
        self.title = QLabel("—")
        self.title.setStyleSheet("QLabel { color: white; font-size: 20px; font-weight: 800; background: transparent; }")
        self.sub = QLabel("")
        self.sub.setStyleSheet("QLabel { color: rgba(255,255,255,205); font-size: 14px; background: transparent; }")
        for l in (self.title, self.sub):
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        v.addWidget(self.title)
        v.addSpacing(2)
        v.addWidget(self.sub)
        v.addSpacing(8)
        self.quality = QualityRow()
        v.addWidget(self.quality)
        v.addSpacing(8)
        # ---- barra de avance (la onda) y tiempos
        self.wave = WaveSeek()
        self.wave.seek.connect(self.do_seek)
        v.addWidget(self.wave)
        tr_ = QHBoxLayout()
        tr_.setContentsMargins(4, 0, 4, 0)
        self.t_pos, self.t_left = QLabel("0:00"), QLabel("-0:00")
        for l in (self.t_pos, self.t_left):
            l.setStyleSheet("QLabel { color: rgba(255,255,255,190); font-size: 12px; background: transparent; }")
        tr_.addWidget(self.t_pos)
        tr_.addStretch(1)
        tr_.addWidget(self.t_left)
        v.addLayout(tr_)
        v.addSpacing(2)
        # ---- controles
        ctr = QHBoxLayout()
        ctr.setContentsMargins(0, 0, 0, 0)
        self.b_shuffle = IconBtn("shuffle", 42, pad=0.25)
        self.b_shuffle.setToolTip(T("Aleatorio"))
        self.b_shuffle.clicked.connect(self.toggle_shuffle)
        self.b_prev = IconBtn("prev", 54, pad=0.25)
        self.b_prev.setToolTip(T("Anterior"))
        self.b_prev.clicked.connect(lambda: self.main.step_play(-1))
        self.b_play = IconBtn("play", 88, "white", 0.27)
        self.b_play.setToolTip(T("Reproducir / pausa (Espacio)"))
        self.b_play.clicked.connect(self.main.toggle_play)
        self.b_next = IconBtn("next", 54, pad=0.25)
        self.b_next.setToolTip(T("Siguiente"))
        self.b_next.clicked.connect(lambda: self.main.step_play(1))
        self.b_repeat = IconBtn("loop", 42, pad=0.25)
        self.b_repeat.setToolTip(T("Repetir: no / todas / una"))
        self.b_repeat.clicked.connect(self.cycle_repeat)
        for i, b in enumerate((self.b_shuffle, self.b_prev, self.b_play, self.b_next, self.b_repeat)):
            if i:
                ctr.addStretch(1)
            ctr.addWidget(b)
        v.addLayout(ctr)
        v.addStretch(1)
        # ---- barra de acciones
        self.bar = ActionBar()
        self.bar.setFixedHeight(56)
        bh = QHBoxLayout(self.bar)
        bh.setContentsMargins(6, 3, 6, 3)
        bh.setSpacing(0)
        self.a_queue = ActionBtn("queue", T("Cola"))
        self.a_queue.setToolTip(T("Todas las canciones, carpetas, artistas y géneros"))
        self.a_queue.clicked.connect(self.toggle_library)
        self.a_lyr = ActionBtn("mic", T("Letra"))
        self.a_lyr.setToolTip(T("Letra de la canción (L)"))
        self.a_lyr.clicked.connect(self.toggle_lyrics)
        self.a_fx = ActionBtn("eqbars", T("Ajustes"))
        self.a_fx.setToolTip(T("Ajustes de la canción: graves, agudos, tempo, tono, velocidad, bucle, eco…"))
        self.a_fx.clicked.connect(self.main.open_fx)
        self.a_edit = ActionBtn("edit", T("Editar"))
        self.a_edit.setToolTip(T("Editar los datos y la portada de esta canción en el editor"))
        self.a_edit.clicked.connect(self.edit_song)
        self.a_q = ActionBtn("wave", T("Calidad"))
        self.a_q.setToolTip(T("Espectrograma y análisis de calidad de esta canción"))
        self.a_q.clicked.connect(self.quality_song)
        for i, b in enumerate((self.a_queue, self.a_lyr, self.a_fx, self.a_edit, self.a_q)):
            if i:
                bh.addStretch(1)
            bh.addWidget(b)
        v.addWidget(self.bar)

        # ---- letra encima de la portada
        self.panel = Panel(self)
        self.panel.setGeometry(self.cover_rect.toRect())
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(14, 10, 8, 10)
        pv.setSpacing(4)
        self.p_head = QLabel(T("LETRA"))
        self.p_head.setStyleSheet("QLabel { color: rgba(255,255,255,165); font-size: 10px; font-weight: 800; "
                                  "letter-spacing: 1px; background: transparent; }")
        pv.addWidget(self.p_head)
        self.lyr = QTextBrowser()
        self.lyr.setOpenLinks(False)
        self.lyr.setFrameShape(QFrame.Shape.NoFrame)
        self.lyr.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lyr.setStyleSheet("QTextBrowser { background: transparent; color: rgba(255,255,255,175); font-size: 14px; "
                               "border: none; }")
        pv.addWidget(self.lyr, 1)
        self.panel.hide()

        # ---- biblioteca («Cola»): ocupa todo menos la barra de acciones
        self.lib = LibraryPage(self)
        self.lib.setGeometry(M, M, self.W, self.H - 12 - 56 - 8)
        self.lib.hide()

        self._save_pos = QTimer(self)
        self._save_pos.setSingleShot(True)
        self._save_pos.setInterval(400)
        self._save_pos.timeout.connect(lambda: self.main.cfg.setValue("mini_pos", f"{self.x()},{self.y()}"))
        self._toast = QTimer(self)
        self._toast.setSingleShot(True)
        self._toast.timeout.connect(self.update_caption)

        pl = main.player
        if pl is not None:
            pl.positionChanged.connect(self.on_pos)
            pl.durationChanged.connect(self.on_dur)
            pl.playbackStateChanged.connect(self.on_state)

    # ------------------------------------------------------------ colocar en pantalla
    def place_initial(self, main_geo):
        pos = None
        try:
            x, y = (int(t) for t in str(self.main.cfg.value("mini_pos", "") or "").split(","))
            pos = QPoint(x, y)
        except (ValueError, TypeError):
            pos = None
        scr = QGuiApplication.screenAt(pos + QPoint(self.width() // 2, 40)) if pos is not None else None
        if scr is None:   # primera vez (o la pantalla ya no está): a la derecha de donde estaba el editor
            scr = QGuiApplication.screenAt(main_geo.center()) or QGuiApplication.primaryScreen()
            pos = QPoint(main_geo.right() - self.width() - 10, main_geo.top() + (main_geo.height() - self.height()) // 2)
        ag = scr.availableGeometry()
        x = min(max(pos.x(), ag.left() - M), ag.right() - self.width() + M)
        y = min(max(pos.y(), ag.top() - M), ag.bottom() - self.height() + M)
        self.move(x, y)

    def moveEvent(self, e):
        if self.isVisible():
            self._save_pos.start()
        super().moveEvent(e)

    def set_top(self, on):
        self.top = bool(on)
        self.main.cfg.setValue("mini_top", 1 if self.top else 0)
        vis, pos = self.isVisible(), self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.top)
        if vis:
            self.move(pos)
            self.show()

    # ------------------------------------------------------------ fondo (se dibuja una vez por canción)
    def card(self):
        return QRectF(M, M, self.W, self.H)

    def bg_pixmap(self):
        """Sombra, degradado con los colores de la portada, la portada muy difuminada que se mezcla con el fondo,
        grano y la portada nítida en su tarjeta. Todo en una imagen: al repintar solo se copia el trozo necesario."""
        dpr = self.devicePixelRatioF()
        key = (id(self.img), self.W, self.H, dpr)
        if self._bg_key == key and self._bg is not None:
            return self._bg
        pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = self.card()
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(M, 0, -1):   # sombra suave alrededor de la ventanita
            p.setBrush(QColor(0, 0, 0, 7))
            p.drawRoundedRect(r.adjusted(-i * 0.8, -i * 0.5, i * 0.8, i * 1.0), RADIUS + i, RADIUS + i)
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        p.setClipPath(path)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0.0, self.col)
        g.setColorAt(0.48, self.col2)
        g.setColorAt(1.0, QColor(14, 14, 20))
        p.fillRect(r, QBrush(g))
        if self.blur is not None:   # la portada enorme y difuminada, que se desvanece hacia abajo (la «mezcla»)
            lay = QPixmap(pm.size())
            lay.setDevicePixelRatio(dpr)
            lay.fill(Qt.GlobalColor.transparent)
            q = QPainter(lay)
            q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            q.drawPixmap(QRectF(r.left() - 40, r.top() - 30, r.width() + 80, r.height() * 0.95), self.blur,
                         QRectF(self.blur.rect()))
            q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            fade = QLinearGradient(0, r.top(), 0, r.top() + r.height() * 0.78)
            fade.setColorAt(0.0, QColor(0, 0, 0, 255))
            fade.setColorAt(0.45, QColor(0, 0, 0, 200))
            fade.setColorAt(1.0, QColor(0, 0, 0, 0))
            q.fillRect(QRectF(0, 0, self.width(), self.height()), QBrush(fade))
            q.end()
            p.setOpacity(0.62)
            p.drawPixmap(0, 0, lay)
            p.setOpacity(1.0)
        g2 = QLinearGradient(0, r.top(), 0, r.bottom())   # un poco más oscuro arriba y abajo: el texto se lee bien
        g2.setColorAt(0.0, QColor(0, 0, 0, 70))
        g2.setColorAt(0.25, QColor(0, 0, 0, 10))
        g2.setColorAt(0.6, QColor(0, 0, 0, 30))
        g2.setColorAt(1.0, QColor(0, 0, 0, 110))
        p.fillRect(r, QBrush(g2))
        p.setOpacity(0.045)   # grano
        p.drawTiledPixmap(r.toRect(), self.noise)
        p.setOpacity(1.0)
        # portada en su tarjeta, con sombra
        cr = self.cover_rect
        for i in range(14, 0, -1):
            p.setBrush(QColor(0, 0, 0, 9))
            p.drawRoundedRect(cr.adjusted(-i * 0.7, -i * 0.3, i * 0.7, i * 1.1), 18 + i, 18 + i)
        cp = QPainterPath()
        cp.addRoundedRect(cr, 18, 18)
        p.save()
        p.setClipPath(cp)
        if self.img is not None:
            sc = self.img.scaled(int(cr.width() * dpr), int(cr.height() * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            sx, sy = (sc.width() - cr.width() * dpr) / 2, (sc.height() - cr.height() * dpr) / 2
            p.drawImage(cr, sc, QRectF(sx, sy, cr.width() * dpr, cr.height() * dpr))
        else:
            rg = QRadialGradient(QPointF(cr.left() + cr.width() * 0.35, cr.top() + cr.height() * 0.3), cr.width())
            rg.setColorAt(0, QColor(70, 62, 100))
            rg.setColorAt(1, QColor(34, 34, 46))
            p.fillRect(cr, QBrush(rg))
            icons.draw_glyph(p, "note", cr.adjusted(cr.width() * 0.33, cr.height() * 0.33, -cr.width() * 0.33,
                                                    -cr.height() * 0.33), QColor(255, 255, 255, 80))
        p.restore()
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QColor(255, 255, 255, 22))
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        p.end()
        self._bg, self._bg_key = pm, key
        return pm

    def paintEvent(self, e):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        dpr = self.devicePixelRatioF()
        r = QRectF(e.rect())
        p.drawPixmap(r, self.bg_pixmap(), QRectF(r.x() * dpr, r.y() * dpr, r.width() * dpr, r.height() * dpr))

    # ------------------------------------------------------------ canción
    def set_cover(self, img):
        self.img = img if img is not None and not img.isNull() else None
        self.col, self.col2 = pick_colors(self.img)
        if self.img is not None:
            tiny = self.img.scaled(8, 8, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            mid = tiny.scaled(40, 40, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.blur = QPixmap.fromImage(mid.scaled(240, 240, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        else:
            self.blur = None
        self.b_play.glow = QColor(self.col).lighter(150)
        self._bg_key = None

    def track_changed(self, path):
        self.path = path
        m = self.main
        if not path:
            self.title.setText(T("Nada sonando"))
            self.sub.setText(T("Toca «Cola» para elegir una canción"))
            self.set_cover(None)
            self.quality.set("", "", 5)
            self.wave.set_levels([])
            self.update_caption()
            self.sync_all()
            self.update()
            return
        title = m.val(path, "title") or os.path.splitext(os.path.basename(path))[0]
        artist = m.val(path, "artist") or T("Artista desconocido")
        wmax = self.W - 40
        self.title.setText(self.title.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, wmax))
        self.title.setToolTip(title)
        self.sub.setText(self.sub.fontMetrics().elidedText(artist, Qt.TextElideMode.ElideRight, wmax))
        album = m.val(path, "album")
        self.sub.setToolTip(" - ".join(x for x in (artist, album) if x))
        data = None
        try:
            data = m.cover_data_of(path)
        except Exception:
            pass
        self.set_cover(QImage.fromData(data) if data else None)
        info = {}
        try:
            info = self.tech_fn(path) if self.tech_fn else {}
        except Exception:
            info = {}
        self.quality.set(*quality_of(info))
        try:
            pend = m.pending.get(path, {})
            text = pend.get("lyrics")
            if text is None:
                text = (self.inspect_file(path) if self.inspect_file else {}).get("lyrics", "")
        except Exception:
            text = ""
        self.lrc, self.plain = parse_lyrics(text or "")
        self.lrc_idx = -1
        if self.panel.isVisible():
            self.render_lyrics()
        viz = getattr(m, "viz", None)
        arr = getattr(viz, "data", None)
        lv = envelope(arr) if arr is not None else []
        self.wave.set_levels(lv or placeholder_wave(path))
        self.update_caption()
        self.sync_all()
        self.lib.list.viewport().update()
        self.lib.strip.update_now()
        self.update()

    def update_caption(self):
        """«1483 de 3786»: qué número es la canción en la lista que se está recorriendo."""
        self.cap1.setText(T("REPRODUCIENDO"))
        txt = ""
        try:
            seq, _ = self.main.play_seq()
            if self.path in seq:
                txt = T(f"{seq.index(self.path) + 1} de {len(seq)}")
        except Exception:
            pass
        self.cap2.setText(txt)

    def set_viz(self, path, arr):
        """Llega el análisis del audio de la canción que suena: la onda pasa a ser la real."""
        if path == self.path and arr is not None:
            lv = envelope(arr)
            if lv:
                self.wave.set_levels(lv)

    def toast(self, text):
        """Mensaje cortito arriba (volumen, aleatorio…) en lugar del «1483 de 3786»."""
        self.cap2.setText(text)
        self._toast.start(1400)

    # ------------------------------------------------------------ letra
    def toggle_lyrics(self):
        if self.lib.isVisible():
            self.close_library()
        on = not self.panel.isVisible()
        self.panel.setVisible(on)
        self.a_lyr.set_active(on)
        if on:
            self.render_lyrics()
            self.panel.raise_()

    def render_lyrics(self):
        if self.lrc:
            rows = []
            for i, (_, w) in enumerate(self.lrc):
                if i == self.lrc_idx:
                    rows.append(f"<p id='cur' style='color:white; font-size:17px; font-weight:800; margin:9px 0'>"
                                f"{html.escape(w) or '♪'}</p>")
                else:
                    rows.append(f"<p style='margin:9px 0'>{html.escape(w) or '♪'}</p>")
            self.lyr.setHtml("<div style='text-align:center'>" + "".join(rows) + "</div>")
            if self.lrc_idx >= 0:
                self.lyr.scrollToAnchor("cur")
                sb = self.lyr.verticalScrollBar()
                sb.setValue(max(0, sb.value() - self.lyr.height() // 3))
        elif self.plain:
            self.lyr.setHtml("<div style='text-align:center; line-height:150%'>"
                             + html.escape(self.plain).replace("\n", "<br>") + "</div>")
        else:
            self.lyr.setHtml("<p style='text-align:center; margin-top:50px'>" + html.escape(T("Esta canción no tiene letra.")) + "</p>")

    # ------------------------------------------------------------ biblioteca («Cola»)
    def toggle_library(self):
        if self.lib.isVisible():
            self.close_library()
        else:
            self.open_library()

    def open_library(self):
        if self.panel.isVisible():
            self.toggle_lyrics()
        base = self.main.current_dir or str(self.main.cfg.value("last_dir", "") or "")
        self.lib.open_for(base)
        self.lib.show()
        self.lib.raise_()
        self.a_queue.set_active(True)

    def close_library(self):
        self.lib.hide()
        self.a_queue.set_active(False)
        self.setFocus()

    def play_from_library(self, path, seq):
        m = self.main
        m.pl_active = False
        m.mini_seq = list(seq)   # «siguiente» y «anterior» recorren esta lista
        m.play_file(path)

    # ------------------------------------------------------------ acciones
    def edit_song(self):
        p = self.path
        self.main.exit_mini()
        if p and os.path.isfile(p):
            self.main.go_to_folder(p)

    def quality_song(self):
        p = self.path
        self.main.exit_mini()
        if p and os.path.isfile(p):
            self.main.go_to_folder(p)
            QTimer.singleShot(300, self.main.open_spectrum)

    def show_menu(self, gpos):
        m = QMenu(self)
        m.addAction(T("Volver al editor"), self.main.exit_mini)
        a = m.addAction(T("Siempre encima de las demás ventanas"))
        a.setCheckable(True)
        a.setChecked(self.top)
        a.triggered.connect(lambda on: self.set_top(on))
        m.addAction(T("Minimizar"), self.showMinimized)
        m.addSeparator()
        mute = False
        try:
            mute = self.main.audio.isMuted()
        except Exception:
            pass
        m.addAction(T("Quitar silencio") if mute else T("Silenciar"), self.main.toggle_mute)
        m.addAction(T(f"Volumen: {self.main.vol.value()} % (rueda del ratón)")).setEnabled(False)
        m.addSeparator()
        m.addAction(T("Cerrar el programa"), self.main.quit_from_mini)
        m.exec(gpos)

    # ------------------------------------------------------------ reproductor
    def on_pos(self, ms):
        if not self.isVisible():
            return
        pl = self.main.player
        dur = pl.duration() if pl is not None else 0
        self.wave.set_pos(ms, dur)
        a, b = fmt(ms), "-" + fmt(max(0, dur - ms))
        if a != self.t_pos.text():   # solo cuando cambia el segundo
            self.t_pos.setText(a)
            self.t_left.setText(b)
        if self.lrc:
            idx = -1
            for i, (t, _) in enumerate(self.lrc):
                if t <= ms + 150:
                    idx = i
                else:
                    break
            if idx != self.lrc_idx:
                self.lrc_idx = idx
                if self.panel.isVisible():
                    self.render_lyrics()

    def on_dur(self, ms):
        pl = self.main.player
        pos = pl.position() if pl is not None else 0
        self.wave.set_pos(pos, ms)
        self.t_pos.setText(fmt(pos))
        self.t_left.setText("-" + fmt(max(0, ms - pos)))

    def on_state(self, st):
        from PyQt6.QtMultimedia import QMediaPlayer
        self.b_play.set_kind("pause" if st == QMediaPlayer.PlaybackState.PlayingState else "play")
        if self.lib.isVisible():
            self.lib.strip.update_now()

    def sync_modes(self):
        self.b_shuffle.set_active(bool(self.main.shuffle))
        rep = self.main.repeat
        self.b_repeat.set_kind("loop1" if rep == "one" else "loop")
        self.b_repeat.set_active(rep != "off")

    def sync_all(self):
        pl = self.main.player
        if pl is not None:
            self.on_dur(pl.duration())
            self.on_state(pl.playbackState())
        self.sync_modes()

    def toggle_shuffle(self):
        self.main.set_shuffle(not self.main.shuffle)
        self.sync_modes()
        self.toast(T("Aleatorio: sí") if self.main.shuffle else T("Aleatorio: no"))

    def cycle_repeat(self):
        nxt = {"off": "all", "all": "one", "one": "off"}.get(self.main.repeat, "off")
        self.main.set_repeat(nxt)
        self.sync_modes()
        self.toast({"off": T("Repetir: desactivado"), "all": T("Repetir: todas"), "one": T("Repetir: esta canción")}[nxt])

    def do_seek(self, ms):
        pl = self.main.player
        if pl is not None:
            pl.setPosition(ms)

    def skip(self, d):
        pl = self.main.player
        if pl is not None and pl.duration() > 0:
            pl.setPosition(max(0, min(pl.duration() - 500, pl.position() + d)))

    def change_vol(self, d):
        vs = self.main.vol
        vs.setValue(max(0, min(100, vs.value() + d)))
        self.toast(T(f"Volumen {vs.value()} %"))

    # ------------------------------------------------------------ ratón y teclado
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.globalPosition().toPoint()
            self._moved = False
            self._drag_off = None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.MouseButton.LeftButton):
            return
        gp = e.globalPosition().toPoint()
        if self._drag_off is not None:
            self.move(gp - self._drag_off)
            return
        if (gp - self._press).manhattanLength() > 5 and not self._moved:
            self._moved = True
            wh = self.windowHandle()
            if wh is not None and wh.startSystemMove():   # el sistema mueve la ventana (suave, con «snap» de Windows)
                self._press = None
                return
            self._drag_off = self._press - self.pos()   # por si el sistema no lo permite: se mueve a mano
            self.move(gp - self._drag_off)

    def mouseReleaseEvent(self, e):
        self._press, self._drag_off = None, None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if self.cover_rect.contains(e.position()) and not self.lib.isVisible():
            self.main.toggle_play()   # doble clic en la portada = reproducir / pausa (como en el celular)

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if d:
            self.change_vol(5 if d > 0 else -5)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key.Key_Space:
            self.main.toggle_play()
        elif k == Qt.Key.Key_Left:
            self.skip(-5000)
        elif k == Qt.Key.Key_Right:
            self.skip(5000)
        elif k == Qt.Key.Key_Up:
            self.change_vol(5)
        elif k == Qt.Key.Key_Down:
            self.change_vol(-5)
        elif k == Qt.Key.Key_Escape:
            if self.lib.isVisible():
                self.lib.go_back()
            elif self.panel.isVisible():
                self.toggle_lyrics()
            else:
                self.main.exit_mini()
        elif k == Qt.Key.Key_L:
            self.toggle_lyrics()
        else:
            super().keyPressEvent(e)

    def contextMenuEvent(self, e):
        self.show_menu(e.globalPos())

    def showEvent(self, e):
        self.sync_all()
        self.update_caption()
        super().showEvent(e)

    def closeEvent(self, e):   # Alt+F4 o cerrar desde la barra de tareas: vuelve al editor
        e.ignore()
        self.main.exit_mini()

    def shutdown(self):
        """Al cerrar el programa: detiene los hilos de la biblioteca."""
        try:
            self.lib.shutdown()
        except Exception:
            pass

"""Modo reproductor: el editor se esconde y queda solo un reproductor pequeño que se puede mover a cualquier parte
de la pantalla. La portada se funde (difuminado) con un fondo del color de la canción, como en los reproductores del
celular; debajo van el título, la onda de la canción para avanzar con los controles encima, los tiempos, la calidad
del archivo y una barra con accesos rápidos."""
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
    """Color del fondo: el de la parte de abajo de la portada (así la portada se funde sin cortes), oscurecido para
    que el texto blanco se lea bien. Devuelve (color de arriba, color de abajo)."""
    if img is None or img.isNull():
        return QColor(46, 38, 72), QColor(16, 13, 26)
    small = img.scaled(24, 24, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    r = g = b = n = 0
    for y in range(16, 24):
        for x in range(24):
            c = small.pixelColor(x, y)
            r, g, b, n = r + c.red(), g + c.green(), b + c.blue(), n + 1
    base = QColor(r // n, g // n, b // n)
    h, s, l, _ = base.getHslF()
    h = max(h, 0.0)
    l2 = min(max(l, 0.13), 0.30)
    s2 = min(s, 0.72)
    return QColor.fromHslF(h, s2, l2), QColor.fromHslF(h, min(1.0, s2 * 1.05), l2 * 0.42)


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
    """Botón redondo dibujado: «plain» (icono blanco), «dark» (círculo negro, como los controles de la imagen)
    o «glass» (círculo oscuro translúcido, para los botones sobre la portada)."""

    def __init__(self, kind, size=36, style="plain", pad=0.27, parent=None):
        super().__init__(parent)
        self.kind, self.style_, self.pad, self.active = kind, style, pad, False
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
        if self.style_ == "dark":
            p.setBrush(QColor(52, 52, 58) if down else QColor(30, 30, 34) if hov else QColor(6, 6, 8, 240))
            p.drawEllipse(r)
            col = QColor(255, 255, 255)
        elif self.style_ == "glass":
            p.setBrush(QColor(0, 0, 0, 140 if hov else 85))
            p.drawEllipse(r)
            col = QColor(255, 255, 255, 245 if (hov or self.active) else 215)
        else:
            if hov:
                p.setBrush(QColor(255, 255, 255, 30))
                p.drawEllipse(r)
            col = QColor(255, 255, 255) if (self.active or hov) else QColor(255, 255, 255, 170)
        if self.active and self.style_ != "dark":
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
    """La onda de la canción: lo ya escuchado en blanco, lo que falta más tenue. Clic o arrastrar = ir a ese punto.
    Los controles de reproducción van encima, en el centro."""
    seek = pyqtSignal(int)
    BW, GAP = 5, 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self.levels, self.pos, self.dur = [], 0, 0
        self.drag, self.hover = None, None
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(116)
        self.btns = []

    def set_levels(self, lv):
        self.levels = list(lv or [])
        self.update()

    def set_pos(self, pos, dur):
        """Solo se repinta cuando cambia el número de barras ya escuchadas (no en cada aviso del reproductor:
        repintar la ventanita transparente decenas de veces por segundo la ponía lenta)."""
        self.pos, self.dur = pos or 0, dur or 0
        n = self.geo()[0]
        k = int((self.pos / self.dur if self.dur else 0.0) * n + 0.5)
        if k != getattr(self, "_k", None) or self.drag is not None:
            self._k = k
            self.update()

    def geo(self):
        n = max(16, int((self.width() + self.GAP) // (self.BW + self.GAP)))
        tw = n * self.BW + (n - 1) * self.GAP
        return n, (self.width() - tw) / 2.0, tw

    def frac_at(self, x):
        _, x0, tw = self.geo()
        return min(1.0, max(0.0, (x - x0) / max(1.0, tw)))

    def resizeEvent(self, e):
        tot = sum(b.width() for b in self.btns) + 4 * (len(self.btns) - 1)
        x = (self.width() - tot) // 2
        for b in self.btns:
            b.move(x, (self.height() - b.height()) // 2)
            x += b.width() + 4
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        n, x0, tw = self.geo()
        lv = resample(self.levels, n)
        frac = self.drag if self.drag is not None else (self.pos / self.dur if self.dur else 0.0)
        hov = self.frac_at(self.hover) if self.hover is not None and self.drag is None else None
        cy, maxh = self.height() / 2.0, self.height() - 6
        for i, v in enumerate(lv):
            x = x0 + i * (self.BW + self.GAP)
            c = (x + self.BW / 2 - x0) / tw
            bh = max(6.0, maxh * (0.14 + 0.86 * v))
            if c <= frac:
                col = QColor(255, 255, 255, 240)
            elif hov is not None and c <= hov:
                col = QColor(255, 255, 255, 150)
            else:
                col = QColor(255, 255, 255, 80)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x, cy - bh / 2, self.BW, bh), self.BW / 2, self.BW / 2)

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


class Pill(QLabel):
    """Tiempos en una pastilla negra con las puntas redondas (como en la imagen)."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("QLabel { color: white; background: transparent; padding: 4px 11px; font-size: 12px; "
                           "font-weight: 800; }")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 220))
        r = QRectF(self.rect())
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.end()
        super().paintEvent(e)


class BottomBar(QWidget):
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 95))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)


class Panel(QWidget):
    """Letra o cola de reproducción encima de la portada, sobre un vidrio oscuro."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 165))
        p.drawRoundedRect(QRectF(self.rect()), 18, 18)


KIND_R, KEY_R, TITLE_R, SUB_R, RIGHT_R = (Qt.ItemDataRole.UserRole + i for i in range(5))


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
    """Fila de la biblioteca: icono redondo, título, subtítulo y (a la derecha) cuántas canciones."""

    def __init__(self, page):
        super().__init__(page)
        self.page = page

    def sizeHint(self, opt, idx):
        return QSize(max(10, opt.rect.width()), 46)

    def paint(self, p, opt, idx):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(opt.rect).adjusted(2, 1, -4, -1)
        kind = idx.data(KIND_R)
        playing = kind == "song" and idx.data(KEY_R) == self.page.main.playing_path
        if opt.state & QStyle.StateFlag.State_MouseOver or playing:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 34 if playing else 20))
            p.drawRoundedRect(r, 12, 12)
        ic = QRectF(r.left() + 6, r.center().y() - 16, 32, 32)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 235) if playing else QColor(255, 255, 255, 28))
        p.drawEllipse(ic)
        glyph = "eqbars" if playing else {"song": "note", "folder": "folder", "artist": "person",
                                           "genre": "tag", "info": "info"}.get(kind, "note")
        p.save()
        icons.draw_glyph(p, glyph, ic.adjusted(8, 8, -8, -8), QColor(18, 18, 22) if playing else QColor(255, 255, 255, 215))
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
        tx = ic.right() + 10
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
            p.drawText(QRectF(tx, r.top() + 5, tw, 19), Qt.AlignmentFlag.AlignVCenter,
                       QFontMetrics(ft).elidedText(title, Qt.TextElideMode.ElideRight, int(tw)))
            p.setFont(fs)
            p.setPen(QColor(255, 255, 255, 150))
            p.drawText(QRectF(tx, r.top() + 23, tw, 17), Qt.AlignmentFlag.AlignVCenter,
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
        self.b_play = IconBtn("play", 38, "dark", 0.30)
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
        v.addWidget(self.list, 1)
        self.strip = NowStrip(self)
        v.addWidget(self.strip)
        self.chips["songs"].setChecked(True)

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
        self.fcount, self.children, self.direct = {}, {}, {}
        base = os.path.normpath(self.base)
        for f in self.files:
            d = os.path.dirname(f)
            self.direct.setdefault(d, []).append(f)
            cur = d
            while True:
                self.fcount[cur] = self.fcount.get(cur, 0) + 1
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
        return ("song", f, title, sub, "")

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
                    rows.append(("folder", d, os.path.basename(d), "", str(self.fcount.get(d, 0))))
                rows += [self.song_row(f) for f in self.direct.get(folder, [])]
            else:
                idx = 1 if self.tab == "artists" else 3
                gr = self.groups(idx)
                self._shown_groups = len(gr)
                for name in sorted(gr, key=lambda n: (n == "", n.lower())):
                    rows.append(("artist" if idx == 1 else "genre", name,
                                 name or (T("(sin artista)") if idx == 1 else T("(sin género)")), "", str(len(gr[name]))))
                if not self.loaded:
                    rows.insert(0, ("info", "", T("Leyendo etiquetas…"), T(f"{self.read_pct} % — la lista se completa sola"), ""))
        if q:
            rows = [r for r in rows if r[0] == "info" or q in r[2].lower() or q in r[3].lower()
                    or (r[0] == "song" and q in os.path.basename(r[1]).lower())]
        self._shown_songs = sum(1 for r in rows if r[0] == "song")
        self._shown_rows = sum(1 for r in rows if r[0] != "info")
        self.list.setUpdatesEnabled(False)
        self.list.clear()
        for kind, key, title, sub, right in rows:
            it = QListWidgetItem()
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
        if not self.files:
            empty = QListWidgetItem()
            empty.setData(KIND_R, "info")
            empty.setData(TITLE_R, T("Buscando canciones…") if not self.loaded else T("No hay canciones aquí."))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)


class MiniPlayer(QWidget):
    BASE_W = 330
    BOTTOM = 340   # alto de la parte de abajo (título, onda, controles, barra)

    def __init__(self, main, inspect_file=None, tech_fn=None, read_fn=None, exts=None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.main, self.inspect_file, self.tech_fn = main, inspect_file, tech_fn
        self.read_fn = read_fn
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
        self.blur, self._layer, self._layer_key = None, None, None
        self._bg, self._bg_key = None, None
        self.noise = make_noise()
        self.lrc, self.lrc_idx, self.plain = [], -1, ""
        self._press, self._moved, self._drag_off = None, False, None
        self.top = bool(int(main.cfg.value("mini_top", 0) or 0))
        if self.top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        scr = QGuiApplication.primaryScreen()
        ah = scr.availableGeometry().height() if scr is not None else 900
        self.W = max(250, min(self.BASE_W, ah - self.BOTTOM - 2 * M - 8))
        self.H = self.W + self.BOTTOM
        self.setFixedSize(self.W + 2 * M, self.H + 2 * M)

        v = QVBoxLayout(self)
        v.setContentsMargins(M + 18, M + self.W - 16, M + 18, M + 14)
        v.setSpacing(4)
        self.title = QLabel("—")
        self.title.setStyleSheet("QLabel { color: white; font-size: 19px; font-weight: 800; background: transparent; }")
        self.sub = QLabel("")
        self.sub.setStyleSheet("QLabel { color: rgba(255,255,255,215); font-size: 13px; font-weight: 600; "
                               "background: transparent; }")
        for l in (self.title, self.sub):
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        v.addWidget(self.title)
        v.addWidget(self.sub)
        v.addSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(4)
        self.b_lyr = IconBtn("lyrics", 34)
        self.b_lyr.setToolTip(T("Letra (o clic en la portada)"))
        self.b_lyr.clicked.connect(lambda: self.show_panel("lyrics"))
        self.badge = QLabel("")
        self.badge.setStyleSheet("QLabel { color: rgba(255,255,255,225); font-size: 11px; font-weight: 800; "
                                 "background: transparent; }")
        self.b_shuffle = IconBtn("shuffle", 34)
        self.b_shuffle.setToolTip(T("Aleatorio"))
        self.b_shuffle.clicked.connect(self.toggle_shuffle)
        self.b_repeat = IconBtn("loop", 34)
        self.b_repeat.setToolTip(T("Repetir: no / todas / una"))
        self.b_repeat.clicked.connect(self.cycle_repeat)
        row.addWidget(self.b_lyr)
        row.addSpacing(10)
        row.addWidget(self.badge)
        row.addStretch(1)
        row.addWidget(self.b_shuffle)
        row.addSpacing(8)
        row.addWidget(self.b_repeat)
        v.addLayout(row)
        v.addSpacing(2)

        self.wave = WaveSeek()
        self.wave.seek.connect(self.do_seek)
        self.b_rew = IconBtn("rew", 44, "dark", 0.29, self.wave)
        self.b_prev = IconBtn("prev", 54, "dark", 0.30, self.wave)
        self.b_play = IconBtn("play", 68, "dark", 0.30, self.wave)
        self.b_next = IconBtn("next", 54, "dark", 0.30, self.wave)
        self.b_ffw = IconBtn("ffw", 44, "dark", 0.29, self.wave)
        self.wave.btns = [self.b_rew, self.b_prev, self.b_play, self.b_next, self.b_ffw]
        self.b_rew.setToolTip(T("Retroceder 10 s"))
        self.b_prev.setToolTip(T("Anterior"))
        self.b_play.setToolTip(T("Reproducir / pausa (Espacio)"))
        self.b_next.setToolTip(T("Siguiente"))
        self.b_ffw.setToolTip(T("Adelantar 10 s"))
        self.b_rew.clicked.connect(lambda: self.skip(-10000))
        self.b_ffw.clicked.connect(lambda: self.skip(10000))
        self.b_prev.clicked.connect(lambda: self.main.step_play(-1))
        self.b_next.clicked.connect(lambda: self.main.step_play(1))
        self.b_play.clicked.connect(self.main.toggle_play)
        v.addWidget(self.wave)

        tr_ = QHBoxLayout()
        self.t_pos, self.t_dur = Pill("0:00"), Pill("0:00")
        tr_.addWidget(self.t_pos)
        tr_.addStretch(1)
        tr_.addWidget(self.t_dur)
        v.addLayout(tr_)
        self.tech = QLabel("")
        self.tech.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tech.setStyleSheet("QLabel { color: rgba(255,255,255,230); font-size: 11px; font-weight: 800; "
                                "letter-spacing: 1px; background: transparent; }")
        v.addWidget(self.tech)
        v.addStretch(1)

        self.bar = BottomBar()
        self.bar.setFixedHeight(52)
        bh = QHBoxLayout(self.bar)
        bh.setContentsMargins(14, 0, 14, 0)
        self.b_editor = IconBtn("grid", 40, pad=0.25)
        self.b_editor.setToolTip(T("Biblioteca: todas las canciones, carpetas, artistas y géneros"))
        self.b_editor.clicked.connect(self.toggle_library)
        self.b_fx = IconBtn("eqbars", 40, pad=0.26)
        self.b_fx.setToolTip(T("Ajustes de la canción: graves, agudos, tempo, tono, velocidad, bucle, eco…"))
        self.b_fx.clicked.connect(self.main.open_fx)
        self.b_vol = IconBtn("vol2", 40, pad=0.25)
        self.b_vol.setToolTip(T("Clic: silenciar · rueda del ratón: volumen"))
        self.b_vol.clicked.connect(self.main.toggle_mute)
        self.b_list = IconBtn("menu", 40, pad=0.26)
        self.b_list.setToolTip(T("Cola de reproducción"))
        self.b_list.clicked.connect(lambda: self.show_panel("queue"))
        for b in (self.b_editor, self.b_fx, self.b_vol, self.b_list):
            bh.addWidget(b)
            if b is not self.b_list:
                bh.addStretch(1)
        v.addWidget(self.bar)

        # botones sobre la portada (aparecen al pasar el ratón)
        self.b_pin = IconBtn("pin", 30, "glass", 0.24, self)
        self.b_pin.setToolTip(T("Siempre encima de las demás ventanas"))
        self.b_pin.clicked.connect(lambda: self.set_top(not self.top))
        self.b_pin.set_active(self.top)
        self.b_min = IconBtn("minus", 30, "glass", 0.24, self)
        self.b_min.setToolTip(T("Minimizar"))
        self.b_min.clicked.connect(self.showMinimized)
        self.b_full = IconBtn("expand", 30, "glass", 0.24, self)
        self.b_full.setToolTip(T("Volver al editor (Esc)"))
        self.b_full.clicked.connect(self.main.exit_mini)
        self.b_pin.move(M + 14, M + 14)
        self.b_full.move(M + self.W - 14 - 30, M + 14)
        self.b_min.move(M + self.W - 14 - 30 - 36, M + 14)
        self.top_btns = (self.b_pin, self.b_min, self.b_full)
        for b in self.top_btns:
            b.hide()

        # letra / cola encima de la portada
        self.panel = Panel(self)
        self.panel.setGeometry(M + 12, M + 52, self.W - 24, self.W - 80)
        pv = QVBoxLayout(self.panel)
        pv.setContentsMargins(14, 10, 8, 10)
        pv.setSpacing(4)
        self.p_head = QLabel("")
        self.p_head.setStyleSheet("QLabel { color: rgba(255,255,255,165); font-size: 10px; font-weight: 800; "
                                  "letter-spacing: 1px; background: transparent; }")
        pv.addWidget(self.p_head)
        self.lyr = QTextBrowser()
        self.lyr.setOpenLinks(False)
        self.lyr.setFrameShape(QFrame.Shape.NoFrame)
        self.lyr.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lyr.setStyleSheet("QTextBrowser { background: transparent; color: rgba(255,255,255,175); font-size: 14px; "
                               "border: none; }")
        self.queue = QListWidget()
        self.queue.setFrameShape(QFrame.Shape.NoFrame)
        self.queue.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.queue.setStyleSheet(
            "QListWidget { background: transparent; color: rgba(255,255,255,205); font-size: 12px; border: none; outline: none; }"
            "QListWidget::item { padding: 6px 4px; border-radius: 8px; }"
            "QListWidget::item:hover { background: rgba(255,255,255,24); }"
            "QListWidget::item:selected { background: rgba(255,255,255,42); color: white; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,80); border-radius: 3px; min-height: 30px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }")
        self.queue.itemDoubleClicked.connect(self.play_from_queue)
        pv.addWidget(self.lyr, 1)
        pv.addWidget(self.queue, 1)
        self.panel.hide()
        self.panel_kind = None

        # biblioteca (todas las canciones, carpetas, artistas, géneros): ocupa todo menos la barra de abajo
        self.lib = LibraryPage(self)
        self.lib.setGeometry(M, M, self.W, self.H - 14 - 52 - 8)
        self.lib.hide()

        self._save_pos = QTimer(self)
        self._save_pos.setSingleShot(True)
        self._save_pos.setInterval(400)
        self._save_pos.timeout.connect(lambda: self.main.cfg.setValue("mini_pos", f"{self.x()},{self.y()}"))
        self._toast = QTimer(self)
        self._toast.setSingleShot(True)
        self._toast.timeout.connect(self.show_tech)
        self.tech_text = ""

        pl = main.player
        if pl is not None:
            pl.positionChanged.connect(self.on_pos)
            pl.durationChanged.connect(self.on_dur)
            pl.playbackStateChanged.connect(self.on_state)
        main.vol.valueChanged.connect(self.sync_vol)

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
        self.b_pin.set_active(self.top)

    # ------------------------------------------------------------ dibujo
    def card(self):
        return QRectF(M, M, self.W, self.H)

    def cover_layer(self):
        """La portada nítida que se va volviendo transparente hacia abajo y se funde con el fondo."""
        dpr = self.devicePixelRatioF()
        key = (id(self.img), self.W, dpr)
        if self._layer_key == key:
            return self._layer
        side = self.W
        pm = QPixmap(int(side * dpr), int(side * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.img is not None and not self.img.isNull():
            sc = self.img.scaled(int(side * dpr), int(side * dpr), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
            sx, sy = (sc.width() - side * dpr) / 2, (sc.height() - side * dpr) / 2
            q.drawImage(QRectF(0, 0, side, side), sc, QRectF(sx, sy, side * dpr, side * dpr))
        else:   # sin portada: degradado con una nota
            g = QRadialGradient(QPointF(side * 0.35, side * 0.3), side * 0.9)
            g.setColorAt(0, QColor(150, 110, 255))
            g.setColorAt(1, QColor(46, 38, 72))
            q.fillRect(QRectF(0, 0, side, side), QBrush(g))
            icons.draw_glyph(q, "note", QRectF(side * 0.33, side * 0.22, side * 0.34, side * 0.34), QColor(255, 255, 255, 120))
            q.resetTransform()
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        g = QLinearGradient(0, 0, 0, side)
        g.setColorAt(0.0, QColor(0, 0, 0, 255))
        g.setColorAt(0.50, QColor(0, 0, 0, 255))
        g.setColorAt(0.78, QColor(0, 0, 0, 120))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        q.fillRect(QRectF(0, 0, side, side), QBrush(g))
        q.end()
        self._layer, self._layer_key = pm, key
        return pm

    def bg_pixmap(self):
        """Todo el fondo (sombra, colores, portada difuminada, grano) se dibuja UNA vez en una imagen; al repintar
        solo se copia el trozo necesario. Antes se redibujaba entero en cada aviso del reproductor y se trababa."""
        dpr = self.devicePixelRatioF()
        dim = self.b_full.isVisible() or self.panel.isVisible() or self.lib.isVisible()
        key = (id(self.img), self.W, self.H, dpr, dim)
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
        for i in range(M, 0, -1):   # sombra suave alrededor
            p.setBrush(QColor(0, 0, 0, 7))
            p.drawRoundedRect(r.adjusted(-i * 0.8, -i * 0.5, i * 0.8, i * 1.0), RADIUS + i, RADIUS + i)
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)
        p.setClipPath(path)
        g = QLinearGradient(0, r.top(), 0, r.bottom())
        g.setColorAt(0.0, self.col)
        g.setColorAt(0.55, self.col)
        g.setColorAt(1.0, self.col2)
        p.fillRect(r, QBrush(g))
        if self.blur is not None:   # la portada muy difuminada mezclada con el color: el fondo no queda plano
            p.setOpacity(0.30)
            p.drawPixmap(r.toRect(), self.blur)
            p.setOpacity(1.0)
        g2 = QLinearGradient(0, r.top() + self.W * 0.7, 0, r.bottom())
        g2.setColorAt(0, QColor(0, 0, 0, 0))
        g2.setColorAt(1, QColor(0, 0, 0, 80))
        p.fillRect(r, QBrush(g2))
        p.drawPixmap(QPointF(r.left(), r.top()), self.cover_layer())
        if dim:   # oscurece un poco arriba para que se vean los botones
            g3 = QLinearGradient(0, r.top(), 0, r.top() + 80)
            g3.setColorAt(0, QColor(0, 0, 0, 110))
            g3.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(r.left(), r.top(), r.width(), 80), QBrush(g3))
        p.setOpacity(0.045)   # grano
        p.drawTiledPixmap(r.toRect(), self.noise)
        p.setOpacity(1.0)
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
            tiny = self.img.scaled(6, 10, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            mid = tiny.scaled(36, 60, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.blur = QPixmap.fromImage(mid.scaled(self.W, self.H, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))
        else:
            self.blur = None
        self._layer_key = None
        self._bg_key = None

    def track_changed(self, path):
        self.path = path
        m = self.main
        if not path:
            self.title.setText(T("Nada sonando"))
            self.sub.setText(T("Pulsa reproducir o vuelve al editor para elegir"))
            self.set_cover(None)
            self.tech_text, self.badge_text = "", ""
            self.badge.setText("")
            self.show_tech()
            self.wave.set_levels([])
            self.update()
            return
        title = m.val(path, "title") or os.path.splitext(os.path.basename(path))[0]
        sub = " - ".join(x for x in (m.val(path, "artist"), m.val(path, "album")) if x)
        wmax = self.W - 40
        self.title.setText(self.title.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, wmax))
        self.title.setToolTip(title)
        self.sub.setText(self.sub.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, wmax))
        self.sub.setToolTip(sub)
        data = None
        try:
            data = m.cover_data_of(path)
        except Exception:
            pass
        self.set_cover(QImage.fromData(data) if data else None)
        self.fill_tech(path)
        try:
            pend = m.pending.get(path, {})
            text = pend.get("lyrics")
            if text is None:
                text = (self.inspect_file(path) if self.inspect_file else {}).get("lyrics", "")
        except Exception:
            text = ""
        self.lrc, self.plain = parse_lyrics(text or "")
        self.lrc_idx = -1
        if self.panel_kind == "lyrics":
            self.render_lyrics()
        elif self.panel_kind == "queue":
            self.fill_queue()
        viz = getattr(m, "viz", None)
        arr = getattr(viz, "data", None)
        lv = envelope(arr) if arr is not None else []
        self.wave.set_levels(lv or placeholder_wave(path))
        self.sync_all()
        self.lib.list.viewport().update()
        self.lib.strip.update_now()
        self.update()

    def set_viz(self, path, arr):
        """Llega el análisis del audio de la canción que suena: la onda pasa a ser la real."""
        if path == self.path and arr is not None:
            lv = envelope(arr)
            if lv:
                self.wave.set_levels(lv)

    def fill_tech(self, path):
        info = {}
        try:
            info = self.tech_fn(path) if self.tech_fn else {}
        except Exception:
            info = {}
        info = info or {}
        bits = re.search(r"(\d+)\s*bits", str(info.get("enc", "")))
        freq = str(info.get("freq", "—"))
        br = str(info.get("bitrate", "—"))
        codec = str(info.get("codec", "—"))
        parts = []
        if bits:
            parts.append(f"{bits.group(1)} BIT")
        for x in (freq, br, codec):
            if x and x != "—":
                parts.append(x.upper())
        self.tech_text = "  ".join(parts)
        khz = re.match(r"([\d.]+)", freq)
        kb = re.match(r"(\d+)", br)
        if bits and khz:
            self.badge_text = f"{bits.group(1)}/{khz.group(1)}K"
        elif kb:
            self.badge_text = f"{kb.group(1)}K"
        else:
            self.badge_text = ""
        self.badge.setText(self.badge_text)
        self.badge.setToolTip(" · ".join(x for x in (info.get("enc_full") or info.get("enc", ""), freq, br,
                                                      info.get("ch", "")) if x and x != "—"))
        self.show_tech()

    def show_tech(self):
        self.tech.setText(self.tech_text)

    def toast(self, text):
        self.tech.setText(text)
        self._toast.start(1300)

    # ------------------------------------------------------------ letra y cola
    def show_panel(self, kind):
        if kind and self.lib.isVisible():
            self.close_library()
        if self.panel_kind == kind:
            kind = None
        self.panel_kind = kind
        self.b_lyr.set_active(kind == "lyrics")
        self.b_list.set_active(kind == "queue")
        if kind is None:
            self.panel.hide()
            self.update()
            return
        self.lyr.setVisible(kind == "lyrics")
        self.queue.setVisible(kind == "queue")
        if kind == "lyrics":
            self.p_head.setText(T("LETRA"))
            self.render_lyrics()
        else:
            self.fill_queue()
        self.panel.show()
        self.panel.raise_()
        for b in self.top_btns:
            b.raise_()
        self.update()

    # ------------------------------------------------------------ biblioteca
    def toggle_library(self):
        if self.lib.isVisible():
            self.close_library()
        else:
            self.open_library()

    def open_library(self):
        if self.panel_kind:
            self.show_panel(self.panel_kind)   # cierra la letra / cola
        base = self.main.current_dir or str(self.main.cfg.value("last_dir", "") or "")
        self.lib.open_for(base)
        self.lib.show()
        self.lib.raise_()
        for b in self.top_btns:
            b.hide()
        self.b_editor.set_active(True)
        self.update()

    def close_library(self):
        self.lib.hide()
        self.b_editor.set_active(False)
        self.setFocus()
        self.update()

    def play_from_library(self, path, seq):
        m = self.main
        m.pl_active = False
        m.mini_seq = list(seq)   # «siguiente» y «anterior» recorren esta lista
        m.play_file(path)

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

    def fill_queue(self):
        seq, from_pl = self.main.play_seq()
        self._q_from_pl = from_pl
        self.queue.clear()
        cur, cur_item = self.main.playing_path, None
        for n, p in enumerate(seq, 1):
            t = self.main.val(p, "title") or os.path.splitext(os.path.basename(p))[0]
            a = self.main.val(p, "artist")
            it = QListWidgetItem(f"{n}.  {t}" + (f"  ·  {a}" if a else ""))
            it.setData(Qt.ItemDataRole.UserRole, p)
            it.setToolTip(p)
            if p == cur:
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                it.setForeground(QColor("white"))
                it.setText("▶  " + it.text())
                cur_item = it
            self.queue.addItem(it)
        head = T("COLA DE REPRODUCCIÓN") if from_pl else T("CANCIONES DE LA CARPETA")
        self.p_head.setText(f"{head}  ·  {len(seq)}")
        if cur_item is not None:
            self.queue.setCurrentItem(cur_item)
            self.queue.scrollToItem(cur_item, QListWidget.ScrollHint.PositionAtCenter)

    def play_from_queue(self, it):
        p = it.data(Qt.ItemDataRole.UserRole)
        if not p:
            return
        if getattr(self, "_q_from_pl", False):
            self.main.play_file(p)
        else:
            r = self.main.row_index.get(p)
            if r is not None:
                self.main.play_item(self.main.list.item(r), user=False)
        self.fill_queue()

    # ------------------------------------------------------------ reproductor
    def player_dur(self):
        pl = self.main.player
        return pl.duration() if pl is not None else 0

    def on_pos(self, ms):
        if not self.isVisible():
            return
        dur = self.player_dur()
        self.wave.set_pos(ms, dur)
        txt = fmt(ms)
        if txt != self.t_pos.text():   # solo cuando cambia el segundo
            self.t_pos.setText(txt)
        if self.lrc:
            idx = -1
            for i, (t, _) in enumerate(self.lrc):
                if t <= ms + 150:
                    idx = i
                else:
                    break
            if idx != self.lrc_idx:
                self.lrc_idx = idx
                if self.panel_kind == "lyrics":
                    self.render_lyrics()

    def on_dur(self, ms):
        self.t_dur.setText(fmt(ms))
        pl = self.main.player
        self.wave.set_pos(pl.position() if pl is not None else 0, ms)

    def on_state(self, st):
        from PyQt6.QtMultimedia import QMediaPlayer
        self.b_play.set_kind("pause" if st == QMediaPlayer.PlaybackState.PlayingState else "play")
        if self.lib.isVisible():
            self.lib.strip.update_now()

    def sync_vol(self, x=None):
        if x is None:
            x = self.main.vol.value()
        muted = False
        try:
            muted = self.main.audio.isMuted()
        except Exception:
            pass
        self.b_vol.set_kind("vol0" if muted or x == 0 else ("vol1" if x < 34 else "vol2" if x < 67 else "vol3"))

    def sync_modes(self):
        self.b_shuffle.set_active(bool(self.main.shuffle))
        rep = self.main.repeat
        self.b_repeat.set_kind("loop1" if rep == "one" else "loop")
        self.b_repeat.set_active(rep != "off")

    def sync_all(self):
        pl = self.main.player
        if pl is not None:
            self.on_dur(pl.duration())
            self.on_pos(pl.position())
            self.on_state(pl.playbackState())
        self.sync_vol()
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
        if self._press is not None and not self._moved and not self.lib.isVisible():
            pos = e.position()
            cover = QRectF(M, M + 50, self.W, self.W - 70)
            if cover.contains(pos):
                self.show_panel("lyrics")   # clic en la portada = letra (otro clic la cierra)
        self._press, self._drag_off = None, None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        pass

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
        elif k == Qt.Key.Key_Escape and self.lib.isVisible():
            self.lib.go_back()
        elif k == Qt.Key.Key_Escape:
            if self.panel_kind:
                self.show_panel(self.panel_kind)
            else:
                self.main.exit_mini()
        elif k == Qt.Key.Key_L:
            self.show_panel("lyrics")
        else:
            super().keyPressEvent(e)

    def enterEvent(self, e):
        if self.lib.isVisible():
            return super().enterEvent(e)
        for b in self.top_btns:
            b.show()
            b.raise_()
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            for b in self.top_btns:
                b.hide()
            self.update()
        super().leaveEvent(e)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.addAction(T("Volver al editor"), self.main.exit_mini)
        m.addAction(T("Biblioteca"), self.toggle_library)
        a = m.addAction(T("Siempre encima"))
        a.setCheckable(True)
        a.setChecked(self.top)
        a.triggered.connect(lambda on: self.set_top(on))
        m.addAction(T("Minimizar"), self.showMinimized)
        m.addSeparator()
        m.addAction(T("Cerrar el programa"), self.main.quit_from_mini)
        m.exec(e.globalPos())

    def showEvent(self, e):
        self.sync_all()
        super().showEvent(e)

    def closeEvent(self, e):   # Alt+F4 o cerrar desde la barra de tareas: vuelve al editor
        e.ignore()
        self.main.exit_mini()

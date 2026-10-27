"""Iconos dibujados a mano (vectoriales) para los botones: sustituyen a los emojis y siguen el tema y el color."""
import math
from PyQt6.QtCore import Qt, QRectF, QPointF, QRect, QPoint, QSize
from PyQt6.QtGui import (QIcon, QIconEngine, QPainter, QPainterPath, QPen, QColor, QPixmap, QPolygonF, QPalette,
                         QGuiApplication, QFont)

# emoji (o símbolo) inicial del texto → icono
LEAD = {
    "💾": "save", "📌": "pin", "➕": "plus", "✂": "cut", "📋": "copy", "📥": "paste", "✏": "edit", "🗑": "trash",
    "🔍": "search", "🔎": "search", "📂": "folder", "☰": "menu", "🗂": "layers", "⇄": "swap", "⇅": "swapv",
    "📝": "lyrics", "↩": "undo", "↺": "undo", "▶": "play", "➡": "arrow_r", "⬅": "arrow_l", "✨": "sparkle",
    "🔄": "refresh", "⟳": "refresh", "⏮": "prev", "⏭": "next", "⏹": "stop", "⏸": "pause", "📊": "chart",
    "🤖": "bot", "🎨": "palette", "🌍": "globe", "❓": "help", "ℹ": "info", "⬇": "download", "🎼": "note",
    "💿": "disc", "💬": "chat", "✔": "check", "🔳": "grid", "🆕": "sparkle", "🔊": "vol3", "🔉": "vol2",
    "🔈": "vol1", "🔇": "vol0", "⋯": "more", "✕": "close", "◀": "arrow_l", "▲": "arrow_u", "🎚": "fx",
    "🔁": "loop", "🎵": "note", "⚙": "gear", "🌐": "globe", "🎧": "note", "📖": "lyrics", "🏷": "edit", "📤": "download",
}


def split(text):
    """('✨ Rellenar con IA…') → ('sparkle', 'Rellenar con IA…'); sin emoji → (None, texto)."""
    if not text:
        return None, text
    c = text[0]
    kind = LEAD.get(c)
    if kind is None:
        return None, text
    rest = text[1:].lstrip("️‍")
    return kind, rest.lstrip(" ")


def _pen(col, w=1.9):
    p = QPen(col, w)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return p


def _poly(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


def _line_path(pts, close=False):
    path = QPainterPath(QPointF(*pts[0]))
    for x, y in pts[1:]:
        path.lineTo(x, y)
    if close:
        path.closeSubpath()
    return path


def draw_glyph(p, kind, rect, col):
    """Dibuja el icono `kind` dentro de `rect` con el color `col` (cuadrícula de 24 × 24)."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(rect.topLeft())
    s = min(rect.width(), rect.height()) / 24.0
    p.translate((rect.width() - 24 * s) / 2, (rect.height() - 24 * s) / 2)
    p.scale(s, s)
    stroke, fill = _pen(col), QColor(col)
    nofill = Qt.BrushStyle.NoBrush
    p.setPen(stroke)
    p.setBrush(nofill)
    k = kind

    def solid():
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)

    def line(*pts):
        p.setPen(stroke)
        p.setBrush(nofill)
        p.drawPath(_line_path(pts))

    if k == "save":
        p.drawRoundedRect(QRectF(4, 4, 16, 16), 2.5, 2.5)
        p.drawRect(QRectF(8, 4, 8, 5.5))
        p.drawRoundedRect(QRectF(7.5, 13, 9, 7), 1, 1)
    elif k == "pin":
        p.drawEllipse(QPointF(12, 9), 4.5, 4.5)
        line((12, 13.5), (12, 21))
    elif k == "plus":
        line((12, 5), (12, 19))
        line((5, 12), (19, 12))
    elif k == "cut":
        p.drawEllipse(QPointF(7, 17.5), 2.8, 2.8)
        p.drawEllipse(QPointF(17, 17.5), 2.8, 2.8)
        line((8.5, 15), (16, 4))
        line((15.5, 15), (8, 4))
    elif k == "copy":
        p.drawRoundedRect(QRectF(8.5, 8.5, 11, 11), 2, 2)
        path = QPainterPath(QPointF(5.5, 15.5))
        path.lineTo(5.5, 6.5)
        path.quadTo(5.5, 4.5, 7.5, 4.5)
        path.lineTo(14.5, 4.5)
        p.drawPath(path)
    elif k == "paste":
        p.drawRoundedRect(QRectF(5, 5.5, 14, 15), 2, 2)
        p.drawRoundedRect(QRectF(8.5, 3.5, 7, 4), 1.5, 1.5)
    elif k == "edit":
        p.drawPath(_line_path([(5, 19), (5.8, 15), (16, 4.8), (19.2, 8), (9, 18.2)], True))
        line((14, 7), (17, 10))
    elif k == "trash":
        line((5, 7), (19, 7))
        line((9.5, 7), (9.5, 4.5), (14.5, 4.5), (14.5, 7))
        p.drawPath(_line_path([(6.5, 7), (7.5, 20), (16.5, 20), (17.5, 7)]))
        line((10.5, 11), (10.5, 16))
        line((13.5, 11), (13.5, 16))
    elif k == "search":
        p.drawEllipse(QPointF(10.5, 10.5), 6, 6)
        line((15, 15), (20, 20))
    elif k == "folder":
        path = QPainterPath(QPointF(3.5, 7))
        path.lineTo(3.5, 18)
        path.quadTo(3.5, 19.5, 5, 19.5)
        path.lineTo(19, 19.5)
        path.quadTo(20.5, 19.5, 20.5, 18)
        path.lineTo(20.5, 9.5)
        path.quadTo(20.5, 8, 19, 8)
        path.lineTo(12, 8)
        path.lineTo(10, 5.5)
        path.lineTo(5, 5.5)
        path.quadTo(3.5, 5.5, 3.5, 7)
        p.drawPath(path)
    elif k == "menu":
        for y in (6.5, 12, 17.5):
            line((4.5, y), (19.5, y))
    elif k == "layers":
        p.drawRoundedRect(QRectF(4, 8, 12, 12), 2, 2)
        line((8, 5), (18, 5), (20, 7), (20, 16))
    elif k in ("swap", "swapv"):
        if k == "swapv":
            p.translate(12, 12)
            p.rotate(90)
            p.translate(-12, -12)
        line((5, 8.5), (19, 8.5))
        line((15.5, 5), (19, 8.5), (15.5, 12))
        line((19, 15.5), (5, 15.5))
        line((8.5, 12), (5, 15.5), (8.5, 19))
    elif k == "lyrics":
        line((4.5, 6.5), (19.5, 6.5))
        line((4.5, 11), (15, 11))
        line((4.5, 15.5), (19.5, 15.5))
        line((4.5, 20), (11, 20))
    elif k == "undo":
        path = QPainterPath(QPointF(5, 9))
        path.lineTo(12, 9)
        path.cubicTo(17, 9, 19.5, 12, 19.5, 15)
        path.cubicTo(19.5, 18, 17, 20, 13.5, 20)
        p.drawPath(path)
        line((8.5, 5), (5, 9), (8.5, 13))
    elif k == "play":
        solid()
        p.drawPolygon(_poly([(7, 4.5), (7, 19.5), (19.5, 12)]))
    elif k == "pause":
        solid()
        p.drawRoundedRect(QRectF(6.5, 5, 4, 14), 1.4, 1.4)
        p.drawRoundedRect(QRectF(13.5, 5, 4, 14), 1.4, 1.4)
    elif k == "stop":
        solid()
        p.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif k == "prev":
        solid()
        p.drawRoundedRect(QRectF(5, 5, 2.8, 14), 1.2, 1.2)
        p.drawPolygon(_poly([(19, 5), (19, 19), (9, 12)]))
    elif k == "next":
        solid()
        p.drawRoundedRect(QRectF(16.2, 5, 2.8, 14), 1.2, 1.2)
        p.drawPolygon(_poly([(5, 5), (5, 19), (15, 12)]))
    elif k in ("arrow_r", "arrow_l", "arrow_u"):
        if k == "arrow_l":
            p.translate(12, 12)
            p.rotate(180)
            p.translate(-12, -12)
        elif k == "arrow_u":
            p.translate(12, 12)
            p.rotate(-90)
            p.translate(-12, -12)
        line((4.5, 12), (19, 12))
        line((13, 6), (19.5, 12), (13, 18))
    elif k == "sparkle":
        solid()
        path = QPainterPath(QPointF(10, 3.5))
        path.cubicTo(10.8, 8.5, 12, 9.7, 17, 10.5)
        path.cubicTo(12, 11.3, 10.8, 12.5, 10, 17.5)
        path.cubicTo(9.2, 12.5, 8, 11.3, 3, 10.5)
        path.cubicTo(8, 9.7, 9.2, 8.5, 10, 3.5)
        p.drawPath(path)
        small = QPainterPath(QPointF(18, 13.5))
        small.cubicTo(18.4, 16, 19, 16.6, 21.5, 17)
        small.cubicTo(19, 17.4, 18.4, 18, 18, 20.5)
        small.cubicTo(17.6, 18, 17, 17.4, 14.5, 17)
        small.cubicTo(17, 16.6, 17.6, 16, 18, 13.5)
        p.drawPath(small)
    elif k == "refresh":
        path = QPainterPath()
        path.arcMoveTo(QRectF(5, 5, 14, 14), 40)
        path.arcTo(QRectF(5, 5, 14, 14), 40, 280)
        p.drawPath(path)
        line((15.5, 3.5), (17.2, 7.2), (13.2, 8.2))
    elif k == "chart":
        for x, h in ((5, 8), (10.5, 14), (16, 10)):
            p.drawRoundedRect(QRectF(x, 20 - h, 3.5, h), 1, 1)
    elif k == "bot":
        p.drawRoundedRect(QRectF(4.5, 8, 15, 11), 3, 3)
        line((12, 8), (12, 4.5))
        solid()
        p.drawEllipse(QPointF(9, 13), 1.4, 1.4)
        p.drawEllipse(QPointF(15, 13), 1.4, 1.4)
        p.drawEllipse(QPointF(12, 4), 1.2, 1.2)
    elif k == "palette":
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        solid()
        for x, y in ((8, 10), (12, 7.5), (16, 10), (8.5, 15)):
            p.drawEllipse(QPointF(x, y), 1.3, 1.3)
    elif k == "globe":
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        p.drawEllipse(QPointF(12, 12), 3.8, 8.5)
        line((3.5, 12), (20.5, 12))
    elif k in ("help", "info"):
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        f = QFont()
        f.setBold(True)
        f.setPixelSize(13)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(3.5, 3.5, 17, 17), Qt.AlignmentFlag.AlignCenter, "?" if k == "help" else "i")
    elif k == "download":
        line((12, 4.5), (12, 15))
        line((7, 10.5), (12, 15.5), (17, 10.5))
        line((5, 19.5), (19, 19.5))
    elif k == "note":
        solid()
        p.drawEllipse(QPointF(8, 17.5), 3.2, 2.6)
        p.setPen(stroke)
        line((11, 17), (11, 5.5), (18, 4))
        line((18, 4), (18, 12.5))
        solid()
        p.drawEllipse(QPointF(15, 12.8), 3.2, 2.6)
    elif k == "disc":
        p.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        p.drawEllipse(QPointF(12, 12), 2.2, 2.2)
    elif k == "chat":
        path = QPainterPath(QPointF(5.5, 5))
        path.lineTo(18.5, 5)
        path.quadTo(20.5, 5, 20.5, 7)
        path.lineTo(20.5, 13)
        path.quadTo(20.5, 15, 18.5, 15)
        path.lineTo(11, 15)
        path.lineTo(7, 19)
        path.lineTo(7, 15)
        path.lineTo(5.5, 15)
        path.quadTo(3.5, 15, 3.5, 13)
        path.lineTo(3.5, 7)
        path.quadTo(3.5, 5, 5.5, 5)
        p.drawPath(path)
    elif k == "check":
        p.setPen(_pen(col, 2.3))
        p.drawPath(_line_path([(5, 12.5), (10, 17.5), (19, 7)]))
    elif k == "grid":
        for x in (4.5, 13.5):
            for y in (4.5, 13.5):
                p.drawRoundedRect(QRectF(x, y, 6, 6), 1.5, 1.5)
    elif k == "fx":   # tres deslizadores
        for x, y in ((6, 15), (12, 8), (18, 13)):
            line((x, 4.5), (x, 19.5))
            p.setBrush(fill)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), 2.7, 2.7)
            p.setPen(stroke)
    elif k.startswith("vol"):
        lvl = int(k[3])
        solid()
        p.drawPolygon(_poly([(4, 9.5), (8, 9.5), (13, 5), (13, 19), (8, 14.5), (4, 14.5)]))
        p.setPen(stroke)
        p.setBrush(nofill)
        if lvl == 0:
            line((16, 9.5), (21, 14.5))
            line((21, 9.5), (16, 14.5))
        else:
            for i in range(lvl):
                r = 3 + i * 3
                path = QPainterPath()
                path.arcMoveTo(QRectF(13 - r + 2, 12 - r, 2 * r, 2 * r), -45)
                path.arcTo(QRectF(13 - r + 2, 12 - r, 2 * r, 2 * r), -45, 90)
                p.drawPath(path)
    elif k == "more":
        solid()
        for x in (5.5, 12, 18.5):
            p.drawEllipse(QPointF(x, 12), 1.9, 1.9)
    elif k == "close":
        line((6, 6), (18, 18))
        line((18, 6), (6, 18))
    elif k == "loop":
        line((6, 10), (6, 8.5), (8, 6.5), (17, 6.5))
        line((14, 3.5), (17, 6.5), (14, 9.5))
        line((18, 14), (18, 15.5), (16, 17.5), (7, 17.5))
        line((10, 14.5), (7, 17.5), (10, 20.5))
    elif k == "shuffle":
        p.drawPath(_line_path([(4, 7), (8, 7), (15, 17), (19.5, 17)]))
        p.drawPath(_line_path([(4, 17), (8, 17), (10.5, 13.3)]))
        p.drawPath(_line_path([(12.6, 10.4), (15, 7), (19.5, 7)]))
        line((17, 4.5), (19.5, 7), (17, 9.5))
        line((17, 14.5), (19.5, 17), (17, 19.5))
    elif k in ("loop1", "chevron_l", "chevron_r"):
        if k == "loop1":
            line((6, 10), (6, 8.5), (8, 6.5), (17, 6.5))
            line((14, 3.5), (17, 6.5), (14, 9.5))
            line((18, 14), (18, 15.5), (16, 17.5), (7, 17.5))
            line((10, 14.5), (7, 17.5), (10, 20.5))
            f = QFont()
            f.setBold(True)
            f.setPixelSize(8)
            p.setFont(f)
            p.setPen(col)
            p.drawText(QRectF(8, 8, 8, 8), Qt.AlignmentFlag.AlignCenter, "1")
        elif k == "chevron_l":
            p.setPen(_pen(col, 2.6))
            p.drawPath(_line_path([(15, 5), (8, 12), (15, 19)]))
        else:
            p.setPen(_pen(col, 2.6))
            p.drawPath(_line_path([(9, 5), (16, 12), (9, 19)]))
    elif k == "gear":
        p.drawEllipse(QPointF(12, 12), 3, 3)
        for i in range(8):
            a = math.radians(i * 45)
            line((12 + 6.5 * math.cos(a), 12 + 6.5 * math.sin(a)), (12 + 9 * math.cos(a), 12 + 9 * math.sin(a)))
        p.drawEllipse(QPointF(12, 12), 6.3, 6.3)


class VIconEngine(QIconEngine):
    def __init__(self, kind, color=None, ctx=None):
        super().__init__()
        self.kind, self.color, self.ctx = kind, color, ctx   # ctx: 'check' (botón marcable) o 'menu'

    def _col(self, mode, state=None):
        if mode != QIcon.Mode.Disabled and (
                (self.ctx == "check" and state == QIcon.State.On) or (self.ctx == "menu" and mode != QIcon.Mode.Normal)):
            return QColor("white")   # botón marcado / opción de menú resaltada: fondo de color
        if self.color is not None:
            c = QColor(self.color)
            return c if mode != QIcon.Mode.Disabled else QColor(c.red(), c.green(), c.blue(), 110)
        pal = QGuiApplication.palette()
        R, G = QPalette.ColorRole, QPalette.ColorGroup
        if mode == QIcon.Mode.Disabled:
            return pal.color(G.Disabled, R.ButtonText)
        if mode == QIcon.Mode.Selected:
            return pal.color(R.HighlightedText)
        return pal.color(R.ButtonText)

    def paint(self, painter, rect, mode, state):
        painter.save()
        draw_glyph(painter, self.kind, QRectF(rect), self._col(mode, state))
        painter.restore()

    def pixmap(self, size, mode, state):
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self.paint(p, QRect(QPoint(0, 0), size), mode, state)
        p.end()
        return pm

    def clone(self):
        return VIconEngine(self.kind, self.color, self.ctx)


def vicon(kind, color=None, ctx=None):
    return QIcon(VIconEngine(kind, color, ctx))


from PyQt6.QtCore import QObject, QEvent
from PyQt6.QtWidgets import QAbstractButton, QMenu, QDialog, QMessageBox, QWidget


def flag_pixmap(code, w=44, h=30):
    """Banderita dibujada para el selector de idioma (es = España, en = EE. UU., ru = Rusia)."""
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)
    p.setClipPath(clip)
    p.setPen(Qt.PenStyle.NoPen)
    if code == "es":
        p.fillRect(QRectF(0, 0, w, h), QColor("#AA151B"))
        p.fillRect(QRectF(0, h / 4, w, h / 2), QColor("#F1BF00"))
    elif code == "ru":
        for i, c in enumerate(("#FFFFFF", "#0039A6", "#D52B1E")):
            p.fillRect(QRectF(0, i * h / 3, w, h / 3 + 0.5), QColor(c))
    else:   # en
        sh = h / 13.0
        for i in range(13):
            p.fillRect(QRectF(0, i * sh, w, sh + 0.3), QColor("#B22234" if i % 2 == 0 else "#FFFFFF"))
        cw, ch = w * 0.42, sh * 7
        p.fillRect(QRectF(0, 0, cw, ch), QColor("#3C3B6E"))
        p.setBrush(QColor("#FFFFFF"))
        for r in range(4):
            for c in range(5):
                p.drawEllipse(QPointF(cw * (c + 0.5) / 5, ch * (r + 0.5) / 4), 0.9, 0.9)
    p.setClipping(False)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 60), 1))
    p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 4, 4)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return pm


def flag_icon(code):
    return QIcon(flag_pixmap(code))


class IconDeco(QObject):
    """Filtro global: cuando se muestra un botón o un menú cuyo texto empieza con emoji, lo cambia por un icono dibujado."""
    def eventFilter(self, o, e):
        try:
            if e.type() == QEvent.Type.Show:
                if isinstance(o, QAbstractButton):
                    t = o.text()
                    if t and t[0] in LEAD:
                        import i18n
                        i18n.deco(o)
                elif isinstance(o, QMenu):
                    import i18n
                    for a in o.actions():
                        t = a.text()
                        if t and (t[0] in LEAD and a.icon().isNull() or i18n.CUR != "es"):
                            i18n.deco(a)
                elif o.isWindow() and isinstance(o, (QDialog, QMessageBox)):
                    import i18n
                    i18n.retranslate(o)   # traduce ventanas y avisos creados sobre la marcha
                if not o.isWindow() and isinstance(o, QWidget):
                    import i18n
                    if i18n.CUR != "es":
                        i18n.retranslate_widget(o)   # controles que aparecen después (resultados, avisos…)
        except Exception:
            pass
        return False

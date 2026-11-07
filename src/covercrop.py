"""Recortar portadas que no son cuadradas (por ejemplo 712×1000) para dejarlas en 1000×1000, 600×600…
Se muestra la imagen con un recuadro cuadrado que se puede mover (arrastrando) y agrandar o achicar
(con las esquinas o la rueda del ratón); lo de fuera se oscurece."""
from PyQt6.QtCore import Qt, QRectF, QPointF, QByteArray, QBuffer, QIODevice, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QPainterPath, QPalette
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox, QWidget,
                             QSizePolicy)
from i18n import tr as T

HANDLE = 12


def is_square(w, h, tol=0.01):
    return w > 0 and h > 0 and abs(w - h) <= max(2, tol * max(w, h))


def crop_square(img, x, y, s, out_side):
    """Recorta el cuadrado (x, y, s) de la imagen y lo deja en out_side×out_side. Devuelve bytes JPG."""
    part = img.copy(int(x), int(y), int(s), int(s))
    if out_side and part.width() != out_side:
        part = part.scaled(out_side, out_side, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    if part.hasAlphaChannel():
        part = part.convertToFormat(QImage.Format.Format_RGB32)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    part.save(buf, "JPG", 92)
    return bytes(ba)


def centered_square(w, h):
    s = min(w, h)
    return (w - s) / 2, (h - s) / 2, s


class CropView(QWidget):
    changed = pyqtSignal()

    def __init__(self, img, parent=None):
        super().__init__(parent)
        self.img = img
        self.pm = QPixmap.fromImage(img)
        self.sel = list(centered_square(img.width(), img.height()))   # x, y, lado (en píxeles de la imagen)
        self.drag = None
        self.setMinimumSize(420, 420)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    # ---- conversión imagen <-> pantalla
    def geo(self):
        w, h = self.img.width(), self.img.height()
        k = min((self.width() - 16) / w, (self.height() - 16) / h)
        ox, oy = (self.width() - w * k) / 2, (self.height() - h * k) / 2
        return k, ox, oy

    def sel_rect(self):
        k, ox, oy = self.geo()
        x, y, s = self.sel
        return QRectF(ox + x * k, oy + y * k, s * k, s * k)

    def clamp(self):
        w, h = self.img.width(), self.img.height()
        x, y, s = self.sel
        s = max(min(s, w, h), min(w, h) * 0.15)
        x = max(0.0, min(x, w - s))
        y = max(0.0, min(y, h - s))
        self.sel = [x, y, s]

    def set_centered(self):
        self.sel = list(centered_square(self.img.width(), self.img.height()))
        self.update()
        self.changed.emit()

    # ---- dibujo
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        k, ox, oy = self.geo()
        full = QRectF(ox, oy, self.img.width() * k, self.img.height() * k)
        p.drawPixmap(full, self.pm, QRectF(self.pm.rect()))
        r = self.sel_rect()
        shade = QPainterPath()
        shade.addRect(full)
        hole = QPainterPath()
        hole.addRect(r)
        p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 150))
        acc = self.palette().color(QPalette.ColorRole.Highlight)
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for i in (1, 2):   # líneas de tercios, como en las cámaras
            p.drawLine(QPointF(r.left() + r.width() * i / 3, r.top()), QPointF(r.left() + r.width() * i / 3, r.bottom()))
            p.drawLine(QPointF(r.left(), r.top() + r.height() * i / 3), QPointF(r.right(), r.top() + r.height() * i / 3))
        p.setPen(QPen(acc, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("white"))
        for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
            p.drawRoundedRect(QRectF(c.x() - HANDLE / 2, c.y() - HANDLE / 2, HANDLE, HANDLE), 3, 3)
        p.end()

    # ---- ratón
    def corner_at(self, pos):
        r = self.sel_rect()
        for name, c in (("tl", r.topLeft()), ("tr", r.topRight()), ("bl", r.bottomLeft()), ("br", r.bottomRight())):
            if abs(pos.x() - c.x()) <= HANDLE and abs(pos.y() - c.y()) <= HANDLE:
                return name
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        c = self.corner_at(pos)
        if c:
            self.drag = ("resize", c, pos, list(self.sel))
        elif self.sel_rect().contains(pos):
            self.drag = ("move", None, pos, list(self.sel))
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:   # clic fuera: el recuadro se centra ahí
            k, ox, oy = self.geo()
            x, y, s = self.sel
            self.sel = [(pos.x() - ox) / k - s / 2, (pos.y() - oy) / k - s / 2, s]
            self.clamp()
            self.drag = ("move", None, pos, list(self.sel))
            self.update()
            self.changed.emit()

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self.drag:
            c = self.corner_at(pos)
            self.setCursor(Qt.CursorShape.SizeFDiagCursor if c in ("tl", "br") else Qt.CursorShape.SizeBDiagCursor if c
                           else Qt.CursorShape.OpenHandCursor if self.sel_rect().contains(pos) else Qt.CursorShape.CrossCursor)
            return
        kind, c, start, (x0, y0, s0) = self.drag
        k, _, _ = self.geo()
        dx, dy = (pos.x() - start.x()) / k, (pos.y() - start.y()) / k
        if kind == "move":
            self.sel = [x0 + dx, y0 + dy, s0]
        else:   # cambiar tamaño manteniendo la esquina contraria fija (siempre cuadrado)
            if c == "br":
                s = s0 + max(dx, dy)
                self.sel = [x0, y0, s]
            elif c == "tl":
                s = s0 - min(dx, dy)
                self.sel = [x0 + s0 - s, y0 + s0 - s, s]
            elif c == "tr":
                s = s0 + max(dx, -dy)
                self.sel = [x0, y0 + s0 - s, s]
            else:   # bl
                s = s0 + max(-dx, dy)
                self.sel = [x0 + s0 - s, y0, s]
            w, h = self.img.width(), self.img.height()
            x, y, s = self.sel
            s = min(s, w, h)
            self.sel = [max(0.0, min(x, w - s)), max(0.0, min(y, h - s)), s]
        self.clamp()
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, e):
        self.drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, e):
        x, y, s = self.sel
        f = 0.95 if e.angleDelta().y() > 0 else 1.05
        ns = s * f
        self.sel = [x + (s - ns) / 2, y + (s - ns) / 2, ns]
        self.clamp()
        self.update()
        self.changed.emit()


class CropDialog(QDialog):
    """Devuelve (en .result_bytes) la portada recortada en cuadrado, o None si se salta."""

    def __init__(self, parent, data, side, name="", remaining=0):
        super().__init__(parent)
        self.setWindowTitle(T("Recortar portada en cuadrado"))
        self.resize(640, 760)
        self.img = QImage.fromData(data)
        self.result_bytes, self.apply_all, self.cancel_all = None, False, False
        v = QVBoxLayout(self)
        w, h = self.img.width(), self.img.height()
        info = QLabel(T(f"Esta portada no es cuadrada ({w}×{h} px). Mueve el recuadro hasta la parte que quieres "
                        f"conservar; agrándalo o achícalo con las esquinas o la rueda del ratón.") +
                      (f"\n«{name}»" if name else ""))
        info.setObjectName("dlgsub")
        info.setWordWrap(True)
        v.addWidget(info)
        self.view = CropView(self.img)
        self.view.changed.connect(self.update_info)
        v.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel(T("Tamaño final:")))
        self.size_cb = QComboBox()
        for s in (500, 600, 800, 1000, 1200):
            self.size_cb.addItem(f"{s} × {s} px", s)
        self.size_cb.setCurrentIndex(max(0, self.size_cb.findData(side if side in (500, 600, 800, 1000, 1200) else 1000)))
        self.size_cb.currentIndexChanged.connect(self.update_info)
        row.addWidget(self.size_cb)
        center = QPushButton(T("Centrar"))
        center.clicked.connect(self.view.set_centered)
        row.addWidget(center)
        row.addStretch(1)
        v.addLayout(row)
        self.note = QLabel("")
        self.note.setObjectName("dlgsub")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        self.all_chk = QCheckBox(T(f"Recortar centradas las otras {remaining} portadas que no son cuadradas (sin preguntar)"))
        self.all_chk.setVisible(remaining > 0)
        v.addWidget(self.all_chk)
        br = QHBoxLayout()
        skip = QPushButton(T("Saltar esta"))
        skip.clicked.connect(self.reject)
        cancel = QPushButton(T("Cancelar todo"))
        cancel.clicked.connect(self.do_cancel)
        ok = QPushButton(T("✂ Recortar y poner"))
        ok.setObjectName("accent")
        ok.setDefault(True)
        ok.clicked.connect(self.do_ok)
        br.addWidget(cancel)
        br.addStretch(1)
        br.addWidget(skip)
        br.addWidget(ok)
        v.addLayout(br)
        self.update_info()

    def update_info(self):
        x, y, s = self.view.sel
        out = self.size_cb.currentData()
        txt = T(f"Se recorta un cuadrado de {int(s)}×{int(s)} px y queda en {out}×{out} px.")
        if s < out * 0.9:
            txt += " " + T("Ojo: el trozo es más pequeño que el tamaño final, se verá algo menos nítido.")
        self.note.setText(txt)

    def side(self):
        return self.size_cb.currentData()

    def do_ok(self):
        x, y, s = self.view.sel
        self.result_bytes = crop_square(self.img, x, y, s, self.side())
        self.apply_all = self.all_chk.isVisible() and self.all_chk.isChecked()
        self.accept()

    def do_cancel(self):
        self.cancel_all = True
        self.reject()

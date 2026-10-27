"""Árboles de carpetas plegables: en modo «cajón» se esconden y salen deslizándose desde el borde izquierdo
con una flechita (igual que el reproductor celular por la derecha)."""
from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QObject, QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFrame, QVBoxLayout, QGraphicsDropShadowEffect
from mobile import EdgeTab


class TreeDrawer(QObject):
    def __init__(self, main, central, content, splitter):
        super().__init__(central)
        self.main, self.central, self.content, self.splitter = main, central, content, splitter
        self.enabled, self.closing = False, False
        self.frame = QFrame(central)
        self.frame.setObjectName("drawer")
        sh = QGraphicsDropShadowEffect(self.frame)
        sh.setBlurRadius(36)
        sh.setOffset(6, 0)
        sh.setColor(QColor(0, 0, 0, 160))
        self.frame.setGraphicsEffect(sh)
        self.lay = QVBoxLayout(self.frame)
        self.lay.setContentsMargins(10, 10, 10, 10)
        self.frame.hide()
        self.anim = QPropertyAnimation(self.frame, b"pos", self)
        self.anim.setDuration(240)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(lambda _v: self.place_tab())
        self.anim.finished.connect(self.anim_done)
        self.tab = EdgeTab(central, "left", ("Mostrar las carpetas", "Ocultar las carpetas"))
        self.tab.clicked.connect(self.toggle)
        self.tab.hide()
        central.installEventFilter(self)

    def width(self):
        tree2 = self.main.tree2_box.isVisible() and self.main.left_split.orientation() == Qt.Orientation.Horizontal
        return 620 if tree2 else 330

    def set_enabled(self, on):
        if on == self.enabled:
            return
        self.enabled = on
        if on:   # los árboles salen del panel principal y pasan al cajón
            self.splitter_sizes = self.splitter.sizes()
            self.lay.addWidget(self.content)
            self.content.show()
            self.tab.show()
            self.main._central_lay.setContentsMargins(20, 0, self.main._central_lay.contentsMargins().right(), 0)
        else:    # vuelven a su sitio de siempre
            self.anim.stop()
            self.frame.hide()
            self.tab.hide()
            self.splitter.insertWidget(0, self.content)
            self.content.show()
            self.splitter.setCollapsible(0, False)
            if getattr(self, "splitter_sizes", None):
                self.splitter.setSizes(self.splitter_sizes)
            m = self.main._central_lay.contentsMargins()
            self.main._central_lay.setContentsMargins(0, 0, m.right(), 0)
        self.place()

    def eventFilter(self, obj, ev):
        if obj is self.central and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.place()
        return False

    def is_open(self):
        return self.frame.isVisible() and not self.closing

    def toggle(self):
        self.close() if self.is_open() else self.open()

    def open(self):
        if not self.enabled:
            return
        h = self.central.height()
        self.frame.setFixedSize(self.width(), h)
        self.closing = False
        self.frame.move(-self.frame.width(), 0)
        self.frame.show()
        self.frame.raise_()
        self.tab.set_open(True)
        self.anim.stop()
        self.anim.setStartValue(QPoint(-self.frame.width(), 0))
        self.anim.setEndValue(QPoint(0, 0))
        self.anim.start()

    def close(self):
        if not self.frame.isVisible():
            return
        self.closing = True
        self.tab.set_open(False)
        self.anim.stop()
        self.anim.setStartValue(self.frame.pos())
        self.anim.setEndValue(QPoint(-self.frame.width(), 0))
        self.anim.start()

    def anim_done(self):
        if self.closing:
            self.frame.hide()
            self.closing = False
        self.place_tab()

    def place(self):
        if not self.enabled:
            return
        if self.frame.isVisible():
            self.frame.setFixedSize(self.width(), self.central.height())
            if self.anim.state() != QPropertyAnimation.State.Running and not self.closing:
                self.frame.move(0, 0)
            self.frame.raise_()
        self.place_tab()

    def place_tab(self):
        x = self.frame.x() + self.frame.width() if self.frame.isVisible() else 0
        self.tab.move(max(0, x), (self.central.height() - self.tab.height()) // 2)
        self.tab.raise_()

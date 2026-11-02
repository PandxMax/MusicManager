"""Árboles de carpetas plegables: en modo «escondidas» los árboles se pliegan y salen desde el borde izquierdo con
una flechita. Al abrirse empujan el resto del programa (no se montan encima)."""
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QObject, QEvent, QPoint
from mobile import EdgeTab

BIG = 16777215


class TreeDrawer(QObject):
    def __init__(self, main, central, content, splitter):
        super().__init__(central)
        self.main, self.central, self.content, self.splitter = main, central, content, splitter
        self.enabled, self.closing, self.opened = False, False, False
        self.anim = QPropertyAnimation(content, b"maximumWidth", self)
        self.anim.setDuration(240)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(lambda _v: self.place_tab())
        self.anim.finished.connect(self.anim_done)
        self.tab = EdgeTab(central, "left", ("Mostrar las carpetas", "Ocultar las carpetas"))
        self.tab.clicked.connect(self.toggle)
        self.tab.hide()
        self.min_left = main.left_split.minimumWidth()
        central.installEventFilter(self)
        splitter.splitterMoved.connect(lambda *_: self.place_tab())

    def target(self):
        tree2 = self.main.tree2_box.isVisible() and self.main.left_split.orientation() == Qt.Orientation.Horizontal
        return 620 if tree2 else 300

    def _free(self, on):
        """Durante la animación se quitan los mínimos para poder plegar del todo."""
        self.main.left_split.setMinimumWidth(0 if on else self.min_left)
        self.content.setMinimumWidth(0)

    def set_enabled(self, on):
        if on == self.enabled:
            self.place_tab()
            return
        self.enabled = on
        self.anim.stop()
        m = self.main._central_lay.contentsMargins()
        if on:
            self.saved = self.splitter.sizes()
            self.opened = False
            self.content.hide()
            self.tab.set_open(False)
            self.tab.show()
            self.main._central_lay.setContentsMargins(20, 0, m.right(), 0)   # canal propio para la flechita
            if int(self.main.cfg.value("trees_open", 0) or 0):
                self.open()
        else:
            self._free(False)
            self.content.setMaximumWidth(BIG)
            self.content.show()
            self.tab.hide()
            self.main._central_lay.setContentsMargins(0, 0, m.right(), 0)
            if getattr(self, "saved", None):
                self.splitter.setSizes(self.saved)
        self.place_tab()

    def eventFilter(self, obj, ev):
        if obj is self.central and ev.type() in (QEvent.Type.Resize, QEvent.Type.Show, QEvent.Type.LayoutRequest):
            self.place_tab()
        return False

    def toggle(self):
        self.close() if self.opened else self.open()

    def open(self):
        if not self.enabled:
            return
        self.opened, self.closing = True, False
        self.tab.set_open(True)
        self._free(True)
        self.content.setMaximumWidth(0)
        self.content.show()
        self.anim.stop()
        self.anim.setStartValue(0)
        self.anim.setEndValue(self.target())
        self.anim.start()
        self.main.cfg.setValue("trees_open", 1)

    def close(self):
        if not self.opened:
            return
        self.opened, self.closing = False, True
        self.tab.set_open(False)
        self._free(True)
        self.anim.stop()
        self.anim.setStartValue(self.content.width())
        self.anim.setEndValue(0)
        self.anim.start()
        self.main.cfg.setValue("trees_open", 0)

    def anim_done(self):
        if self.closing:
            self.content.hide()
            self.content.setMaximumWidth(BIG)
            self.closing = False
        elif self.opened:   # ya abierto: se puede volver a ajustar con el divisor como siempre
            w = self.target()
            self.content.setMaximumWidth(BIG)
            self._free(False)
            sizes = self.splitter.sizes()
            if len(sizes) == 2:
                self.splitter.setSizes([w, max(200, sum(sizes) - w)])
        self.place_tab()

    def place(self):
        self.place_tab()

    def place_tab(self):
        if not self.enabled:
            return
        # la flechita vive en su propio canal del borde izquierdo: abre («›») y cierra («‹») sin tapar nada
        self.tab.move(0, (self.central.height() - self.tab.height()) // 2)
        self.tab.raise_()

"""Reproductor «modo celular»: un panel que sale desde el borde derecho de la ventana con la portada grande,
fondo difuminado con los colores de la canción, barra de avance, controles grandes, aleatorio, repetir y letra."""
import re
from PyQt6.QtCore import (Qt, QPoint, QRect, QRectF, QPointF, QPropertyAnimation, QEasingCurve, QSize, pyqtSignal)
from PyQt6.QtGui import (QPainter, QPixmap, QColor, QLinearGradient, QBrush, QPainterPath, QPen, QFont, QImage, QPalette)
from PyQt6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QStackedWidget,
                             QListWidget, QListWidgetItem,
                             QTextBrowser, QStyle, QStyleOptionSlider, QGraphicsDropShadowEffect, QSizePolicy)
import icons
from i18n import tr as T

LRC_LINE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")


def fmt(ms):
    s = max(0, int(ms // 1000))
    return f"{s // 60}:{s % 60:02d}"


class JumpSlider(QSlider):
    """Barra que salta al punto donde haces clic."""
    jumped = pyqtSignal(int)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            gr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
            x = e.position().x() - gr.x()
            v = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(x), max(1, gr.width()))
            self.setValue(v)
            self.jumped.emit(v)
        super().mousePressEvent(e)


class RoundButton(QPushButton):
    """Botón redondo dibujado (el de reproducir es grande y blanco, los demás son iconos limpios)."""
    def __init__(self, kind, size=44, big=False):
        super().__init__()
        self.kind, self.big, self.active = kind, big, False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def set_active(self, on):
        self.active = on
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.big:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 245 if not self.isDown() else 210))
            p.drawEllipse(r)
            icons.draw_glyph(p, self.kind, r.adjusted(r.width() * .28, r.height() * .28, -r.width() * .28, -r.height() * .28),
                             QColor(20, 18, 30))
            return
        if self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 30))
            p.drawEllipse(r)
        col = QColor(255, 255, 255) if self.active or self.kind in ("prev", "next") else QColor(255, 255, 255, 150)
        if self.active:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPointF(r.center().x(), r.bottom() - 3), 2, 2)
        pad = r.width() * (.22 if self.kind in ("prev", "next") else .27)
        icons.draw_glyph(p, self.kind, r.adjusted(pad, pad, -pad, -pad), col)


class CoverArt(QWidget):
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.pm = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 160)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Clic: ver la letra")

    def set_pixmap(self, pm):
        self.pm = pm
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        side = min(self.width(), self.height())
        r = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        p.setClipPath(path)
        if self.pm is not None and not self.pm.isNull():
            p.drawPixmap(r.toRect(), self.pm.scaled(int(side * 2), int(side * 2), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                                    Qt.TransformationMode.SmoothTransformation))
        else:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor(80, 70, 120))
            g.setColorAt(1, QColor(30, 26, 48))
            p.fillRect(r, QBrush(g))
            icons.draw_glyph(p, "note", r.adjusted(side * .32, side * .32, -side * .32, -side * .32), QColor(255, 255, 255, 120))


class EdgeTab(QPushButton):
    """Asa discreta en el borde: «‹» abre el reproductor; con el reproductor abierto se pega a su lado con «›» para cerrarlo."""
    def __init__(self, parent, side="right", tips=("Abrir el reproductor grande", "Cerrar el reproductor grande")):
        super().__init__(parent)
        self.setFixedSize(18, 64)
        self.opened, self.side, self.tips = False, side, tips
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tips[0])
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_open(self, on):
        self.opened = on
        self.setToolTip(self.tips[1] if on else self.tips[0])
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        acc = self.palette().color(QPalette.ColorRole.Highlight)
        hover = self.underMouse()
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        if self.side == "right":
            path.addRoundedRect(QRectF(r.x(), r.y(), r.width() + 12, r.height()), 9, 9)   # redondeada solo por fuera
        else:
            path.addRoundedRect(QRectF(r.x() - 12, r.y(), r.width() + 12, r.height()), 9, 9)
        p.setPen(QPen(QColor(acc.red(), acc.green(), acc.blue(), 230 if hover else 120), 1))
        p.setBrush(QColor(acc) if hover else QColor(28, 26, 38, 235))
        p.drawPath(path)
        col = QColor("white") if hover else QColor(acc).lighter(130)
        point_right = self.opened if self.side == "right" else not self.opened
        icons.draw_glyph(p, "chevron_r" if point_right else "chevron_l", QRectF(2, r.height() / 2 - 7, 14, 14), col)


class MobilePlayer(QFrame):
    WIDTH = 380

    def __init__(self, main, parent, inspect_file=None):
        super().__init__(parent)
        self.main, self.inspect_file = main, inspect_file
        self.bg = None
        self.tint = QColor(60, 50, 100)
        self.lrc, self.lrc_idx, self.plain = [], -1, ""
        self.setFixedWidth(self.WIDTH)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(40)
        sh.setOffset(-6, 0)
        sh.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(sh)
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(260)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.finished.connect(self._anim_done)
        self.anim.valueChanged.connect(lambda _v: self.place_tab())
        self._closing = False

        white = "color: white;"
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 14, 24, 18)
        v.setSpacing(10)
        top = QHBoxLayout()
        self.btn_close = RoundButton("chevron_r", 36)
        self.btn_close.setToolTip("Cerrar el reproductor grande")
        self.btn_close.clicked.connect(self.close_panel)
        cap = QLabel("REPRODUCIENDO")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setStyleSheet("color: rgba(255,255,255,170); font-size: 11px; font-weight: 700; letter-spacing: 2px;")
        self.btn_fx = RoundButton("fx", 36)
        self.btn_fx.setToolTip("Ajustes de la canción")
        self.btn_fx.clicked.connect(self.main.open_fx)
        top.addWidget(self.btn_close)
        top.addWidget(cap, 1)
        top.addWidget(self.btn_fx)
        v.addLayout(top)

        self.stack = QStackedWidget()
        self.cover = CoverArt()
        self.cover.clicked.connect(self.toggle_lyrics)
        self.lyr = QTextBrowser()
        self.lyr.setOpenLinks(False)
        self.lyr.setFrameShape(QFrame.Shape.NoFrame)
        self.lyr.setStyleSheet("QTextBrowser { background: transparent; color: rgba(255,255,255,190); font-size: 15px; border: none; }")
        self.lyr.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lyr.mousePressEvent = lambda e: self.toggle_lyrics()
        self.queue = QListWidget()
        self.queue.setFrameShape(QFrame.Shape.NoFrame)
        self.queue.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.queue.setStyleSheet(
            "QListWidget { background: transparent; color: rgba(255,255,255,200); font-size: 13px; border: none; outline: none; }"
            "QListWidget::item { padding: 8px 6px; border-radius: 8px; }"
            "QListWidget::item:hover { background: rgba(255,255,255,22); }"
            "QListWidget::item:selected { background: rgba(255,255,255,40); color: white; }"
            "QScrollBar:vertical { background: transparent; width: 6px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,70); border-radius: 3px; min-height: 30px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }")
        self.queue.itemDoubleClicked.connect(self.play_from_queue)
        self.q_head = QLabel("")
        self.q_head.setStyleSheet("color: rgba(255,255,255,150); font-size: 11px; font-weight: 700; letter-spacing: 1px;")
        qbox = QWidget()
        qv = QVBoxLayout(qbox)
        qv.setContentsMargins(0, 0, 0, 0)
        qv.setSpacing(6)
        qv.addWidget(self.q_head)
        qv.addWidget(self.queue, 1)
        self.stack.addWidget(self.cover)
        self.stack.addWidget(self.lyr)
        self.stack.addWidget(qbox)
        v.addWidget(self.stack, 1)

        self.title = QLabel("—")
        self.title.setStyleSheet(white + "font-size: 19px; font-weight: 700;")
        self.sub = QLabel("")
        self.sub.setStyleSheet("color: rgba(255,255,255,165); font-size: 13px;")
        for l in (self.title, self.sub):
            l.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            l.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        v.addSpacing(4)
        v.addWidget(self.title)
        v.addWidget(self.sub)

        self.seek = JumpSlider(Qt.Orientation.Horizontal)
        self.seek.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; background: rgba(255,255,255,60); border-radius: 2px; }"
            "QSlider::sub-page:horizontal { background: white; border-radius: 2px; }"
            "QSlider::handle:horizontal { background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }")
        self.seek.sliderReleased.connect(lambda: self.main.player.setPosition(self.seek.value()))
        self.seek.jumped.connect(lambda v_: self.main.player.setPosition(v_))
        v.addWidget(self.seek)
        tr_ = QHBoxLayout()
        self.t_pos, self.t_left = QLabel("0:00"), QLabel("-0:00")
        for l in (self.t_pos, self.t_left):
            l.setStyleSheet("color: rgba(255,255,255,150); font-size: 11px;")
        tr_.addWidget(self.t_pos)
        tr_.addStretch(1)
        tr_.addWidget(self.t_left)
        v.addLayout(tr_)

        ctr = QHBoxLayout()
        ctr.setSpacing(6)
        self.b_shuffle = RoundButton("shuffle", 42)
        self.b_prev = RoundButton("prev", 52)
        self.b_play = RoundButton("play", 72, big=True)
        self.b_next = RoundButton("next", 52)
        self.b_repeat = RoundButton("loop", 42)
        self.b_shuffle.setToolTip("Aleatorio")
        self.b_repeat.setToolTip("Repetir: no / todas / una")
        self.b_shuffle.clicked.connect(self.toggle_shuffle)
        self.b_repeat.clicked.connect(self.cycle_repeat)
        self.b_prev.clicked.connect(lambda: self.main.step_play(-1))
        self.b_next.clicked.connect(lambda: self.main.step_play(1))
        self.b_play.clicked.connect(self.main.toggle_play)
        ctr.addWidget(self.b_shuffle)
        ctr.addStretch(1)
        ctr.addWidget(self.b_prev)
        ctr.addWidget(self.b_play)
        ctr.addWidget(self.b_next)
        ctr.addStretch(1)
        ctr.addWidget(self.b_repeat)
        v.addLayout(ctr)

        bot = QHBoxLayout()
        self.b_vol = RoundButton("vol2", 34)
        self.b_vol.clicked.connect(self.main.toggle_mute)
        self.vol = JumpSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setSingleStep(2)
        self.vol.setPageStep(5)
        self.vol.jumped.connect(lambda x: self.main.vol.setValue(x))
        self.vol.setStyleSheet(self.seek.styleSheet())
        self.vol.valueChanged.connect(lambda x: self.main.vol.setValue(x))
        self.b_lyr = RoundButton("lyrics", 34)
        self.b_lyr.setToolTip("Letra")
        self.b_lyr.clicked.connect(self.toggle_lyrics)
        self.b_list = RoundButton("menu", 34)
        self.b_list.setToolTip("Lista de reproducción")
        self.b_list.clicked.connect(lambda: self.show_page(0 if self.stack.currentIndex() == 2 else 2))
        bot.addWidget(self.b_vol)
        bot.addWidget(self.vol, 1)
        bot.addSpacing(8)
        bot.addWidget(self.b_lyr)
        bot.addWidget(self.b_list)
        v.addLayout(bot)

        self.tab = EdgeTab(parent)
        self.tab.clicked.connect(lambda: self.close_panel() if self.isVisible() and not self._closing else self.open_panel())
        self.tab.hide()   # solo aparece con el estilo «celular» (Ajustes → Reproductor)
        self.hide()
        p = main.player
        if p is not None:
            p.positionChanged.connect(self.on_pos)
            p.durationChanged.connect(self.on_dur)
            p.playbackStateChanged.connect(self.on_state)
        main.vol.valueChanged.connect(self.sync_vol)
        self.sync_vol(main.vol.value())
        self.sync_modes()

    # ------------------------------------------------------------ abrir / cerrar
    def place(self):
        par = self.parentWidget()
        if par is None:
            return
        self.setFixedHeight(par.height())
        if self.isVisible() and self.anim.state() != QPropertyAnimation.State.Running and not self._closing:
            self.move(par.width() - self.width(), 0)
        self.place_tab()
        if self.isVisible():
            self.raise_()
        self.tab.raise_()

    def place_tab(self):
        par = self.parentWidget()
        if par is None:
            return
        x = (self.x() if self.isVisible() else par.width()) - self.tab.width()
        self.tab.move(x, (par.height() - self.tab.height()) // 2)
        self.tab.raise_()

    def open_panel(self):
        par = self.parentWidget()
        if par is None or not par.isVisible() or par.width() < 200:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(150, self.open_panel)   # la ventana aún se está colocando: espera un momento
            return
        self.track_changed(self.main.playing_path)
        self._closing = False
        self.setFixedHeight(par.height())
        self.move(par.width(), 0)
        self.show()
        self.raise_()
        self.tab.set_open(True)
        self.anim.stop()
        self.anim.setStartValue(QPoint(par.width(), 0))
        self.anim.setEndValue(QPoint(par.width() - self.width(), 0))
        self.anim.start()
        self.place_tab()
        self.main.cfg.setValue("mobile_open", 1)

    def close_panel(self):
        par = self.parentWidget()
        self._closing = True
        self.tab.set_open(False)
        self.anim.stop()
        self.anim.setStartValue(self.pos())
        self.anim.setEndValue(QPoint(par.width(), 0))
        self.anim.start()
        self.main.cfg.setValue("mobile_open", 0)

    def _anim_done(self):
        if self._closing:
            self.hide()
            self._closing = False
        else:   # si la ventana cambió de tamaño mientras se abría, se pega otra vez al borde derecho
            par = self.parentWidget()
            if par is not None:
                self.setFixedHeight(par.height())
                self.move(par.width() - self.width(), 0)
        self.place_tab()

    # ------------------------------------------------------------ fondo
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        r = QRectF(self.rect())
        path.addRoundedRect(QRectF(0, 0, r.width() + 20, r.height()), 20, 20)
        p.setClipPath(path)
        if self.bg is not None:
            p.drawPixmap(self.rect(), self.bg)
        else:
            p.fillRect(self.rect(), self.tint)
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor(0, 0, 0, 90))
        g.setColorAt(0.55, QColor(0, 0, 0, 140))
        g.setColorAt(1, QColor(0, 0, 0, 205))
        p.fillRect(self.rect(), QBrush(g))

    def make_bg(self, data):
        """Portada muy difuminada como fondo (se reduce a pocos píxeles y se agranda suavemente)."""
        img = QImage.fromData(data) if data else QImage()
        if img.isNull():
            self.bg = None
            return
        tiny = img.scaled(12, 18, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        mid = tiny.scaled(48, 72, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.bg = QPixmap.fromImage(mid.scaled(self.WIDTH, 900, Qt.AspectRatioMode.IgnoreAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))

    # ------------------------------------------------------------ datos de la canción
    def track_changed(self, path):
        if not path:
            self.title.setText(T("Nada sonando"))
            self.sub.setText("")
            self.cover.set_pixmap(None)
            self.bg = None
            self.update()
            return
        import os
        m = self.main
        title = m.val(path, "title") or os.path.splitext(os.path.basename(path))[0]
        sub = " · ".join(x for x in (m.val(path, "artist"), m.val(path, "album")) if x)
        fm = self.title.fontMetrics()
        self.title.setText(fm.elidedText(title, Qt.TextElideMode.ElideRight, self.WIDTH - 50))
        self.title.setToolTip(title)
        self.sub.setText(self.sub.fontMetrics().elidedText(sub, Qt.TextElideMode.ElideRight, self.WIDTH - 50))
        data = m.cover_data_of(path)
        pm = QPixmap()
        self.cover.set_pixmap(pm if data and pm.loadFromData(data) else None)
        self.make_bg(data)
        self.load_lyrics(path)
        if self.stack.currentIndex() == 2:
            self.fill_queue()
        if m.player is not None:
            self.on_dur(m.player.duration())
            self.on_pos(m.player.position())
            self.on_state(m.player.playbackState())
        self.update()

    def load_lyrics(self, path):
        pend = self.main.pending.get(path, {})
        text = pend.get("lyrics")
        if text is None:
            try:
                text = (self.inspect_file(path) if self.inspect_file else {}).get("lyrics", "")
            except Exception:
                text = ""
        text = text or ""
        self.lrc, self.lrc_idx = [], -1
        for ln in text.splitlines():
            stamps = LRC_LINE.findall(ln)
            words = LRC_LINE.sub("", ln).strip()
            for mm, ss in stamps:
                try:
                    self.lrc.append((int((int(mm) * 60 + float(ss.replace(":", "."))) * 1000), words))
                except ValueError:
                    pass
        self.lrc.sort()
        self.plain = LRC_LINE.sub("", text).strip()
        self.render_lyrics()

    def render_lyrics(self):
        import html
        if self.lrc:
            rows = []
            for i, (_, w) in enumerate(self.lrc):
                if i == self.lrc_idx:
                    rows.append(f"<p id='cur' style='color:white; font-size:19px; font-weight:700; margin:10px 0'>{html.escape(w) or '♪'}</p>")
                else:
                    rows.append(f"<p style='margin:10px 0'>{html.escape(w) or '♪'}</p>")
            self.lyr.setHtml("<div style='text-align:center'>" + "".join(rows) + "</div>")
            if self.lrc_idx >= 0:
                self.lyr.scrollToAnchor("cur")
                sb = self.lyr.verticalScrollBar()
                sb.setValue(max(0, sb.value() - self.lyr.height() // 3))
        elif self.plain:
            self.lyr.setHtml("<div style='text-align:center; line-height:150%'>"
                             + html.escape(self.plain).replace("\n", "<br>") + "</div>")
        else:
            self.lyr.setHtml("<p style='text-align:center; margin-top:60px'>" + html.escape(T("Esta canción no tiene letra.")) + "</p>")

    def toggle_lyrics(self):
        self.show_page(0 if self.stack.currentIndex() == 1 else 1)

    def show_page(self, i):
        """0 = portada · 1 = letra · 2 = cola de reproducción (todo dentro del reproductor, sin ventanas aparte)."""
        if i == 2:
            self.fill_queue()
        self.stack.setCurrentIndex(i)
        self.b_lyr.set_active(i == 1)
        self.b_list.set_active(i == 2)

    def fill_queue(self):
        import os
        seq, from_pl = self.main.play_seq()
        self._q_from_pl = from_pl
        self.queue.clear()
        cur = self.main.playing_path
        cur_item = None
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
        self.q_head.setText(f"{head}  ·  {len(seq)}")
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
                self.main.play_item(self.main.list.item(r))
        self.fill_queue()

    # ------------------------------------------------------------ reproductor
    def on_pos(self, ms):
        if not self.isVisible():
            return
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        dur = self.main.player.duration() if self.main.player is not None else 0
        self.t_pos.setText(fmt(ms))
        self.t_left.setText("-" + fmt(max(0, dur - ms)))
        if self.lrc:
            idx = -1
            for i, (t, _) in enumerate(self.lrc):
                if t <= ms + 150:
                    idx = i
                else:
                    break
            if idx != self.lrc_idx:
                self.lrc_idx = idx
                if self.stack.currentIndex() == 1:
                    self.render_lyrics()

    def on_dur(self, ms):
        self.seek.setRange(0, max(0, ms))

    def on_state(self, st):
        from PyQt6.QtMultimedia import QMediaPlayer
        self.b_play.set_kind("pause" if st == QMediaPlayer.PlaybackState.PlayingState else "play")

    def sync_vol(self, x):
        self.vol.blockSignals(True)
        self.vol.setValue(x)
        self.vol.blockSignals(False)
        self.b_vol.set_kind("vol0" if x == 0 else ("vol1" if x < 34 else "vol2" if x < 67 else "vol3"))

    def sync_modes(self):
        self.b_shuffle.set_active(bool(self.main.shuffle))
        rep = self.main.repeat
        self.b_repeat.set_kind("loop1" if rep == "one" else "loop")
        self.b_repeat.set_active(rep != "off")

    def toggle_shuffle(self):
        self.main.set_shuffle(not self.main.shuffle)
        self.sync_modes()

    def cycle_repeat(self):
        nxt = {"off": "all", "all": "one", "one": "off"}[self.main.repeat]
        self.main.set_repeat(nxt)
        self.sync_modes()
        self.main.statusBar().showMessage({"off": T("Repetir: desactivado"), "all": T("Repetir: todas"),
                                           "one": T("Repetir: esta canción")}[nxt], 2500)

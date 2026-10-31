"""Vista «Detalles» de la lista de canciones (como Mp3tag o el Explorador): columnas con título, intérprete, álbum,
bitrate, frecuencia, códec… que se pueden ordenar con un clic, cambiar de ancho y ocultar.
Se dibuja sobre la misma lista de siempre, así la selección, el arrastre y todo lo demás siguen funcionando igual."""
import os, re
from PyQt6.QtCore import Qt, QSize, QRect, QObject, QEvent, QTimer
from PyQt6.QtGui import QStandardItemModel, QStandardItem, QColor, QBrush
from PyQt6.QtWidgets import (QHeaderView, QStyledItemDelegate, QStyle, QStyleOptionViewItem, QApplication, QMenu,
                             QAbstractItemView)
from i18n import tr as T

# clave, título, ancho inicial, a la derecha
COLUMNS = [
    ("file", "Nombre de archivo", 230, False), ("title", "Título", 180, False), ("artist", "Intérprete", 150, False),
    ("album", "Álbum", 150, False), ("albumartist", "Intérprete del álbum", 140, False), ("genre", "Género", 100, False),
    ("date", "Año", 55, True), ("tracknumber", "Pista", 50, True), ("discnumber", "Disco", 50, True),
    ("composer", "Compositor", 130, False), ("dur", "Duración", 70, True), ("bitrate", "Tasa de bits", 90, True),
    ("freq", "Frecuencia", 85, True), ("codec", "Códec", 70, False), ("enc", "Codificación", 120, False),
    ("tag", "Etiqueta", 110, False), ("ch", "Canales", 70, False), ("size", "Tamaño", 80, True),
    ("mtime", "Modificado", 125, False),
]
HIDDEN_DEFAULT = {"albumartist", "discnumber", "composer", "enc", "ch", "mtime"}
TAG_KEYS = {"title", "artist", "album", "albumartist", "genre", "date", "tracknumber", "discnumber", "composer"}
TECH_KEYS = {"dur", "bitrate", "freq", "codec", "enc", "tag", "ch", "size"}
SORTS = [("file", "Nombre de archivo"), ("title", "Título"), ("artist", "Intérprete"), ("album", "Álbum"),
         ("genre", "Género"), ("date", "Año"), ("tracknumber", "Pista"), ("dur", "Duración"), ("bitrate", "Tasa de bits"),
         ("size", "Tamaño"), ("mtime", "Fecha de modificación")]
ROW_H = 26
PATH_ROLE = Qt.ItemDataRole.UserRole
KIND_ROLE = Qt.ItemDataRole.UserRole.value + 1


def _num(text):
    m = re.search(r"\d+(?:[.,]\d+)?", text or "")
    return float(m.group(0).replace(",", ".")) if m else -1.0


def sort_value(main, path, key, tech_info):
    """Valor para ordenar (números como números, textos sin distinguir mayúsculas)."""
    if key == "file":
        return (0, os.path.basename(path).lower())
    if key == "mtime":
        try:
            return (0, os.path.getmtime(path))
        except OSError:
            return (1, 0)
    if key in ("tracknumber", "discnumber", "date"):
        v = _num(main.val(path, key))
        return (0 if v >= 0 else 1, v)
    if key in TAG_KEYS:
        v = (main.val(path, key) or "").lower()
        return (0 if v else 1, v)     # los vacíos al final
    t = tech_info(path)
    if key == "dur":
        d = t.get("dur", "")
        if ":" in d:
            mm, ss = d.split(":", 1)
            return (0, int(_num(mm)) * 60 + int(_num(ss)))
        return (1, 0)
    if key in ("bitrate", "freq"):
        v = _num(t.get(key, ""))
        return (0 if v >= 0 else 1, v)
    if key == "size":
        try:
            return (0, os.path.getsize(path))
        except OSError:
            return (1, 0)
    return (0, (t.get(key) or "").lower())


def cell_text(main, path, key, tech_info):
    if key == "file":
        return os.path.basename(path)
    if key in TAG_KEYS:
        return main.val(path, key)
    if key == "mtime":
        try:
            import time
            return time.strftime("%d/%m/%Y %H:%M", time.localtime(os.path.getmtime(path)))
        except OSError:
            return ""
    v = tech_info(path).get(key, "")
    return "" if v in ("—", "-") else T(v)


class DetailsDelegate(QStyledItemDelegate):
    def __init__(self, ctl):
        super().__init__(ctl.list)
        self.ctl = ctl

    def sizeHint(self, option, index):
        return QSize(max(200, self.ctl.header.length()), ROW_H)

    def updateEditorGeometry(self, editor, option, index):
        """Al renombrar en la vista detalles, el cuadro de edición va solo en la columna del nombre."""
        h = self.ctl.header
        x = option.rect.x() + h.sectionPosition(0) + 28
        w = max(120, h.sectionSize(0) - 30)
        editor.setGeometry(QRect(x, option.rect.y() + 1, w, option.rect.height() - 2))

    def paint(self, p, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text_all, icon = opt.text, opt.icon
        opt.text, opt.icon = "", opt.icon.__class__()
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)   # fondo y selección
        path = index.data(PATH_ROLE)
        is_dir = index.data(KIND_ROLE) == "dir"
        sel = bool(opt.state & QStyle.StateFlag.State_Selected)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        col = (opt.palette.color(opt.palette.ColorRole.HighlightedText) if sel else
               (fg.color() if isinstance(fg, QBrush) else opt.palette.color(opt.palette.ColorRole.Text)))
        h = self.ctl.header
        r = option.rect
        p.save()
        p.setPen(col)
        f = opt.font
        p.setFont(f)
        fm = p.fontMetrics()
        for vis in range(h.count()):
            logical = h.logicalIndex(vis)
            if h.isSectionHidden(logical):
                continue
            key, _t, _w, right = COLUMNS[logical]
            x = r.x() + h.sectionPosition(logical)
            w = h.sectionSize(logical)
            cell = QRect(x + 6, r.y(), w - 12, r.height())
            if key == "file":
                if not icon.isNull():
                    icon.paint(p, QRect(x + 4, r.y() + 3, 20, 20))
                cell = QRect(x + 30, r.y(), w - 36, r.height())
                text = text_all if is_dir else os.path.basename(path or "")
            elif is_dir or not path:
                continue
            else:
                text = cell_text(self.ctl.main, path, key, self.ctl.tech_info)
            if not text:
                continue
            al = (Qt.AlignmentFlag.AlignRight if right else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter
            p.drawText(cell, al, fm.elidedText(text, Qt.TextElideMode.ElideRight, max(4, cell.width())))
        p.restore()


class DetailsView(QObject):
    """Controla la cabecera de columnas y el modo detalles de la lista."""
    def __init__(self, main, lst, tech_info):
        super().__init__(lst)
        self.main, self.list, self.tech_info = main, lst, tech_info
        self.enabled = False
        self.normal_delegate = lst.itemDelegate()
        self.model = QStandardItemModel(0, len(COLUMNS), self)
        for i, (_k, title, _w, _r) in enumerate(COLUMNS):
            self.model.setHorizontalHeaderItem(i, QStandardItem(T(title)))
        self.header = QHeaderView(Qt.Orientation.Horizontal, lst)
        self.header.setModel(self.model)
        self.header.setSectionsClickable(True)
        self.header.setSectionsMovable(True)
        self.header.setSortIndicatorShown(True)
        self.header.setHighlightSections(False)
        self.header.setStretchLastSection(False)
        self.header.setMinimumSectionSize(40)
        self.header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.header.customContextMenuRequested.connect(self.header_menu)
        self.header.sectionClicked.connect(self.on_click)
        self.header.sectionResized.connect(lambda *_: self.relayout())
        self.header.sectionMoved.connect(lambda *_: self.relayout())
        self.header.hide()
        self.delegate = DetailsDelegate(self)
        cfg = main.cfg
        hidden = str(cfg.value("det_hidden", ",".join(HIDDEN_DEFAULT)) or "")
        hidden = {x for x in hidden.split(",") if x}
        widths = str(cfg.value("det_widths", "") or "").split(",")
        for i, (k, _t, w, _r) in enumerate(COLUMNS):
            try:
                w = int(widths[i]) if i < len(widths) and widths[i] else w
            except ValueError:
                pass
            self.header.resizeSection(i, w)
            self.header.setSectionHidden(i, k in hidden)
        state = cfg.value("det_state")
        if state is not None:
            try:
                self.header.restoreState(state)
            except Exception:
                pass
        lst.horizontalScrollBar().valueChanged.connect(self.header.setOffset)
        lst.installEventFilter(self)
        lst.viewport().installEventFilter(self)   # el viewport cambia de tamaño DESPUÉS que la lista
        self.update_indicator()

    # ------------------------------------------------------------ activar / desactivar
    def set_enabled(self, on):
        self.enabled = on
        lst = self.list
        if on:
            lst.setItemDelegate(self.delegate)
            lst.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            lst.setUniformItemSizes(True)
            self.header.show()
            lst.setViewportMargins(0, self.header.sizeHint().height(), 0, 0)
        else:
            lst.setItemDelegate(self.normal_delegate)
            self.header.hide()
            lst.setViewportMargins(0, 0, 0, 0)
        self.place()
        self.relayout()

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Type.Resize, QEvent.Type.Show) and (
                obj is self.list or obj is self.list.viewport()):
            self.place()
            if obj is self.list:   # la geometría del viewport aún es la vieja: se vuelve a colocar enseguida
                QTimer.singleShot(0, self.place)
        return False

    def place(self):
        if not self.enabled:
            return
        vp = self.list.viewport().geometry()
        h = self.header.sizeHint().height()
        self.header.setGeometry(vp.x(), vp.y() - h, vp.width(), h)
        self.header.raise_()
        self.header.setOffset(self.list.horizontalScrollBar().value())

    def relayout(self):
        if self.enabled:
            self.list.doItemsLayout()
            self.list.viewport().update()
        self.save()

    def save(self):
        cfg = self.main.cfg
        cfg.setValue("det_hidden", ",".join(k for i, (k, _t, _w, _r) in enumerate(COLUMNS) if self.header.isSectionHidden(i)))
        cfg.setValue("det_widths", ",".join(str(self.header.sectionSize(i)) for i in range(len(COLUMNS))))
        cfg.setValue("det_state", self.header.saveState())

    # ------------------------------------------------------------ ordenar
    def on_click(self, logical):
        key = COLUMNS[logical][0]
        if key not in dict(SORTS) and key not in TAG_KEYS and key not in TECH_KEYS:
            return
        desc = (not self.main.sort_desc) if self.main.sort_key == key else False
        self.main.set_sort(key, desc)

    def update_indicator(self):
        keys = [c[0] for c in COLUMNS]
        k = getattr(self.main, "sort_key", "file")
        if k in keys:
            self.header.setSortIndicator(keys.index(k), Qt.SortOrder.DescendingOrder if self.main.sort_desc
                                         else Qt.SortOrder.AscendingOrder)
        else:
            self.header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

    # ------------------------------------------------------------ columnas visibles
    def header_menu(self, pos):
        m = QMenu(self.header)
        m.addAction(T("Columnas visibles")).setEnabled(False)
        for i, (k, title, _w, _r) in enumerate(COLUMNS):
            a = m.addAction(T(title))
            a.setCheckable(True)
            a.setChecked(not self.header.isSectionHidden(i))
            a.setEnabled(k != "file")
            a.toggled.connect(lambda on, i=i: (self.header.setSectionHidden(i, not on), self.relayout()))
        m.addSeparator()
        m.addAction(T("Restablecer columnas"), self.reset_columns)
        m.exec(self.header.mapToGlobal(pos))

    def reset_columns(self):
        for i, (k, _t, w, _r) in enumerate(COLUMNS):
            vis = self.header.visualIndex(i)
            if vis != i:
                self.header.moveSection(vis, i)
            self.header.resizeSection(i, w)
            self.header.setSectionHidden(i, k in HIDDEN_DEFAULT)
        self.relayout()

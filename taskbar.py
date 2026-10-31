"""Botones en la miniatura de la barra de tareas de Windows (anterior / reproducir-pausa / siguiente), como los
reproductores de música. Usa la interfaz ITaskbarList3 de Windows directamente (sin librerías extra)."""
import os, sys, ctypes
from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer, Qt, QRectF, QStandardPaths
from PyQt6.QtGui import QPixmap, QPainter, QColor

IS_WIN = sys.platform == "win32"
WM_COMMAND, THBN_CLICKED = 0x0111, 0x1800
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8
ID_PREV, ID_PLAY, ID_NEXT = 1, 2, 3

if IS_WIN:
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8)]

    class THUMBBUTTON(ctypes.Structure):
        _fields_ = [("dwMask", wintypes.DWORD), ("iId", wintypes.UINT), ("iBitmap", wintypes.UINT),
                    ("hIcon", wintypes.HICON), ("szTip", ctypes.c_wchar * 260), ("dwFlags", wintypes.DWORD)]


def _guid(text):
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


class TaskbarButtons(QAbstractNativeEventFilter):
    def __init__(self, main, draw_glyph):
        super().__init__()
        self.main, self.draw_glyph = main, draw_glyph
        self.ptr, self.added, self.playing = None, False, False
        self.icons = {}
        self.created_msg = 0
        if not IS_WIN:
            return
        try:
            self.created_msg = ctypes.windll.user32.RegisterWindowMessageW("TaskbarButtonCreated")
        except Exception:
            self.created_msg = 0
        QTimer.singleShot(1500, self.add)   # por si el botón de la barra ya existía

    # ------------------------------------------------------------ COM
    def _com(self):
        if self.ptr is not None:
            return self.ptr
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")), None, 1,
                                    ctypes.byref(_guid("{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}")), ctypes.byref(ptr))
        if hr != 0 or not ptr.value:
            return None
        self.ptr = ptr
        self._call(3, ctypes.HRESULT)   # HrInit
        return ptr

    def _call(self, index, restype, *args, argtypes=()):
        vt = ctypes.cast(self.ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
        return proto(vt[index])(self.ptr, *args)

    def _icon(self, kind):
        if kind in self.icons:
            return self.icons[kind]
        size = ctypes.windll.user32.GetSystemMetrics(49) or 16   # SM_CXSMICON
        pm = QPixmap(64, 64)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self.draw_glyph(p, kind, QRectF(6, 6, 52, 52), QColor("white"))
        p.end()
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation) or \
            os.path.join(os.path.expanduser("~"), ".musicmanager")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"tb_{kind}.ico")
        pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation).save(path, "ICO")
        h = ctypes.windll.user32.LoadImageW(None, path, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
        self.icons[kind] = h
        return h

    def _buttons(self):
        arr = (THUMBBUTTON * 3)()
        for i, (bid, kind, tip) in enumerate(((ID_PREV, "prev", "Anterior"),
                                              (ID_PLAY, "pause" if self.playing else "play",
                                               "Pausa" if self.playing else "Reproducir"),
                                              (ID_NEXT, "next", "Siguiente"))):
            try:
                from i18n import tr
                tip = tr(tip)
            except Exception:
                pass
            arr[i].dwMask = THB_ICON | THB_TOOLTIP | THB_FLAGS
            arr[i].iId = bid
            arr[i].hIcon = self._icon(kind)
            arr[i].szTip = tip
            arr[i].dwFlags = 0
        return arr

    def hwnd(self):
        try:
            return int(self.main.winId())
        except Exception:
            return 0

    def add(self):
        if not IS_WIN or self.added:
            return
        try:
            if self._com() is None:
                return
            arr = self._buttons()
            hr = self._call(15, ctypes.HRESULT, wintypes.HWND(self.hwnd()), wintypes.UINT(3), arr,
                            argtypes=(wintypes.HWND, wintypes.UINT, ctypes.POINTER(THUMBBUTTON)))
            self.added = hr == 0
        except Exception:
            pass

    def set_playing(self, on):
        on = bool(on)
        if not IS_WIN or on == self.playing:
            self.playing = on
            return
        self.playing = on
        if not self.added:
            return
        try:
            arr = self._buttons()
            self._call(16, ctypes.HRESULT, wintypes.HWND(self.hwnd()), wintypes.UINT(3), arr,
                       argtypes=(wintypes.HWND, wintypes.UINT, ctypes.POINTER(THUMBBUTTON)))
        except Exception:
            pass

    # ------------------------------------------------------------ clics en los botones
    def nativeEventFilter(self, etype, message):
        if not IS_WIN:
            return False, 0
        try:
            msg = wintypes.MSG.from_address(int(message))
            if self.created_msg and msg.message == self.created_msg and msg.hWnd == self.hwnd():
                self.added = False
                QTimer.singleShot(0, self.add)
            elif msg.message == WM_COMMAND and ((msg.wParam >> 16) & 0xFFFF) == THBN_CLICKED and msg.hWnd == self.hwnd():
                bid = msg.wParam & 0xFFFF
                m = self.main
                act = {ID_PREV: lambda: m.step_play(-1), ID_PLAY: m.toggle_play, ID_NEXT: lambda: m.step_play(1)}.get(bid)
                if act:
                    QTimer.singleShot(0, act)
                    return True, 0
        except Exception:
            pass
        return False, 0

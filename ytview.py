"""Ventana de YouTube dentro del programa (Qt WebEngine)."""
from urllib.parse import quote_plus
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings

HOME = "https://www.youtube.com/"


class YouTubeDialog(QDialog):
    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"▶ YouTube — {query}")
        self.resize(1100, 720)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        self.view = QWebEngineView()
        s = self.view.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self.view.page().fullScreenRequested.connect(self.on_fullscreen)
        self.addr = QLineEdit()
        self.addr.returnPressed.connect(self.go)
        for text, tip, fn in (("◀", "Atrás", self.view.back), ("▶", "Adelante", self.view.forward),
                              ("🏠", "Inicio de YouTube", lambda: self.view.setUrl(QUrl(HOME))),
                              ("⟳", "Recargar", self.view.reload)):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedWidth(38)
            b.clicked.connect(lambda _=False, f=fn: f())
            bar.addWidget(b)
        bar.addWidget(self.addr, 1)
        ext = QPushButton("🌐 Abrir en el navegador")
        ext.clicked.connect(lambda: QDesktopServices.openUrl(self.view.url()))
        bar.addWidget(ext)
        v.addLayout(bar)
        v.addWidget(self.view, 1)
        self.view.urlChanged.connect(lambda u: self.addr.setText(u.toString()))
        self.view.setUrl(QUrl("https://www.youtube.com/results?search_query=" + quote_plus(query)))

    def go(self):
        t = self.addr.text().strip()
        if not t:
            return
        if "://" not in t and "." not in t.split("/")[0]:
            self.view.setUrl(QUrl("https://www.youtube.com/results?search_query=" + quote_plus(t)))
        else:
            self.view.setUrl(QUrl(t if "://" in t else "https://" + t))

    def on_fullscreen(self, req):
        req.accept()
        if req.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def closeEvent(self, e):
        self.view.setUrl(QUrl("about:blank"))  # corta el sonido
        super().closeEvent(e)

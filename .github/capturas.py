"""Hace capturas de pantalla del programa en GitHub Actions (Windows) para revisar el diseño sin abrirlo.
Crea una pequeña biblioteca de prueba (tonos de 4 s con etiquetas y portadas) y guarda PNG en la carpeta «shots»."""
import os, sys, json, time, tempfile, subprocess, shutil, faulthandler
faulthandler.dump_traceback_later(200, exit=True)   # si algo se cuelga, muestra dónde
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from PyQt6.QtCore import QSettings, QTimer, Qt, QByteArray, QBuffer, QIODevice, QRectF
from PyQt6.QtGui import QImage, QColor, QPainter, QLinearGradient, QFont
from PyQt6.QtWidgets import QApplication

OUT = os.path.abspath("shots")
os.makedirs(OUT, exist_ok=True)
app = QApplication(sys.argv)
app.setApplicationName("Music Manager")
import music_manager as mm, i18n, icons
i18n.install_hooks()
_deco = icons.IconDeco(app)
app.installEventFilter(_deco)


_n = [0]


def close_unexpected():
    """Cualquier ventana modal inesperada (avisos, preguntas) se captura y se cierra para no colgarse."""
    try:
        m = QApplication.activeModalWidget()
        if m is not None and not getattr(m, "_expected", False):
            _n[0] += 1
            m.grab().save(os.path.join(OUT, f"inesperado_{_n[0]}.png"))
            m.close()
            print("modal inesperado:", type(m).__name__, ascii(m.windowTitle()), flush=True)
    except Exception as e:
        print("guardia:", e, flush=True)


_guard = QTimer()
_guard.timeout.connect(close_unexpected)
_guard.start(2500)


def wait(ms):
    t = time.time() + ms / 1000
    while time.time() < t:
        app.processEvents()
        time.sleep(0.01)


def shot(widget, name):
    wait(300)
    widget.grab().save(os.path.join(OUT, name + ".png"))
    print("captura", ascii(name), flush=True)


def cover(c1, c2, text):
    im = QImage(600, 600, QImage.Format.Format_RGB32)
    p = QPainter(im)
    g = QLinearGradient(0, 0, 600, 600)
    g.setColorAt(0, QColor(c1))
    g.setColorAt(1, QColor(c2))
    p.fillRect(im.rect(), g)
    f = QFont("Segoe UI", 54)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(30, 30, 540, 540), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, text)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    im.save(buf, "JPG", 90)
    return bytes(ba)


# ---------------------------------------------------------------- biblioteca de prueba
root = os.path.join(tempfile.gettempdir(), "Musica de prueba")
shutil.rmtree(root, ignore_errors=True)
import imageio_ffmpeg
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
ff = imageio_ffmpeg.get_ffmpeg_exe()
albums = [("Aurora Norte", "Luces de Ciudad", "2021", "Synthpop", "#ff5f6d", "#ffc371",
           ["Neón en la lluvia", "Medianoche", "Avenida Central", "Señales", "Último tren"]),
          ("Los Andes Trío", "Raíces", "2019", "Folk andino", "#11998e", "#38ef7d",
           ["Viento de altura", "Quebrada", "Cholita linda"]),
          ("DJ Kora", "Pulse", "2023", "House", "#7f00ff", "#e100ff", ["Pulse", "Deep Blue", "Sunrise (Extended Mix)"])]
first = None
for artist, album, year, genre, c1, c2, songs in albums:
    d = os.path.join(root, genre, artist)
    os.makedirs(d, exist_ok=True)
    art = cover(c1, c2, album)
    for i, title in enumerate(songs, 1):
        p = os.path.join(d, f"{i:02d}. {artist} - {title}.mp3")
        subprocess.run([ff, "-loglevel", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 60 * i}:duration=4",
                        "-q:a", "5", "-y", p], check=True)
        t = EasyID3()
        t.update({"title": title, "artist": artist, "album": album, "albumartist": artist, "date": year,
                  "genre": genre, "tracknumber": str(i)})
        t.save(p)
        id3 = ID3(p)
        id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=art))
        id3.save(p)
    first = first or d

cfg = QSettings("MusicManager", "MusicManager")
cfg.clear()
for k, v in {"welcomed": 1, "auto_update": 0, "last_dir": first, "open_last": 1, "pinned": json.dumps([root]),
             "theme": "dark", "last_version": mm.APP_VERSION}.items():
    cfg.setValue(k, v)
cfg.sync()

w = mm.Main()
w.resize(1366, 768)
w.show()
wait(3500)
try:
    w.tree.reveal(first)
except Exception:
    pass
w.list.setCurrentRow(1)
wait(1500)
shot(w, "01_principal_oscuro")
w.set_view_mode("details")
wait(800)
shot(w, "02_detalles")
w.set_view_mode("list")
wait(800)
shot(w, "03_lista")
w.set_view_mode("icons")
w.show_right_tab(1)
wait(500)
shot(w, "04_letra")
w.show_right_tab(0)


def grab_modal(name):
    def go():
        m = QApplication.activeModalWidget()
        if m is not None:
            m.grab().save(os.path.join(OUT, name + ".png"))
            print("captura", ascii(name), flush=True)
            m.reject()
    QTimer.singleShot(1500, go)


grab_modal("05_ajustes")
w.open_settings("general")

paths = [w.list.item(r).data(mm.PATH_ROLE) for r in range(w.list.count()) if w.list.item(r).data(mm.KIND_ROLE) != "dir"]
import picard_tools
for name, dlg in (("06_acoustid", picard_tools.AcoustIdDialog(w, paths)),
                  ("07_emparejar_album", picard_tools.AlbumMatchDialog(w, paths, mm.tech_info))):
    i18n.retranslate(dlg)
    dlg.show()
    shot(dlg, name)
    dlg.close()
import navidrome
dlg = navidrome.NavidromeDialog(w, first, mm.AUDIO_EXT, mm.read_tags, mm.inspect_file, mm.find_folder_image)
dlg.show()
shot(dlg, "08_navidrome")
dlg.close()
import folders_by
dlg = folders_by.FoldersByDialog(w, paths, mm.tech_info)
dlg.show()
shot(dlg, "09_crear_carpetas")
dlg.close()

# ---------------- interacciones (sombrear en el árbol, renombrar, recuadro de selección, menú Herramientas)
from PyQt6.QtTest import QTest
from PyQt6.QtCore import QPoint
try:
    t = w.tree
    items = [it for it in t.all_items() if it.data(0, mm.PATH_ROLE) and it.parent() is not None and it.parent().parent() is None]
    print("árbol hijos:", [ascii(i.text(0)) for i in items], flush=True)
    if len(items) >= 3:
        r1, r3 = t.visualItemRect(items[0]), t.visualItemRect(items[2])
        vp = t.viewport()
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r1.center())
        for k in range(1, 9):
            QTest.mouseMove(vp, QPoint(r1.center().x(), r1.center().y() + (r3.center().y() - r1.center().y()) * k // 8))
            wait(40)
        shot(w, "11_sombrear_arbol")
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, r3.center())
        print("árbol seleccionadas:", len(t.selectedItems()), flush=True)
        wait(400)
        w.rename_folder(items[1].data(0, mm.PATH_ROLE), t)
        wait(500)
        shot(w, "12_renombrar_carpeta")
        fw = QApplication.focusWidget()
        if fw is not None:
            QTest.keyClick(fw, Qt.Key.Key_Escape)
        wait(300)
except Exception as e:
    print("árbol error:", ascii(str(e)), flush=True)
try:
    w.load_folder(first)
    wait(800)
    w.list.clearSelection()
    w.list.setCurrentRow(1)
    w.list.item(1).setSelected(True)
    wait(400)
    w.rename_selected()
    wait(500)
    shot(w, "13_renombrar_cancion")
    fw = QApplication.focusWidget()
    if fw is not None:
        QTest.keyClick(fw, Qt.Key.Key_Escape)
    wait(300)
    vp = w.list.viewport()
    a, b = QPoint(vp.width() - 10, vp.height() - 10), QPoint(60, 40)
    QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, a)
    for k in range(1, 9):
        QTest.mouseMove(vp, QPoint(a.x() + (b.x() - a.x()) * k // 8, a.y() + (b.y() - a.y()) * k // 8))
        wait(40)
    shot(w, "14_recuadro_lista")
    QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, b)
    wait(300)
except Exception as e:
    print("lista error:", ascii(str(e)), flush=True)
try:
    for a in w.menuBar().actions():
        if a.menu() is not None and "Herramientas" in a.text().replace("&", ""):
            mnu = a.menu()
            mnu.popup(w.mapToGlobal(QPoint(300, 30)))
            wait(700)
            mnu.grab().save(os.path.join(OUT, "15_menu_herramientas.png"))
            print("captura menu", flush=True)
            mnu.close()
except Exception as e:
    print("menu error:", ascii(str(e)), flush=True)

w.set_theme("light")
wait(1200)
shot(w, "10_principal_claro")
w.set_theme("dark")
cfg.clear()
print("listo")
os._exit(0)

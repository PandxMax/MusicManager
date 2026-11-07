"""Hace capturas de pantalla del programa en GitHub Actions (Windows) para revisar el diseño sin abrirlo.
Crea una pequeña biblioteca de prueba (tonos de 4 s con etiquetas y portadas) y guarda PNG en la carpeta «shots»."""
import os, sys, json, time, tempfile, subprocess, shutil, faulthandler
faulthandler.dump_traceback_later(480, exit=True)   # si algo se cuelga, muestra dónde
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
_polish = mm.DialogPolish()
app.installEventFilter(_polish)


_n = [0]
import traceback
def _exc(t, v, tb):
    print("EXC:", ascii("".join(traceback.format_exception(t, v, tb))), flush=True)
sys.excepthook = _exc


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
            subs = [x.menu() for x in mnu.actions() if x.menu() is not None]
            if subs:
                g = mnu.mapToGlobal(QPoint(mnu.width() - 4, 4))
                subs[1 if len(subs) > 1 else 0].popup(g)
                wait(600)
                subs[1 if len(subs) > 1 else 0].grab().save(os.path.join(OUT, "15b_submenu.png"))
                subs[1 if len(subs) > 1 else 0].close()
            mnu.close()
except Exception as e:
    print("menu error:", ascii(str(e)), flush=True)

try:
    house = os.path.join(root, "House", "DJ Kora")
    hp = [os.path.join(house, f) for f in sorted(os.listdir(house))]
    grab_modal("16_parentesis")
    w.open_strip_parens(hp)
    wait(300)
except Exception as e:
    print("parentesis error:", ascii(str(e)), flush=True)

# ---------------- prueba general: abrir todo lo que se pueda y anotar los fallos
from PyQt6.QtWidgets import QDialog as _QD


def tops():
    return {id(x): x for x in QApplication.topLevelWidgets() if x.isVisible() and x is not w}


def smoke(name, fn, keep=False):
    before = set(tops())
    try:
        fn()
    except Exception:
        print("FALLO", name, ascii(traceback.format_exc()), flush=True)
    wait(900)
    new = [x for k, x in tops().items() if k not in before]
    for i, x in enumerate(new):
        try:
            x.grab().save(os.path.join(OUT, f"s_{name}_{i}.png"))
        except Exception:
            pass
        if not keep:
            try:
                x.close()
            except Exception:
                pass
    print("ok", name, len(new), flush=True)


w.load_folder(first)
wait(800)
w.list.clearSelection()
for r in range(min(3, w.list.count())):
    w.list.item(r).setSelected(True)
w.on_select()
wait(500)
for nm in ("open_report", "open_dupes", "open_organize", "open_tags_from_name", "open_normalize", "open_batch_genres",
           "open_fx", "convert_selected", "open_spectrum", "open_ytdl", "show_about", "show_guide", "open_upscale",
           "open_meta_ai", "open_folders_by", "open_navidrome", "open_acoustid", "open_album_match"):
    f = getattr(w, nm, None)
    if f is None:
        print("NO EXISTE", nm, flush=True)
        continue
    smoke(nm, f)
try:
    w.close_spectrum()
except Exception:
    pass
smoke("whats_new", lambda: w.show_whats_new(True))
smoke("atajos", w.show_shortcuts)
smoke("fold_off", lambda: w.set_meta_open(False))
shot(w, "s_plegado")
smoke("fold_on", lambda: w.set_meta_open(True))
smoke("drawer", lambda: w.set_trees_mode("drawer"))
shot(w, "s_cajon")
smoke("drawer_off", lambda: w.set_trees_mode("normal"))
smoke("tree2_on", lambda: w.act_tree2.setChecked(True))
shot(w, "s_dos_arboles")
smoke("tree2_off", lambda: w.act_tree2.setChecked(False))
smoke("mobile", lambda: w.set_player_style("mobile"))
shot(w, "s_movil")
smoke("classic", lambda: w.set_player_style("classic"))
# guardar una etiqueta y renombrar / mover un archivo
try:
    p0 = w.list.item(0).data(mm.PATH_ROLE)
    w.pending.setdefault(p0, {})["comment"] = "prueba"
    w.save_all()
    wait(800)
    print("guardado comentario:", ascii(mm.read_tags(p0).get("comment")), flush=True)
    w.do_renames([(p0, "00. Prueba renombrada")])
    wait(800)
    newp = os.path.join(os.path.dirname(p0), "00. Prueba renombrada.mp3")
    print("renombrado:", os.path.exists(newp), flush=True)
    dst = os.path.join(root, "House")
    w.move_items([newp], dst)
    wait(1200)
    print("movido:", os.path.exists(os.path.join(dst, "00. Prueba renombrada.mp3")), flush=True)
except Exception:
    print("FALLO archivos", ascii(traceback.format_exc()), flush=True)
# mover muchas canciones a la vez (como arrastrarlas al árbol)
try:
    lote = os.path.join(root, "Lote")
    os.makedirs(lote, exist_ok=True)
    src0 = os.path.join(first, sorted(os.listdir(first))[0])
    for i in range(45):
        shutil.copy2(src0, os.path.join(lote, f"{i:02d}. Cancion de prueba {i}.mp3"))
    dest = os.path.join(root, "Destino")
    os.makedirs(dest, exist_ok=True)
    w.refresh_trees()
    w.load_folder(lote)
    wait(2500)   # que empiecen las miniaturas, como en la vida real
    w.list.selectAll()
    sel = w.selected_all_paths()
    print("seleccionadas:", len(sel), flush=True)
    w.tree.dropped.emit(sel, dest)
    wait(6000)
    print("movidas:", len(os.listdir(dest)), "quedan:", len(os.listdir(lote)), flush=True)
except Exception:
    print("FALLO lote", ascii(traceback.format_exc()), flush=True)
# cortar: quedan medio transparentes
try:
    w.load_folder(first)
    wait(800)
    w.list.clearSelection()
    for r in (0, 1):
        w.list.item(r).setSelected(True)
    w.clip_set("cut")
    w.list.clearSelection()
    wait(500)
    shot(w, "s_cortar")
    w.set_cut_marks([])
    w.clip = None
except Exception:
    print("FALLO cortar", ascii(traceback.format_exc()), flush=True)
# copiar / pegar metadatos
try:
    w.load_folder(first)
    wait(600)
    w.list.clearSelection()
    w.list.item(0).setSelected(True)
    w.on_select()
    w.copy_meta()
    print("clip:", sorted((w.meta_clip or {}).get("tags", {}).items())[:3], "portada:", bool((w.meta_clip or {}).get("cover")), flush=True)
    w.list.clearSelection()
    for r in (1, 2):
        w.list.item(r).setSelected(True)
    w.on_select()
    grab_modal("s_pegar_meta")
    w.paste_meta()
    wait(300)
except Exception:
    print("FALLO metadatos", ascii(traceback.format_exc()), flush=True)
# búsqueda activa y cambio de carpeta
try:
    w.load_folder(first)
    wait(600)
    w.search.setText("medianoche")
    wait(600)
    shot(w, "s_busqueda")
    print("barra busqueda visible:", w.filter_bar.isVisible(), ascii(w.filter_lbl.text()), flush=True)
    w.load_folder(os.path.join(root, "House", "DJ Kora"))
    wait(600)
    print("busqueda tras cambiar carpeta:", ascii(w.search.text()), "barra:", w.filter_bar.isVisible(),
          "visibles:", sum(not w.list.item(r).isHidden() for r in range(w.list.count())), flush=True)
except Exception:
    print("FALLO busqueda", ascii(traceback.format_exc()), flush=True)
# textos sin traducir en inglés
try:
    w.set_language("en")
    wait(1500)
    shot(w, "s_ingles")
    import re as _re
    from PyQt6.QtWidgets import QAbstractButton, QLabel as _QL
    from PyQt6.QtGui import QAction as _QA
    left = set()
    sp = _re.compile(r"[ñáéíóú¿¡]|\b(de|la|las|los|una|canci|carpeta|elige|pulsa|sin|con)\b", _re.I)
    for x in w.findChildren(QAbstractButton) + w.findChildren(_QL):
        for t in (x.text(), x.toolTip()):
            t = _re.sub(r"<[^>]+>", "", t or "")
            if t and sp.search(t) and not x.window().isHidden():
                left.add(t[:90])
    for a in w.findChildren(_QA):
        for t in (a.text(), a.toolTip()):
            if t and sp.search(t):
                left.add(t[:90])
    for t in sorted(left):
        print("SIN TRADUCIR:", ascii(t), flush=True)
    w.set_language("es")
    wait(800)
except Exception:
    print("FALLO idioma", ascii(traceback.format_exc()), flush=True)

w.set_theme("light")
wait(1200)
shot(w, "10_principal_claro")
w.set_theme("dark")
cfg.clear()
print("listo")
os._exit(0)

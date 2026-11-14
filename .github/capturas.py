import time
"""Hace capturas de pantalla del programa en GitHub Actions (Windows) para revisar el diseño sin abrirlo.
Crea una pequeña biblioteca de prueba (tonos de 4 s con etiquetas y portadas) y guarda PNG en la carpeta «shots»."""
import os, sys, json, time, tempfile, subprocess, shutil, faulthandler
faulthandler.dump_traceback_later(480, exit=True)   # si algo se cuelga, muestra dónde
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
from PyQt6.QtCore import QSettings, QTimer, Qt, QByteArray, QBuffer, QIODevice, QRectF
from PyQt6.QtGui import QImage, QColor, QPainter, QLinearGradient, QFont
from PyQt6.QtWidgets import QApplication, QWidget

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
    # deshacer el movimiento (vuelven las 45)
    w.undo_fs()
    wait(1500)
    print("tras deshacer:", "destino:", len(os.listdir(dest)), "lote:", len(os.listdir(lote)), flush=True)
    # guardar muchos cambios a la vez (en segundo plano con barra)
    w.load_folder(lote)
    wait(1500)
    fl = list(w._all_files)[:20]
    for i, pth in enumerate(fl):
        w.pending.setdefault(pth, {})["comment"] = f"prueba {i}"
    t0 = time.perf_counter()
    w.save_all()
    wait(800)
    print("guardado en lote:", round(time.perf_counter() - t0, 1), "s; pendientes:", len(w.pending),
          "comentario:", ascii(mm.read_tags(fl[7]).get("comment")), flush=True)
    # renombrar y deshacer
    w.do_renames([(fl[0], "Renombrada para deshacer")])
    wait(800)
    ren = os.path.exists(os.path.join(lote, "Renombrada para deshacer.mp3"))
    w.undo_fs()
    wait(800)
    print("renombrar/deshacer:", ren, os.path.exists(fl[0]), flush=True)
    # atajos de música: AvPág / RePág
    w.play_file(fl[2])
    wait(800)
    w.list.setFocus()
    QTest.keyClick(w.list, Qt.Key.Key_PageDown)
    wait(800)
    a1 = os.path.basename(w.playing_path)
    QTest.keyClick(w.list, Qt.Key.Key_PageUp)
    wait(800)
    a2 = os.path.basename(w.playing_path)
    w.search.setFocus()
    QTest.keyClick(w.search, Qt.Key.Key_PageDown)
    wait(500)
    print("atajos:", ascii(os.path.basename(fl[2])), "->", ascii(a1), "->", ascii(a2), "escribiendo no cambia:",
          os.path.basename(w.playing_path) == a2, flush=True)
    w.list.setFocus()
    w.cfg.setValue("hk_next", "F8")
    w.music_keys.load()
    QTest.keyClick(w.list, Qt.Key.Key_F8)
    wait(700)
    print("atajo cambiado a F8:", ascii(os.path.basename(w.playing_path)), flush=True)
    w.cfg.remove("hk_next")
    w.music_keys.load()
    # atajos en todo Windows: se simula la tecla a nivel del sistema, con el foco en un cuadro de texto
    import ctypes
    w.play_file(fl[5])
    wait(900)
    w.search.setFocus()
    print("globales registrados:", sorted(w.music_keys.registered), "fallidos:", w.music_keys.failed, flush=True)
    ctypes.windll.user32.keybd_event(0x22, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0x22, 0, 2, 0)
    wait(1200)
    g1 = os.path.basename(w.playing_path)
    ctypes.windll.user32.keybd_event(0x21, 0, 0, 0)
    ctypes.windll.user32.keybd_event(0x21, 0, 2, 0)
    wait(1200)
    print("global AvPag/RePag:", ascii(os.path.basename(fl[5])), "->", ascii(g1), "->", ascii(os.path.basename(w.playing_path)), flush=True)
    # una pulsación con las dos vías activas debe contar UNA vez
    b0 = os.path.basename(w.playing_path)
    ctypes.windll.user32.keybd_event(0x22, 0, 0, 0)
    wait(120)
    ctypes.windll.user32.keybd_event(0x22, 0, 2, 0)
    wait(1200)
    b1 = os.path.basename(w.playing_path)
    # como en un juego que bloquea los atajos: sin registro de Windows, solo la lectura directa del teclado
    for act in list(w.music_keys.registered):
        ctypes.windll.user32.UnregisterHotKey(int(w.winId()), w.music_keys.IDS[act])
    ctypes.windll.user32.keybd_event(0x22, 0, 0, 0)
    wait(150)
    ctypes.windll.user32.keybd_event(0x22, 0, 2, 0)
    wait(1200)
    b2 = os.path.basename(w.playing_path)
    print("una pulsacion = un salto:", ascii(b0), "->", ascii(b1), "| sin registro (como en un juego):", ascii(b2),
          "sondeo activo:", w.music_keys.poll.isActive(), flush=True)
    w.player.stop()
    wait(500)
    print("sin musica, teclas libres:", w.music_keys.registered == {}, flush=True)
    import secret
    secret.put(w.cfg, "key_Prueba", "sk-secreta-123")
    raw = str(w.cfg.value("key_Prueba", ""))
    print("clave cifrada:", raw.startswith("dpapi:"), "sk-secreta" not in raw, "se lee:", secret.get(w.cfg, "key_Prueba") == "sk-secreta-123",
          "vieja sin cifrar se lee:", secret.unprotect("clave-vieja") == "clave-vieja", flush=True)
    w.cfg.remove("key_Prueba")
    print("novedades:", len(mm.CHANGELOG), mm.CHANGELOG[0][0], flush=True)
    smoke("ajustes atajos", lambda: w.open_settings("atajos"), "s_ajustes_atajos")
    smoke("primeros pasos", w.show_welcome, "s_bienvenida")
    smoke("reportar", w.report_problem, "s_reportar")
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
# portada no cuadrada: ventanita para recortar
try:
    rect_dir = os.path.join(root, "Rectangular")
    os.makedirs(rect_dir, exist_ok=True)
    rp = os.path.join(rect_dir, "01. Portada larga.mp3")
    shutil.copy2(src0, rp)
    im = QImage(712, 1000, QImage.Format.Format_RGB32)
    pp = QPainter(im)
    g = QLinearGradient(0, 0, 0, 1000)
    g.setColorAt(0, QColor("#1e3c72"))
    g.setColorAt(1, QColor("#e94057"))
    pp.fillRect(im.rect(), g)
    pp.setPen(QColor("white"))
    f = QFont("Segoe UI", 60)
    f.setBold(True)
    pp.setFont(f)
    pp.drawText(QRectF(0, 0, 712, 1000), Qt.AlignmentFlag.AlignCenter, "SONIC\nX")
    pp.end()
    ba = QByteArray()
    bf = QBuffer(ba)
    bf.open(QIODevice.OpenModeFlag.WriteOnly)
    im.save(bf, "JPG", 90)
    id3 = ID3(rp)
    id3.delall("APIC")
    id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=bytes(ba)))
    id3.save(rp)
    w.load_folder(rect_dir)
    wait(800)
    w.list.clearSelection()
    w.list.item(0).setSelected(True)
    w.on_select()
    import covercrop
    out = covercrop.crop_square(im, 0, 144, 712, 1000)
    print("recorte:", mm.cover_dims(out), flush=True)
    grab_modal("s_recortar")
    w.resize_covers(1000)
    wait(300)
except Exception:
    print("FALLO recortar", ascii(traceback.format_exc()), flush=True)
# FLAC falso (viene de MP3): recomendación en el espectrograma + reparar recortes
try:
    fk = os.path.join(root, "FlacFalso")
    os.makedirs(fk, exist_ok=True)
    tmp3 = os.path.join(fk, "tmp.mp3")
    subprocess.run([ff, "-loglevel", "error", "-f", "lavfi", "-i", "anoisesrc=d=12:c=pink:a=0.9", "-ac", "2",
                    "-c:a", "libmp3lame", "-b:a", "128k", "-y", tmp3], check=True)
    fl = os.path.join(fk, "01. Cancion convertida.flac")
    subprocess.run([ff, "-loglevel", "error", "-i", tmp3, "-c:a", "flac", "-y", fl], check=True)
    os.remove(tmp3)
    w.load_folder(fk)
    wait(800)
    w.list.clearSelection()
    w.list.item(0).setSelected(True)
    w.on_select()
    w.open_spectrum()
    wait(9000)
    shot(w, "s_espectro_falso")
    try:
        sp = w.spec_pane.findChild(QWidget, None)
    except Exception:
        pass
    import repair
    jobs = [(fl, os.path.join(fk, "01. Cancion convertida (reparada).flac"), False)]
    rw = repair.RepairWorker(jobs)
    res = []
    rw.step.connect(lambda i, o, e: res.append((o, e)))
    rw.run()
    print("reparar:", ascii(res), flush=True)
    w.close_spectrum()
    w.list.clearSelection()
    w.list.item(0).setSelected(True)
    w.on_select()
    smoke("open_repair", w.open_repair)
except Exception:
    print("FALLO flac falso", ascii(traceback.format_exc()), flush=True)
# buscar en una carpeta grande con subcarpetas (modo iconos)
try:
    big = os.path.join(root, "Grande")
    for k in range(6):
        d = os.path.join(big, f"Sub {k}")
        os.makedirs(d, exist_ok=True)
        for i in range(600):
            nm = f"{i:03d}. Artista {k} - " + ("Tame Impala tema" if (i * 7 + k) % 23 == 0 else "Otra cancion") + f" {i}.mp3"
            try:
                os.link(src0, os.path.join(d, nm))
            except OSError:
                shutil.copy2(src0, os.path.join(d, nm))
    w.chk_sub.setChecked(True)
    w.set_view_mode("icons")
    w.load_folder(big)
    wait(1500)
    print("grande:", w.list.count(), "canciones", flush=True)
    for q in ("t", "ta", "tam", "tame", "tam", "tame"):
        t0 = time.perf_counter()
        w.apply_filter(q)
        QApplication.processEvents()
        print("filtro", q, w.list.count(), "en", round((time.perf_counter() - t0) * 1000), "ms", flush=True)
    t0 = time.perf_counter()
    w.apply_filter("")
    QApplication.processEvents()
    print("quitar filtro", w.list.count(), "en", round((time.perf_counter() - t0) * 1000), "ms", flush=True)
    w.search.setText("otra")
    wait(1200)
    print("busqueda amplia:", w.list.count(), "scroll max:", w.list.verticalScrollBar().maximum(), flush=True)
    shot(w, "s_busqueda_amplia")
    w.search.setText("tame")
    wait(1200)
    vis = [w.list.item(r) for r in range(w.list.count()) if not w.list.item(r).isHidden()]
    rects = [w.list.visualItemRect(x) for x in vis]
    print("busqueda grande:", len(vis), "visibles; primeras posiciones:", [(r.x(), r.y()) for r in rects[:6]],
          "scroll max:", w.list.verticalScrollBar().maximum(), flush=True)
    shot(w, "s_busqueda_grande")
    tgt = vis[3].data(mm.PATH_ROLE)
    w.go_to_folder(tgt)
    wait(1200)
    print("ir a carpeta:", ascii(os.path.basename(w.current_dir or "")), "busqueda:", ascii(w.search.text()),
          "seleccion ok:", w.selected_paths() == [tgt], flush=True)
    shot(w, "s_ir_carpeta")
    w.search.clear()
    wait(500)
    w.chk_sub.setChecked(False)
except Exception:
    print("FALLO busqueda grande", ascii(traceback.format_exc()), flush=True)
# eliminar varias carpetas grandes (en segundo plano)
try:
    dels = []
    for k in range(3):
        d = os.path.join(root, f"Borrar {k}")
        os.makedirs(d, exist_ok=True)
        for i in range(40):
            shutil.copy2(src0, os.path.join(d, f"{i:02d}.mp3"))
        dels.append(d)
    w.refresh_trees()
    wait(800)
    w.cfg.setValue("confirm_delete", 0)
    t0 = time.time()
    w.delete_paths(dels)
    t1 = time.time()
    for _ in range(300):
        if not any(os.path.exists(d) for d in dels):
            break
        wait(100)
    print("borrar: la llamada tardó %.2f s, todo borrado en %.1f s, quedan: %d" % (t1 - t0, time.time() - t0,
          sum(os.path.exists(d) for d in dels)), flush=True)
except Exception:
    print("FALLO borrar", ascii(traceback.format_exc()), flush=True)
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

# reproductor del editor (panel de la derecha) con el diseño nuevo
try:
    w.chk_sub.setChecked(False)
    w.search.clear()
    w.load_folder(first)
    wait(600)
    print("barra clasica visible:", w.player_bar.isVisible(), "estilo:", w.player_style, flush=True)
    QTest.mouseClick(w.btn_phone, Qt.MouseButton.LeftButton)
    wait(900)
    w.play_file(list(w._all_files)[1])
    wait(1500)
    if w.player is not None:
        w.player.setPosition(1500)
        w.player.pause()
    wait(1200)
    inn = w.mobile.inner
    print("panel:", w.mobile.isVisible(), inn.isVisible(), inn.width(), inn.height(), inn.S, ascii(inn.title.text()),
          ascii(inn.cap2.text()), flush=True)
    shot(w, "s_panel_editor")
    inn.set_cover_mode("card")
    shot(w.mobile, "s_panel_tarjeta")
    inn.set_cover_mode("full")
    shot(w.mobile, "s_panel_extendida")
    inn.set_cover_mode("fit")
    QTest.mouseClick(inn.a_queue, Qt.MouseButton.LeftButton)
    for _ in range(120):
        wait(250)
        if inn.lib.loaded:
            break
    wait(1200)
    shot(w.mobile, "s_panel_cola")
    print("panel cola:", len(inn.lib.files), flush=True)
    QTest.mouseClick(inn.a_queue, Qt.MouseButton.LeftButton)
    inn.toggle_lyrics()
    shot(w.mobile, "s_panel_letra")
    inn.toggle_lyrics()
    w.resize(1366, 620)
    wait(700)
    shot(w.mobile, "s_panel_bajo")
    w.resize(1366, 768)
    wait(500)
    QTest.mouseClick(inn.b_compact, Qt.MouseButton.LeftButton)
    wait(1200)
    print("separado (dos ventanas):", w.mini is not None and w.mini.isVisible(), "editor visible:", w.isVisible(),
          "panel cerrado:", not w.mobile.isVisible(), "detached:", w.mini_detached, flush=True)
    wait(600)
    QTest.mouseClick(w.mini.a_edit, Qt.MouseButton.LeftButton)
    wait(800)
    print("editar desde separado: sigue abierto:", w.mini.isVisible(), "seleccion:", len(w.selected_paths()), flush=True)
    w.set_mini_detached(False)
    wait(500)
    print("esconder editor:", not w.isVisible(), w.mini.isVisible(), flush=True)
    w.set_mini_detached(True)
    wait(500)
    print("mostrar editor otra vez:", w.isVisible(), w.mini.isVisible(), flush=True)
    w.exit_mini()
    wait(500)
    print("unido de nuevo:", w.isVisible(), not w.mini.in_use(), flush=True)
    w.mobile.open_panel()
    wait(900)
    wait(600)
    QTest.mouseClick(inn.b_down, Qt.MouseButton.LeftButton)
    wait(700)
    print("panel cerrado:", not w.mobile.isVisible(), flush=True)
    QTest.mouseClick(w.btn_phone, Qt.MouseButton.LeftButton)
    wait(900)
    o1 = w.mobile.isVisible()
    QTest.mouseClick(w.btn_phone, Qt.MouseButton.LeftButton)
    wait(900)
    print("boton celular abre/cierra:", o1, not w.mobile.isVisible(), flush=True)
    QTest.mouseClick(w.pl_fab, Qt.MouseButton.LeftButton)
    for _ in range(60):
        wait(250)
        if inn.lib.loaded:
            break
    wait(800)
    print("boton redondo abre la biblioteca:", "boton de la barra quitado:", not w.btn_list.isVisible(), w.mobile.isVisible(), inn.lib.isVisible(), len(inn.lib.files), flush=True)
    R = mm.Qt.ItemDataRole.UserRole
    kinds = lambda: [inn.lib.list.item(i).data(R) for i in range(min(6, inn.lib.list.count()))]
    print("boton redondo escondido con el panel abierto:", not w.pl_fab.isVisible(), flush=True)
    # se abre donde está la canción que suena
    cur = w.playing_path
    vis = [inn.lib.list.itemAt(10, y) for y in range(10, inn.lib.list.viewport().height(), 20)]
    print("canción que suena a la vista:", any(it is not None and it.data(R + 1) == cur for it in vis), flush=True)
    # reproducir una carpeta entera
    inn.lib.set_tab("folders")
    rit = next(inn.lib.list.item(i) for i in range(inn.lib.list.count())
               if os.path.normcase(inn.lib.list.item(i).data(R + 1) or "") == os.path.normcase(os.path.normpath(root)))
    inn.lib.on_click(rit)
    wait(400)
    sub = next(inn.lib.list.item(i) for i in range(inn.lib.list.count()) if inn.lib.list.item(i).data(R + 2) == "Folk andino")
    inn.lib.on_click(sub)
    wait(400)
    print("dentro de carpeta:", kinds(), ascii(inn.lib.list.item(0).data(R + 2)), ascii(inn.lib.list.item(0).data(R + 3)), flush=True)
    shot(w.mobile, "s_lib_reproducir_carpeta")
    inn.lib.on_click(inn.lib.list.item(0))
    wait(1000)
    print("reproducir carpeta:", ascii(os.path.basename(w.playing_path)), "lista:", len(w.mini_seq or []), ascii(inn.cap2.text()), flush=True)
    QTest.mouseClick(inn.lib.b_queue, Qt.MouseButton.LeftButton)
    wait(500)
    print("en reproduccion:", ascii(inn.lib.h_title.text()), inn.lib.list.count(), ascii(inn.lib.h_sub.text()), flush=True)
    shot(w.mobile, "s_lib_en_reproduccion")
    QTest.mouseClick(inn.lib.b_queue, Qt.MouseButton.LeftButton)
    wait(300)
    shot(w, "s_barra_lista")
    w.mobile.close_panel()
    wait(900)
    print("panel cerrado, boton redondo de vuelta en la esquina:", w.pl_fab.isVisible(),
          w.pl_fab.x() + w.pl_fab.width() + 16 == w.centralWidget().width(), flush=True)
    w.enter_mini(True)
    wait(800)
    shot(w.mini, "s_mini_x")
    QTest.mouseClick(w.mini.b_x, Qt.MouseButton.LeftButton)
    wait(700)
    print("X del reproductor separado:", not w.mini.in_use(), w.isVisible(), flush=True)
    QTest.mouseClick(w.btn_mini, Qt.MouseButton.LeftButton)
    wait(1000)
    shot(w.mini.compact, "s_compacto_x")
    QTest.mouseClick(w.mini.compact.b_x, Qt.MouseButton.LeftButton)
    wait(700)
    print("X de la ventanita:", not w.mini.in_use(), w.isVisible(), flush=True)
    QTest.mouseClick(w.btn_mini, Qt.MouseButton.LeftButton)
    wait(1000)
    print("boton ventana:", w.mini.compact.isVisible(), "editor visible:", w.isVisible(), "completo:", w.mini.isVisible(), flush=True)
    shot(w, "s_barra_clasica")
    QTest.mouseClick(w.btn_mini, Qt.MouseButton.LeftButton)
    wait(800)
    print("boton ventana otra vez (cierra):", not w.mini.in_use(), w.isVisible(), flush=True)
    # tras usar el modo ventana, separar desde el modo celular debe abrir el reproductor COMPLETO
    QTest.mouseClick(w.btn_phone, Qt.MouseButton.LeftButton)
    wait(900)
    QTest.mouseClick(inn.b_compact, Qt.MouseButton.LeftButton)
    wait(1000)
    print("separar tras modo ventana: completo:", w.mini.isVisible(), "portada:", w.mini.compact.isVisible(), "editor:", w.isVisible(), flush=True)
    w.exit_mini()
    wait(500)
    QTest.mouseClick(w.btn_phone, Qt.MouseButton.LeftButton)
    wait(900)
    QTest.mouseClick(inn.b_solo, Qt.MouseButton.LeftButton)
    wait(1000)
    print("solo reproductor: completo:", w.mini.isVisible(), "portada:", w.mini.compact.isVisible(), "editor:", w.isVisible(), flush=True)
    w.exit_mini()
    wait(500)
    w.set_player_style("classic")
    wait(500)
except Exception:
    print("FALLO panel", ascii(traceback.format_exc()), flush=True)

# modo reproductor (diseño como la app del celular, con el fondo difuminado)
try:
    w.chk_sub.setChecked(False)
    w.search.clear()
    w.load_folder(first)
    wait(800)
    songs = list(w._all_files)
    w.play_file(songs[1])
    wait(1500)
    if w.player is not None:
        w.player.setPosition(1600)
        w.player.pause()
    w.enter_mini()
    wait(2500)
    mp = w.mini
    print("mini:", mp.isVisible(), "editor visible:", w.isVisible(), "tam:", mp.width(), mp.height(),
          "titulo:", ascii(mp.title.text()), "sub:", ascii(mp.sub.text()), "cap:", ascii(mp.cap2.text()),
          "calidad:", ascii((mp.quality.fmt, mp.quality.detail, mp.quality.lvl)), "onda:", len(mp.wave.levels), flush=True)
    for wd in (mp.title, mp.quality, mp.wave, mp.b_play, mp.bar):
        print("  geo", type(wd).__name__, wd.geometry().getRect(), flush=True)
    shot(mp, "s_mini")
    print("modo portada:", mp.cover_mode, flush=True)
    mp.set_cover_mode("card")
    shot(mp, "s_mini_normal")
    mp.set_cover_mode("full")
    shot(mp, "s_mini_extendida")
    mp.set_cover_mode("fit")
    # solo la portada (ventanita pequeña que se puede agrandar)
    QTest.mouseClick(mp.b_compact, Qt.MouseButton.LeftButton)
    wait(700)
    cp = mp.compact
    print("compacto:", cp.isVisible(), "completo:", mp.isVisible(), cp.width(), cp.height(), flush=True)
    try:   # lo que ve Windows (y Wallpaper Engine): título, artista, portada
        import asyncio

        async def ver():
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M
            m = await M.request_async()
            out = []
            for ses in m.get_sessions():
                pr = await ses.try_get_media_properties_async()
                out.append((pr.title, pr.artist, pr.album_title, pr.thumbnail is not None, int(ses.get_playback_info().playback_status)))
            return out
        import threading
        box = []
        th = threading.Thread(target=lambda: box.append(asyncio.run(ver())))
        th.start()
        while th.is_alive():
            wait(100)
        print("Windows ve:", ascii(box), "smtc ok:", w.media.ok, ascii(w.media.error), flush=True)
    except Exception:
        print("FALLO smtc", ascii(traceback.format_exc()), flush=True)
    QTest.mouseClick(cp.b_vol, Qt.MouseButton.LeftButton)
    wait(300)
    print("volumen en ventanita:", mp.volpop.isVisible(), flush=True)
    mp.volpop.hide()
    shot(cp, "s_compacto")
    t0 = time.perf_counter()
    for k in range(40):
        cp.resize(300 + k * 6, 368 + k * 5)
        cp.repaint()
    print("40 cambios de tamano:", round((time.perf_counter() - t0) * 1000 / 40, 1), "ms cada uno", flush=True)
    cp.resize(460, 380)
    wait(400)
    shot(cp, "s_compacto_grande")
    cp.resize(210, 210)
    wait(400)
    shot(cp, "s_compacto_chico")
    QTest.mouseClick(cp.b_next, Qt.MouseButton.LeftButton)
    wait(1000)
    print("compacto siguiente:", ascii(cp.title_txt), ascii(os.path.basename(w.playing_path)), flush=True)
    QTest.mouseClick(cp.wave, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(cp.wave.width() // 2, 8))
    wait(300)
    t0 = time.perf_counter()
    for i in range(200):
        cp.on_pos(1000 + i * 15)
    QApplication.processEvents()
    print("compacto 200 avisos:", round((time.perf_counter() - t0) * 1000), "ms; bordes:",
          int(cp.edges_at(mm.QPointF(cp.width() - 12, cp.height() - 12)).value), flush=True)
    QTest.keyClick(cp, Qt.Key.Key_Escape)
    wait(600)
    print("de vuelta al completo:", mp.isVisible(), cp.isVisible(), flush=True)
    mp.volpop.open_above(mp.b_vol)
    wait(300)
    mp.volpop.sl.setValue(35)
    print("volumen por barrita:", w.vol.value(), flush=True)
    shot(mp.volpop, "s_volumen")
    mp.volpop.hide()
    mp.toggle_lyrics()
    shot(mp, "s_mini_letra")
    mp.toggle_lyrics()
    QTest.mouseClick(mp.b_next, Qt.MouseButton.LeftButton)
    wait(1200)
    print("siguiente:", ascii(mp.title.text()), ascii(mp.cap2.text()), flush=True)
    QTest.mouseClick(mp.wave, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(mp.wave.width() - 20, 10))
    wait(300)
    mp.change_vol(-10)
    mp.cycle_repeat()
    mp.toggle_shuffle()
    mp.toggle_shuffle()
    mp.cycle_repeat()
    mp.cycle_repeat()
    mp.set_top(True)
    wait(300)
    print("encima:", bool(mp.windowFlags() & Qt.WindowType.WindowStaysOnTopHint), mp.isVisible(), flush=True)
    mp.set_top(False)
    mp.track_changed(None)
    shot(mp, "s_mini_vacio")
    mp.track_changed(w.playing_path)
    t0 = time.perf_counter()
    for _ in range(20):
        mp.repaint()
    print("repintado completo:", round((time.perf_counter() - t0) * 1000 / 20, 1), "ms", flush=True)
    t0 = time.perf_counter()
    for i in range(200):
        mp.on_pos(1000 + i * 15)
    QApplication.processEvents()
    print("200 avisos de posicion:", round((time.perf_counter() - t0) * 1000), "ms", flush=True)
    # biblioteca («Cola»): carpeta principal con muchas subcarpetas
    w.exit_mini()
    w.load_folder(root)
    wait(800)
    w.enter_mini()
    wait(500)
    t0 = time.perf_counter()
    QTest.mouseClick(mp.a_queue, Qt.MouseButton.LeftButton)
    for _ in range(240):
        wait(250)
        if mp.lib.loaded:
            break
    wait(1500)
    mp.lib.list.verticalScrollBar().setValue(900)
    mp.lib.open_for(force=True)
    for _ in range(80):
        wait(250)
        if mp.lib.loaded:
            break
    print("scroll tras revisar:", mp.lib.list.verticalScrollBar().value(), "portadas en memoria:", len(mp.lib.pix), flush=True)
    mp.lib.list.verticalScrollBar().setValue(0)
    wait(600)
    print("biblioteca:", len(mp.lib.files), "canciones en", round(time.perf_counter() - t0, 1), "s; sub:",
          ascii(mp.lib.h_sub.text()), "portadas:", len([1 for v in mp.lib.pix.values() if v is not None]), flush=True)
    shot(mp, "s_lib_canciones")
    mp.lib.set_tab("folders")
    wait(1500)
    print("raices:", [ascii(mp.lib.list.item(i).data(mm.Qt.ItemDataRole.UserRole + 2)) for i in range(mp.lib.list.count())],
          flush=True)
    shot(mp, "s_lib_carpetas")
    rit = next(mp.lib.list.item(i) for i in range(mp.lib.list.count())
               if os.path.normcase(mp.lib.list.item(i).data(mm.Qt.ItemDataRole.UserRole + 1) or "") == os.path.normcase(os.path.normpath(root)))
    mp.lib.on_click(rit)
    wait(1200)
    print("dentro:", ascii(mp.lib.h_title.text()), ascii(mp.lib.h_sub.text()),
          [ascii(mp.lib.list.item(i).data(mm.Qt.ItemDataRole.UserRole + 2)) for i in range(min(9, mp.lib.list.count()))], flush=True)
    shot(mp, "s_lib_carpeta_dentro")
    # se agrega una carpeta nueva con una canción: al volver a abrir la Cola tiene que aparecer
    nd = os.path.join(root, "Nueva Carpeta Test")
    os.makedirs(nd, exist_ok=True)
    shutil.copy2(songs[0], os.path.join(nd, "Cancion nueva.mp3"))
    QTest.mouseClick(mp.a_queue, Qt.MouseButton.LeftButton)
    wait(300)
    QTest.mouseClick(mp.a_queue, Qt.MouseButton.LeftButton)
    for _ in range(80):
        wait(250)
        if mp.lib.loaded:
            break
    print("tras agregar:", "Nueva Carpeta Test" in [os.path.basename(c) for c in mp.lib.children.get(os.path.normpath(root), mp.lib.children.get(root, []))],
          len(mp.lib.files), ascii(mp.lib.h_sub.text()), flush=True)
    shutil.rmtree(nd, ignore_errors=True)
    mp.lib.set_tab("folders")
    mp.lib.set_tab("artists")
    wait(1200)
    shot(mp, "s_lib_artistas")
    arts = [mp.lib.list.item(i) for i in range(mp.lib.list.count())]
    tgt = next((it for it in arts if it.data(mm.Qt.ItemDataRole.UserRole + 1) == "Los Andes Trío"), arts[0])
    mp.lib.on_click(tgt)
    mp.lib.on_click(mp.lib.list.item(1))
    wait(1000)
    print("suena:", ascii(os.path.basename(w.playing_path or "")), "seq:", len(w.mini_seq or []),
          "cap:", ascii(mp.cap2.text()), flush=True)
    shot(mp, "s_lib_artista")
    QTest.mouseClick(mp.a_queue, Qt.MouseButton.LeftButton)
    wait(600)
    shot(mp, "s_mini_tras_lib")
    print("biblioteca cerrada:", not mp.lib.isVisible(), flush=True)
    QTest.keyClick(mp, Qt.Key.Key_Escape)
    wait(800)
    print("Esc muestra el editor:", w.isVisible(), "reproductor sigue:", mp.isVisible(), ascii(mp.b_down.text_), flush=True)
    QTest.mouseClick(mp.b_down, Qt.MouseButton.LeftButton)
    wait(600)
    print("boton Ocultar editor:", not w.isVisible(), mp.isVisible(), ascii(mp.b_down.text_), flush=True)
    shot(mp, "s_mini_boton")
    w.exit_mini()
    wait(800)
    print("volver:", "editor visible:", w.isVisible(), "mini:", mp.isVisible(), flush=True)
    w.set_theme("light")
    wait(600)
    w.enter_mini()
    wait(800)
    shot(mp, "s_mini_tema_claro")
    w.exit_mini()
    w.set_theme("dark")
    wait(600)
    if w.player is not None:
        w.player.stop()
except Exception:
    print("FALLO mini", ascii(traceback.format_exc()), flush=True)

w.set_theme("light")
wait(1200)
shot(w, "10_principal_claro")
w.set_theme("dark")
cfg.clear()
print("listo")
os._exit(0)

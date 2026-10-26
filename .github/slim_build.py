"""Quita del EXE generado los archivos que Music Manager no usa, para que pese menos.
Solo borra un archivo si ningún otro .dll/.pyd/.exe del programa depende de él."""
import os, sys, shutil

ROOT = sys.argv[1] if len(sys.argv) > 1 else "dist/MusicManager"
INT = os.path.join(ROOT, "_internal")
QT = os.path.join(INT, "PyQt6", "Qt6")

FILES = [
    # OpenGL por software (solo para gráficos 3D/QtQuick; el programa no lo usa)
    os.path.join(QT, "bin", "opengl32sw.dll"),
    # visor de PDF de Qt (solo lo usa el plugin de imágenes PDF)
    os.path.join(QT, "bin", "Qt6Pdf.dll"),
    os.path.join(QT, "plugins", "imageformats", "qpdf.dll"),
    # formatos de imagen que no se usan para portadas
    os.path.join(QT, "plugins", "imageformats", "qtiff.dll"),
    os.path.join(QT, "plugins", "imageformats", "qicns.dll"),
    os.path.join(QT, "plugins", "imageformats", "qtga.dll"),
    os.path.join(QT, "plugins", "imageformats", "qwbmp.dll"),
    # OpenSSL propio de Qt (las descargas del programa usan el de Python)
    os.path.join(QT, "plugins", "tls", "qopensslbackend.dll"),
    os.path.join(INT, "libcrypto-3-x64.dll"),
    os.path.join(INT, "libssl-3-x64.dll"),
    # plataformas sin ventana y pantallas táctiles especiales
    os.path.join(QT, "plugins", "platforms", "qminimal.dll"),
    os.path.join(QT, "plugins", "platforms", "qoffscreen.dll"),
    os.path.join(QT, "plugins", "generic", "qtuiotouchplugin.dll"),
]
DIRS = [os.path.join(QT, "translations")]   # traducciones de Qt (el programa trae las suyas)


def size(p):
    if os.path.isdir(p):
        return sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs)
    return os.path.getsize(p) if os.path.exists(p) else 0


def imports_of_all(skip):
    """Nombres (en minúsculas) de las DLL que importan los binarios que se quedan."""
    try:
        import pefile
    except ImportError:
        return None
    need = set()
    for d, _, fs in os.walk(ROOT):
        for f in fs:
            p = os.path.join(d, f)
            if not f.lower().endswith((".dll", ".pyd", ".exe")) or os.path.normcase(p) in skip:
                continue
            try:
                pe = pefile.PE(p, fast_load=True)
                pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                       pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
                for attr in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
                    for e in getattr(pe, attr, []):
                        need.add(e.dll.decode(errors="ignore").lower())
                pe.close()
            except Exception:
                pass
    return need


before = size(ROOT)
cands = {os.path.normcase(p) for p in FILES if os.path.exists(p)}
need = imports_of_all(cands)
for p in FILES:
    if not os.path.exists(p):
        continue
    name = os.path.basename(p).lower()
    if need is None and name.endswith(".dll") and "plugins" not in p:
        print("conservo (no puedo comprobar dependencias):", p)
        continue
    if need is not None and name in need:
        print("conservo (otro archivo lo usa):", p)
        continue
    os.remove(p)
    print("quitado:", p)
for d in DIRS:
    if os.path.isdir(d):
        shutil.rmtree(d)
        print("quitado:", d)
after = size(ROOT)
print(f"Tamaño: {before / 1e6:.1f} MB -> {after / 1e6:.1f} MB (ahorro {(before - after) / 1e6:.1f} MB)")

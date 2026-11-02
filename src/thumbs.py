"""Miniaturas de portadas en segundo plano con caché en disco.

- Se generan en un hilo aparte, así la ventana nunca se traba mientras cargan.
- Se guardan en una carpeta de caché para que volver a una carpeta sea instantáneo.
- La clave incluye fecha y tamaño del archivo: si la canción cambia, se genera de nuevo.
- Cada hora se borran las miniaturas que no se han usado en la última hora (para no ocupar espacio)."""
import os, json, time, hashlib, threading, shutil
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QStandardPaths
from PyQt6.QtGui import QImage

MAX_AGE = 3600          # segundos sin usarse antes de borrarse
VERSION = "1"           # cambia si cambia el formato de la caché


def cache_dir():
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation) or \
        os.path.join(os.path.expanduser("~"), ".musicmanager_cache")
    d = os.path.join(base, "miniaturas")
    os.makedirs(d, exist_ok=True)
    return d


def key_of(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    raw = f"{VERSION}|{os.path.normcase(os.path.abspath(path))}|{st.st_mtime_ns}|{st.st_size}"
    return hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()


def cleanup(max_age=MAX_AGE):
    """Borra las miniaturas que no se usaron en la última hora. Devuelve cuántas borró."""
    d = cache_dir()
    now, n = time.time(), 0
    try:
        names = os.listdir(d)
    except OSError:
        return 0
    for name in names:
        p = os.path.join(d, name)
        try:
            if now - os.path.getmtime(p) > max_age:
                os.remove(p)
                n += 1
        except OSError:
            pass
    return n


def clear_all():
    shutil.rmtree(cache_dir(), ignore_errors=True)


class ThumbWorker(QThread):
    """Recibe listas de canciones y devuelve (gen, ruta, imagen o None, tiene_letra, etiquetas)."""
    ready = pyqtSignal(int, str, object, bool, object)

    def __init__(self, side, inspect_file, read_tags, find_folder_image, tech_fn=None):
        super().__init__()
        self.tech_fn = tech_fn   # datos técnicos (formato, bitrate…) también en segundo plano
        self.side = side
        self.inspect_file, self.read_tags, self.find_folder_image = inspect_file, read_tags, find_folder_image
        self.lock = threading.Condition()
        self.jobs, self.gen, self.stop_flag = [], 0, False
        self.dir = cache_dir()

    def request(self, gen, paths):
        """Sustituye el trabajo pendiente por estas canciones (las de la carpeta abierta)."""
        with self.lock:
            self.gen, self.jobs = gen, list(paths)
            self.lock.notify()

    def stop(self):
        with self.lock:
            self.stop_flag = True
            self.jobs = []
            self.lock.notify()
        self.wait(3000)

    # ---------------------------------------------------------------- caché
    def load_cached(self, k):
        js = os.path.join(self.dir, k + ".json")
        if not os.path.exists(js):
            return None
        try:
            with open(js, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            img = None
            if meta.get("thumb"):
                png = os.path.join(self.dir, k + ".png")
                img = QImage(png)
                if img.isNull():
                    return None
                os.utime(png, None)   # marca de «usada ahora» para la limpieza de cada hora
            os.utime(js, None)
            tags = dict(meta.get("tags") or {})
            if isinstance(meta.get("tech"), list) and len(meta["tech"]) == 2:
                tags["_tech"] = meta["tech"]
            return img, bool(meta.get("lyrics")), tags
        except (OSError, ValueError):
            return None

    def save_cached(self, k, img, lyrics, tags):
        try:
            if img is not None:
                img.save(os.path.join(self.dir, k + ".png"), "PNG")
            tags = dict(tags or {})
            tech = tags.pop("_tech", None)
            with open(os.path.join(self.dir, k + ".json"), "w", encoding="utf-8") as fh:
                json.dump({"thumb": img is not None, "lyrics": lyrics, "tags": tags, "tech": tech}, fh, ensure_ascii=False)
        except OSError:
            pass

    # ---------------------------------------------------------------- trabajo
    def build(self, path):
        d = self.inspect_file(path)
        tags = self.read_tags(path)
        data = d.get("cover")
        if not data:
            fi = self.find_folder_image(os.path.dirname(path))
            if fi:
                try:
                    with open(fi, "rb") as fh:
                        data = fh.read()
                except OSError:
                    data = None
        img = None
        if data:
            im = QImage.fromData(data)
            if not im.isNull():
                img = im.scaled(self.side, self.side, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        return img, bool((d.get("lyrics") or "").strip()), tags

    def run(self):
        self.setPriority(QThread.Priority.LowPriority)
        while True:
            with self.lock:
                while not self.jobs and not self.stop_flag:
                    self.lock.wait()
                if self.stop_flag:
                    return
                gen, path = self.gen, self.jobs.pop(0)
            try:
                k = key_of(path)
                got = self.load_cached(k) if k else None
                fresh = got is None
                if fresh:
                    got = self.build(path)
                img, lyrics, tags = got
                tags = dict(tags or {})
                if self.tech_fn is not None and "_tech" not in tags:
                    try:
                        tags["_tech"] = self.tech_fn(path)
                        fresh = True
                    except Exception:
                        pass
                if fresh and k:
                    self.save_cached(k, img, lyrics, tags)
                self.ready.emit(gen, path, img, lyrics, tags)
            except Exception:
                self.ready.emit(gen, path, None, False, None)

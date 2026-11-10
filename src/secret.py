"""Guarda las claves (IA, Discogs, AcoustID) cifradas con la protección de datos de Windows (DPAPI): solo tu
usuario de Windows en esta PC puede leerlas. En otros sistemas, o si algo falla, se guardan como antes."""
import sys
import base64

PREFIX = "dpapi:"


def _crypt(data, protect):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    src = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(text):
    text = text or ""
    if not text or sys.platform != "win32":
        return text
    try:
        return PREFIX + base64.b64encode(_crypt(text.encode("utf-8"), True)).decode("ascii")
    except Exception:
        return text


def unprotect(value):
    value = str(value or "")
    if not value.startswith(PREFIX):
        return value   # guardada por una versión anterior (sin cifrar): se lee igual
    try:
        return _crypt(base64.b64decode(value[len(PREFIX):]), False).decode("utf-8")
    except Exception:
        return ""


def get(cfg, key):
    return unprotect(cfg.value(key, "")).strip()


def put(cfg, key, text):
    cfg.setValue(key, protect((text or "").strip()))

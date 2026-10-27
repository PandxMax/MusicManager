"""Tonalidad (key) de una canción: se lee de la etiqueta si existe; si no, se estima analizando el audio
(cromagrama + perfiles de Krumhansl). Es una estimación: puede confundir tonalidades relativas (Do mayor / La menor)."""
import numpy as np

NAMES_ES = ["Do", "Do♯", "Re", "Mi♭", "Mi", "Fa", "Fa♯", "Sol", "La♭", "La", "Si♭", "Si"]
NAMES_EN = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
# rueda Camelot (la usan los DJ para mezclar tonalidades compatibles)
CAMELOT_MAJ = {0: "8B", 7: "9B", 2: "10B", 9: "11B", 4: "12B", 11: "1B", 6: "2B", 1: "3B", 8: "4B", 3: "5B", 10: "6B", 5: "7B"}
CAMELOT_MIN = {9: "8A", 4: "9A", 11: "10A", 6: "11A", 1: "12A", 8: "1A", 3: "2A", 10: "3A", 5: "4A", 0: "5A", 7: "6A", 2: "7A"}
_ALIASES = {"DB": 1, "C#": 1, "D#": 3, "EB": 3, "GB": 6, "F#": 6, "G#": 8, "AB": 8, "A#": 10, "BB": 10,
            "C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def describe(pc, minor):
    """(texto corto, texto largo) p. ej. ('Am · 8A', 'La menor')."""
    short = NAMES_EN[pc] + ("m" if minor else "")
    cam = (CAMELOT_MIN if minor else CAMELOT_MAJ)[pc]
    return f"{short} · {cam}", f"{NAMES_ES[pc]} {'menor' if minor else 'mayor'}"


def parse_tag(text):
    """Interpreta lo que traen las etiquetas: «Am», «F#m», «C major», «8A»… Devuelve (pc, menor) o None."""
    t = (text or "").strip().replace("♯", "#").replace("♭", "b")
    if not t:
        return None
    import re
    m = re.fullmatch(r"(\d{1,2})\s*([AaBb])", t)
    if m:   # notación Camelot
        num, letter = int(m.group(1)), m.group(2).upper()
        table = CAMELOT_MIN if letter == "A" else CAMELOT_MAJ
        for pc, cam in table.items():
            if cam == f"{num}{letter}":
                return pc, letter == "A"
        return None
    m = re.fullmatch(r"([A-Ga-g])([#b]?)\s*(m|min|minor|moll|maj|major|dur)?\.?", t)
    if not m:
        return None
    acc = m.group(2)
    root = m.group(1).upper() + ("#" if acc == "#" else "B" if acc == "b" else "")
    pc = _ALIASES.get(root)
    if pc is None:
        return None
    q = (m.group(3) or "").lower()
    return pc, q in ("m", "min", "minor", "moll")


def read_tag(path):
    """Tonalidad guardada en la etiqueta (TKEY, INITIALKEY…), o cadena vacía."""
    try:
        import mutagen
        f = mutagen.File(path)
        t = getattr(f, "tags", None)
        if not t:
            return ""
        for k in ("TKEY", "initialkey", "INITIALKEY", "key", "KEY", "----:com.apple.iTunes:initialkey",
                  "----:com.apple.iTunes:KEY"):
            try:
                v = t.get(k)
            except Exception:
                v = None
            if v:
                v = v.text[0] if hasattr(v, "text") else v[0]
                if isinstance(v, bytes):
                    v = v.decode("utf-8", "ignore")
                return str(v).strip()
    except Exception:
        pass
    return ""


def detect(samples, sr):
    """Estima la tonalidad de un audio mono. Devuelve (pc, menor, confianza 0–1)."""
    x = np.asarray(samples, dtype=np.float32)
    span = int(120 * sr)
    if len(x) > span:   # el centro de la canción: evita intros y finales
        s = (len(x) - span) // 2
        x = x[s:s + span]
    n = 8192
    hop = 4096
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    win = np.hanning(n).astype(np.float32)
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    band = (freqs >= 55) & (freqs <= 2000)
    midi = 69 + 12 * np.log2(freqs[band] / 440.0)
    pcs = np.mod(np.round(midi).astype(int), 12)
    onehot = np.zeros((band.sum(), 12), dtype=np.float32)
    onehot[np.arange(len(pcs)), pcs] = 1.0
    low = freqs[band] <= 260          # zona de los bajos: suele marcar la nota principal (tónica)
    chroma, bass = np.zeros(12), np.zeros(12)
    for start in range(0, len(x) - n + 1, hop):
        mag = np.sqrt(np.abs(np.fft.rfft(x[start:start + n] * win))[band])
        c = mag @ onehot
        tot = c.sum()
        if tot > 1e-6:
            chroma += c / tot
            b = (mag * low) @ onehot
            if b.sum() > 1e-6:
                bass += b / b.sum()
    if chroma.sum() <= 0:
        return 0, False, 0.0
    best = (-2, 0, False)
    scores = []
    for pc in range(12):
        for minor, prof in ((False, MAJOR), (True, MINOR)):
            r = np.corrcoef(chroma, np.roll(prof, pc))[0, 1]
            if bass.max() > 0:
                r += 0.35 * bass[pc] / bass.max()
            scores.append(r)
            if r > best[0]:
                best = (r, pc, minor)
    scores.sort(reverse=True)
    conf = float(max(0.0, min(1.0, (scores[0] - scores[1]) * 8 + 0.3)))
    return best[1], best[2], conf


def detect_file(path):
    from spectro import decode_mono
    sr = 11025
    x = decode_mono(path, sr)
    return detect(x, sr)

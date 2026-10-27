"""Traducción sencilla de la interfaz: español (base), inglés y ruso."""
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractButton, QLabel, QGroupBox, QLineEdit, QMenu, QTabWidget, QWidget, QComboBox,
                             QMessageBox, QDialogButtonBox)
import re

LANGS = [("es", "Español"), ("en", "English"), ("ru", "Русский")]
CUR = "es"

_ROWS = [
    # menús
    ("&Archivo", "&File", "&Файл"), ("&Edición", "&Edit", "&Правка"), ("&Ver", "&View", "&Вид"),
    ("&Reproducción", "&Playback", "&Воспроизведение"), ("&Herramientas", "&Tools", "&Инструменты"),
    ("&Ajustes", "&Settings", "&Настройки"), ("A&yuda", "&Help", "&Справка"),
    ("📌 Agregar carpeta al árbol…", "📌 Add folder to tree…", "📌 Добавить папку в дерево…"),
    ("➕ Nueva carpeta", "➕ New folder", "➕ Новая папка"),
    ("➕ Nueva carpeta aquí", "➕ New folder here", "➕ Новая папка здесь"),
    ("✂️ Cortar\tCtrl+X", "✂️ Cut\tCtrl+X", "✂️ Вырезать\tCtrl+X"),
    ("📋 Copiar\tCtrl+C", "📋 Copy\tCtrl+C", "📋 Копировать\tCtrl+C"),
    ("📥 Pegar\tCtrl+V", "📥 Paste\tCtrl+V", "📥 Вставить\tCtrl+V"),
    ("✏️ Renombrar\tF2", "✏️ Rename\tF2", "✏️ Переименовать\tF2"),
    ("🗑 Eliminar\tSupr", "🗑 Delete\tDel", "🗑 Удалить\tDel"),
    ("💾 Guardar cambios en los archivos\tCtrl+S", "💾 Save changes to files\tCtrl+S", "💾 Сохранить изменения в файлах\tCtrl+S"),
    ("Salir", "Exit", "Выход"),
    ("🔍 Buscar canción…\tCtrl+F", "🔍 Search song…\tCtrl+F", "🔍 Поиск песни…\tCtrl+F"),
    ("📂 Incluir subcarpetas", "📂 Include subfolders", "📂 Включая подпапки"),
    ("☰ Lista", "☰ List", "☰ Список"), ("🗂 2.º árbol", "🗂 2nd tree", "🗂 2-е дерево"),
    ("⇄ Árboles lado a lado", "⇄ Trees side by side", "⇄ Деревья рядом"),
    ("📝 Letra", "📝 Lyrics", "📝 Текст песни"),
    ("↩ Deshacer cambios", "↩ Undo changes", "↩ Отменить изменения"),
    ("☰ Lista de reproducción", "☰ Playlist", "☰ Плейлист"),
    ("▶ Reproducir carpeta", "▶ Play folder", "▶ Воспроизвести папку"),
    ("➕ Añadir a la lista de reproducción", "➕ Add to playlist", "➕ Добавить в плейлист"),
    ("➕ Añadir carpeta a la lista", "➕ Add folder to playlist", "➕ Добавить папку в плейлист"),
    ("⬅ Volver a metadatos y letra", "⬅ Back to tags and lyrics", "⬅ Назад к тегам и тексту"),
    ("✨ Buscar portada automáticamente", "✨ Find cover automatically", "✨ Найти обложку автоматически"),
    ("✨ Portadas automáticas (alta calidad)", "✨ Automatic covers (high quality)", "✨ Автоматические обложки (высокое качество)"),
    ("🔄 Recargar carpetas", "🔄 Reload folders", "🔄 Обновить папки"),
    ("▶ Reproducir / pausa\tEspacio", "▶ Play / pause\tSpace", "▶ Играть / пауза\tПробел"),
    ("⏮ Anterior", "⏮ Previous", "⏮ Предыдущая"), ("⏭ Siguiente", "⏭ Next", "⏭ Следующая"),
    ("⏹ Detener", "⏹ Stop", "⏹ Стоп"),
    ("📊 Espectrograma y calidad…", "📊 Spectrogram & quality…", "📊 Спектрограмма и качество…"),
    ("🔄 Convertir formato…", "🔄 Convert format…", "🔄 Конвертировать формат…"),
    ("▶️ Buscar en YouTube (navegador)", "▶️ Search on YouTube (browser)", "▶️ Искать на YouTube (браузер)"),
    ("➡ Mover al otro árbol", "➡ Move to other tree", "➡ Переместить в другое дерево"),
    ("🔄 Convertir formato", "🔄 Convert format", "🔄 Конвертировать формат"),
    ("Formato de salida", "Output format", "Выходной формат"), ("Calidad", "Quality", "Качество"),
    ("Guardar junto a los originales", "Save next to the originals", "Сохранить рядом с оригиналами"),
    ("Guardar en otra carpeta…", "Save in another folder…", "Сохранить в другую папку…"),
    ("▶ Convertir", "▶ Convert", "▶ Конвертировать"),
    ("🎚 Ajustes de la canción…", "🎚 Song settings…", "🎚 Настройки песни…"),
    ("🤖 Ajustes de IA…", "🤖 AI settings…", "🤖 Настройки ИИ…"),
    ("🎨 Apariencia (tema y color)…", "🎨 Appearance (theme & color)…", "🎨 Оформление (тема и цвет)…"),
    ("🌍 Idioma…", "🌍 Language…", "🌍 Язык…"),
    ("❓ Guía rápida", "❓ Quick guide", "❓ Краткое руководство"),
    ("ℹ️ Acerca de Music Manager", "ℹ️ About Music Manager", "ℹ️ О программе Music Manager"),
    # menú contextual
    ("📂 Abrir carpeta", "📂 Open folder", "📂 Открыть папку"), ("▶ Reproducir", "▶ Play", "▶ Играть"),
    ("▶️ Buscar en YouTube (abre el navegador)", "▶️ Search on YouTube (browser)", "▶️ Искать на YouTube (браузер)"),
    ("📊 Espectrograma / calidad (varias = comparar)", "📊 Spectrogram / quality (several = compare)", "📊 Спектрограмма / качество (несколько = сравнить)"),
    ("✏️ Renombrar archivo (F2)", "✏️ Rename file (F2)", "✏️ Переименовать файл (F2)"),
    ("✂️ Cortar (Ctrl+X)", "✂️ Cut (Ctrl+X)", "✂️ Вырезать (Ctrl+X)"), ("📋 Copiar (Ctrl+C)", "📋 Copy (Ctrl+C)", "📋 Копировать (Ctrl+C)"),
    ("📥 Pegar aquí (Ctrl+V)", "📥 Paste here (Ctrl+V)", "📥 Вставить сюда (Ctrl+V)"),
    ("🗑 Eliminar (Supr)", "🗑 Delete (Del)", "🗑 Удалить (Del)"),
    ("📂 Mostrar carpeta en el Explorador", "📂 Show folder in Explorer", "📂 Показать папку в проводнике"),
    ("🖼 Cambiar portada…", "🖼 Change cover…", "🖼 Сменить обложку…"), ("🗑 Quitar portada", "🗑 Remove cover", "🗑 Удалить обложку"),
    ("📋 Copiar portada", "📋 Copy cover", "📋 Копировать обложку"),
    ("📥 Pegar portada (reemplaza la actual)", "📥 Paste cover (replaces current)", "📥 Вставить обложку (заменит текущую)"),
    ("💾 Guardar portada como imagen…", "💾 Save cover as image…", "💾 Сохранить обложку как изображение…"),
    ("Otro tamaño…", "Other size…", "Другой размер…"),
    # paneles
    ("⚙ Opciones…", "⚙ Options…", "⚙ Параметры…"),
    ("📖 Historia del artista (Wikipedia)", "📖 Artist history (Wikipedia)", "📖 История исполнителя (Википедия)"),
    ("▶️ Buscar artista en YouTube", "▶️ Search artist on YouTube", "▶️ Искать исполнителя на YouTube"),
    ("🟢 Buscar artista en Spotify", "🟢 Search artist on Spotify", "🟢 Искать исполнителя в Spotify"),
    ("🌊 Buscar artista en Tidal", "🌊 Search artist on Tidal", "🌊 Искать исполнителя в Tidal"),
    ("🎧 Buscar artista en Qobuz", "🎧 Search artist on Qobuz", "🎧 Искать исполнителя в Qobuz"),
    ("General", "General", "Общие"), ("Etiquetas", "Tags", "Теги"), ("Panel de etiquetas", "Tag panel", "Панель тегов"),
    ("Portadas", "Covers", "Обложки"), ("Reproductor", "Player", "Плеер"),
    ("Abrir la última carpeta al iniciar", "Open the last folder on start", "Открывать последнюю папку при запуске"),
    ("Confirmar antes de eliminar (con papelera)", "Confirm before deleting (with recycle bin)", "Подтверждать удаление (с корзиной)"),
    ("Mostrar la guía rápida cada vez que se inicia", "Show the quick guide on every start", "Показывать краткое руководство при каждом запуске"),
    ("Campos que se muestran en el panel de metadatos:", "Fields shown in the metadata panel:", "Поля на панели метаданных:"),
    ("Tamaño máximo de las portadas nuevas (nunca se agranda):", "Max size of new covers (never enlarged):", "Макс. размер новых обложек (не увеличиваются):"),
    ("Pasar a la siguiente canción al terminar", "Play next song when finished", "Переходить к следующей песне"),
    ("Información técnica (códec, tasa de bits, frecuencia…)", "Technical info (codec, bitrate, frequency…)", "Техническая информация (кодек, битрейт, частота…)"),
    ("🔎 Buscar letra en LRCLIB (sincronizada)", "🔎 Find lyrics on LRCLIB (synced)", "🔎 Найти текст в LRCLIB (с синхронизацией)"),
    ("Letras", "Lyrics", "Тексты песен"),
    ("Preferir la letra sincronizada (con minutos) al buscar en LRCLIB", "Prefer synced lyrics (with timestamps) from LRCLIB", "Предпочитать синхронизированный текст (с таймкодами) из LRCLIB"),
    ("Guardar también un archivo .lrc junto a la canción", "Also save a .lrc file next to the song", "Также сохранять файл .lrc рядом с песней"),
    ("🎼 Géneros", "🎼 Genres", "🎼 Жанры"),
    ("Aceptar", "OK", "ОК"), ("Silenciar", "Mute", "Выключить звук"), ("Quitar silencio", "Unmute", "Включить звук"),
    ("Acerca de Music Manager", "About Music Manager", "О программе Music Manager"), ("Cancelar", "Cancel", "Отмена"),
    ("&Fuente de etiquetas", "&Tag source", "&Источник тегов"),
    ("🎼 Buscar en MusicBrainz…", "🎼 Search MusicBrainz…", "🎼 Поиск в MusicBrainz…"),
    ("💿 Buscar en Discogs…", "💿 Search Discogs…", "💿 Поиск в Discogs…"),
    ("🔑 Token de Discogs…", "🔑 Discogs token…", "🔑 Токен Discogs…"),
    ("Fuentes de etiquetas", "Tag sources", "Источники тегов"),
    ("Códec", "Codec", "Кодек"), ("Tasa de bits", "Bitrate", "Битрейт"), ("Frecuencia", "Frequency", "Частота"),
    ("Duración", "Duration", "Длительность"), ("Modo", "Mode", "Режим"), ("Tamaño", "Size", "Размер"),
    ("🔍 Buscar", "🔍 Search", "🔍 Найти"), ("✔ Aplicar a la canción", "✔ Apply to song", "✔ Применить к песне"),
    ("Aplicar:", "Apply:", "Применить:"),
    ("🔍 Buscar canción…", "🔍 Search song…", "🔍 Поиск песни…"), ("Incluir subcarpetas", "Include subfolders", "Включая подпапки"),
    ("📁 Carpetas", "📁 Folders", "📁 Папки"), ("📁 Árbol 2", "📁 Tree 2", "📁 Дерево 2"),
    ("Metadatos (de las canciones seleccionadas)", "Metadata (of selected songs)", "Метаданные (выбранных песен)"),
    ("Título", "Title", "Название"), ("Artista", "Artist", "Исполнитель"), ("Álbum", "Album", "Альбом"),
    ("Artista del álbum", "Album artist", "Исполнитель альбома"), ("Compositor", "Composer", "Композитор"),
    ("Género", "Genre", "Жанр"), ("Año", "Year", "Год"), ("Pista", "Track", "Трек"), ("Disco", "Disc", "Диск"),
    ("Aplicar a selección", "Apply to selection", "Применить к выбранным"),
    ("✏️ Renombrar archivo…", "✏️ Rename file…", "✏️ Переименовать файл…"),
    ("💾 Guardar cambios", "💾 Save changes", "💾 Сохранить изменения"),
    ("Letra", "Lyrics", "Текст"),     ("Portada", "Cover", "Обложка"), ("Selecciona una canción", "Select a song", "Выберите песню"),
    ("Reconocer géneros con IA", "Recognize genres with AI", "Определить жанры с помощью ИИ"),
    ("✨ Sugerir género (selección o todas)", "✨ Suggest genre (selection or all)", "✨ Предложить жанр (выбранные или все)"),
    ("💬 Hablar con la IA sobre este género", "💬 Talk to the AI about this genre", "💬 Обсудить этот жанр с ИИ"),
    ("Pulsa «Sugerir género» para ver opciones.", "Press “Suggest genre” to see options.", "Нажмите «Предложить жанр», чтобы увидеть варианты."),
    # ajustes
    ("Ajustes", "Settings", "Настройки"), ("Inteligencia artificial", "Artificial intelligence", "Искусственный интеллект"),
    ("Apariencia", "Appearance", "Оформление"), ("Idioma", "Language", "Язык"),
    ("Elige el proveedor, el modelo y pega tu clave.", "Choose the provider and model, and paste your key.", "Выберите провайдера и модель и вставьте ключ."),
    ("Proveedor", "Provider", "Провайдер"), ("Modelo", "Model", "Модель"), ("API key", "API key", "API-ключ"),
    ("Tema", "Theme", "Тема"), ("Oscuro", "Dark", "Тёмная"), ("Claro", "Light", "Светлая"),
    ("Color de acento", "Accent color", "Акцентный цвет"), ("🎨 Otro color…", "🎨 Other color…", "🎨 Другой цвет…"),
    ("↺ Restablecer", "↺ Reset", "↺ Сбросить"),
    ("Idioma de la interfaz", "Interface language", "Язык интерфейса"), ("Cerrar", "Close", "Закрыть"),
    ("Algunos mensajes emergentes siguen en español.", "Some pop-up messages are still in Spanish.", "Некоторые всплывающие сообщения пока на испанском."),
    # espectrograma
    ("📊 Espectrograma y análisis de calidad", "📊 Spectrogram & quality analysis", "📊 Спектрограмма и анализ качества"),
    ("Frecuencia máxima:", "Max frequency:", "Макс. частота:"), ("Completa", "Full", "Полная"),
    ("💾 Guardar imagen…", "💾 Save image…", "💾 Сохранить изображение…"),
    ("Espectrogramas", "Spectrograms", "Спектрограммы"), ("Comparación", "Comparison", "Сравнение"),
    ("Análisis", "Analysis", "Анализ"),
]
try:
    from i18n_more import ROWS as _MORE
except Exception:   # pragma: no cover
    _MORE = []
TABLE = {es: {"en": en, "ru": ru} for es, en, ru in _ROWS + _MORE}
# claves que sirven de prefijo («No se pudo: » + detalle) y claves con %s (texto variable en medio)
_PREFIXES = sorted((k for k in TABLE if k.endswith((": ", " ")) and len(k.strip()) > 3), key=len, reverse=True)
_PATTERNS = [(re.compile("^" + re.escape(k).replace("%s", "(.+?)") + "$", re.S), k) for k in TABLE if "%s" in k]

# botones estándar de los cuadros de mensaje (Qt no trae traducciones)
STD_BUTTONS = {
    "Yes": ("Sí", "Yes", "Да"), "No": ("No", "No", "Нет"), "Ok": ("Aceptar", "OK", "ОК"),
    "Cancel": ("Cancelar", "Cancel", "Отмена"), "Save": ("Guardar", "Save", "Сохранить"),
    "Discard": ("Descartar", "Discard", "Не сохранять"), "Close": ("Cerrar", "Close", "Закрыть"),
    "Apply": ("Aplicar", "Apply", "Применить"), "Retry": ("Reintentar", "Retry", "Повторить"),
    "Ignore": ("Ignorar", "Ignore", "Пропустить"), "Abort": ("Abortar", "Abort", "Прервать"),
    "Open": ("Abrir", "Open", "Открыть"), "Reset": ("Restablecer", "Reset", "Сбросить"),
    "YesToAll": ("Sí a todo", "Yes to all", "Да для всех"), "NoToAll": ("No a todo", "No to all", "Нет для всех"),
}


def set_lang(code):
    global CUR
    CUR = code if code in ("es", "en", "ru") else "es"


def _lookup(s):
    """Traducción de s o None si no se conoce (exacta, con %s, o por prefijo)."""
    d = TABLE.get(s)
    if d:
        return d[CUR]
    for rx, k in _PATTERNS:
        m = rx.match(s)
        if m:
            out = TABLE[k][CUR]
            for g in m.groups():
                out = out.replace("%s", g, 1)
            return out
    for k in _PREFIXES:
        if s.startswith(k) and len(s) > len(k):
            return TABLE[k][CUR] + s[len(k):]
    return None


def known(s):
    return bool(s) and (s in TABLE or any(rx.match(s) for rx, _ in _PATTERNS)
                        or any(s.startswith(k) and len(s) > len(k) for k in _PREFIXES))


def tr(s):
    if CUR == "es" or not s or not isinstance(s, str):
        return s
    out = _lookup(s)
    return out if out is not None else s


def fix_std_buttons(box):
    """Pone «Sí / No / Aceptar…» en los botones estándar en el idioma actual."""
    idx = {"es": 0, "en": 1, "ru": 2}.get(CUR, 0)
    try:
        if isinstance(box, QMessageBox):
            pairs = [(box.standardButton(b), b) for b in box.buttons()]
            enum = QMessageBox.StandardButton
        else:
            pairs = [(box.standardButton(b), b) for b in box.buttons()]
            enum = QDialogButtonBox.StandardButton
        for sb, b in pairs:
            for name, texts in STD_BUTTONS.items():
                if sb == getattr(enum, name, None):
                    b.setText(texts[idx])
                    break
    except Exception:
        pass


def _deco(obj, text):
    """Si el texto empieza con un emoji, lo cambia por un icono dibujado y devuelve el texto sin el emoji."""
    try:
        import icons
        kind, rest = icons.split(text)
        if kind and hasattr(obj, "setIcon"):
            white = hasattr(obj, "objectName") and obj.objectName() == "accent"
            from PyQt6.QtGui import QAction
            ctx = "menu" if isinstance(obj, QAction) else ("check" if obj.isCheckable() else None)
            obj.setIcon(icons.vicon(kind, "white" if white else None, ctx))
            return rest
    except Exception:
        pass
    return text


def _apply(obj, attr, get, set_, deco=False):
    cur = get()
    if not cur:
        return
    ok, lk = "_i18n_o_" + attr, "_i18n_l_" + attr
    orig, last = obj.property(ok), obj.property(lk)
    if orig is None or cur != last:           # texto nuevo (o cambiado desde el programa)
        if known(cur):
            orig = cur
        else:
            obj.setProperty(ok, None)
            if deco:
                shown = _deco(obj, cur)
                if shown != cur:
                    set_(shown)
            return
    new = tr(orig)
    if deco:
        new = _deco(obj, new)
    obj.setProperty(ok, orig)
    obj.setProperty(lk, new)
    if new != cur:
        set_(new)


def deco(obj):
    """Aplica icono/traducción a un botón o acción cuyo texto se acaba de cambiar desde el programa."""
    _apply(obj, "t", obj.text, obj.setText, True)


def retranslate(root):
    objs = [root] + root.findChildren(QObject)
    for o in objs:
        if isinstance(o, QAction):
            _apply(o, "t", o.text, o.setText, True)
            _apply(o, "tip", o.toolTip, o.setToolTip)
        elif isinstance(o, QMenu):
            _apply(o, "m", o.title, o.setTitle)
        elif isinstance(o, QWidget):
            if isinstance(o, QAbstractButton):
                _apply(o, "t", o.text, o.setText, True)
            elif isinstance(o, QLabel):
                _apply(o, "t", o.text, o.setText)
            elif isinstance(o, QGroupBox):
                _apply(o, "t", o.title, o.setTitle)
            elif isinstance(o, QComboBox):
                for i in range(o.count()):
                    role = Qt.ItemDataRole.UserRole + 77
                    orig = o.itemData(i, role)
                    if orig is None and known(o.itemText(i)):
                        orig = o.itemText(i)
                        o.setItemData(i, orig, role)
                    if orig is not None and o.itemText(i) != tr(orig):
                        o.setItemText(i, tr(orig))
            elif isinstance(o, QLineEdit):
                _apply(o, "ph", o.placeholderText, o.setPlaceholderText)
            elif isinstance(o, QTabWidget):
                for i in range(o.count()):
                    # las pestañas guardan el original en una propiedad por índice
                    key = f"_i18n_tab{i}"
                    cur = o.tabText(i)
                    orig = o.property(key)
                    if orig is None or cur != tr(orig):
                        orig = cur if known(cur) else orig
                    if orig is not None:
                        o.setProperty(key, orig)
                        o.setTabText(i, tr(orig))
            if isinstance(o, (QMessageBox, QDialogButtonBox)):
                fix_std_buttons(o)
            if o.toolTip():
                _apply(o, "wtip", o.toolTip, o.setToolTip)
            if o.windowTitle() and o.isWindow():
                _apply(o, "wt", o.windowTitle, o.setWindowTitle)

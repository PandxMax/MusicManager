"""Traducción sencilla de la interfaz: español (base), inglés y ruso."""
from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QAbstractButton, QLabel, QGroupBox, QLineEdit, QMenu, QTabWidget, QWidget

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
    ("🔍 Buscar canción…", "🔍 Search song…", "🔍 Поиск песни…"), ("Incluir subcarpetas", "Include subfolders", "Включая подпапки"),
    ("📁 Carpetas", "📁 Folders", "📁 Папки"), ("📁 Árbol 2", "📁 Tree 2", "📁 Дерево 2"),
    ("Metadatos (de las canciones seleccionadas)", "Metadata (of selected songs)", "Метаданные (выбранных песен)"),
    ("Título", "Title", "Название"), ("Artista", "Artist", "Исполнитель"), ("Álbum", "Album", "Альбом"),
    ("Artista del álbum", "Album artist", "Исполнитель альбома"), ("Compositor", "Composer", "Композитор"),
    ("Género", "Genre", "Жанр"), ("Año", "Year", "Год"), ("Pista", "Track", "Трек"), ("Disco", "Disc", "Диск"),
    ("Aplicar a selección", "Apply to selection", "Применить к выбранным"),
    ("✏️ Renombrar archivo…", "✏️ Rename file…", "✏️ Переименовать файл…"),
    ("💾 Guardar cambios", "💾 Save changes", "💾 Сохранить изменения"),
    ("Letra", "Lyrics", "Текст"), ("✨ Poner letra con IA", "✨ Add lyrics with AI", "✨ Добавить текст с помощью ИИ"),
    ("Portada", "Cover", "Обложка"), ("Selecciona una canción", "Select a song", "Выберите песню"),
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
TABLE = {es: {"en": en, "ru": ru} for es, en, ru in _ROWS}


def set_lang(code):
    global CUR
    CUR = code if code in ("es", "en", "ru") else "es"


def tr(s):
    if CUR == "es":
        return s
    d = TABLE.get(s)
    return d[CUR] if d else s


def _apply(obj, attr, get, set_):
    cur = get()
    if not cur:
        return
    ok, lk = "_i18n_o_" + attr, "_i18n_l_" + attr
    orig, last = obj.property(ok), obj.property(lk)
    if orig is None or cur != last:           # texto nuevo (o cambiado desde el programa)
        if cur in TABLE:
            orig = cur
        else:
            obj.setProperty(ok, None)
            return
    new = tr(orig)
    obj.setProperty(ok, orig)
    obj.setProperty(lk, new)
    if new != cur:
        set_(new)


def retranslate(root):
    objs = [root] + root.findChildren(QObject)
    for o in objs:
        if isinstance(o, QAction):
            _apply(o, "t", o.text, o.setText)
            _apply(o, "tip", o.toolTip, o.setToolTip)
        elif isinstance(o, QMenu):
            _apply(o, "m", o.title, o.setTitle)
        elif isinstance(o, QWidget):
            if isinstance(o, QAbstractButton):
                _apply(o, "t", o.text, o.setText)
            elif isinstance(o, QLabel):
                _apply(o, "t", o.text, o.setText)
            elif isinstance(o, QGroupBox):
                _apply(o, "t", o.title, o.setTitle)
            elif isinstance(o, QLineEdit):
                _apply(o, "ph", o.placeholderText, o.setPlaceholderText)
            elif isinstance(o, QTabWidget):
                for i in range(o.count()):
                    # las pestañas guardan el original en una propiedad por índice
                    key = f"_i18n_tab{i}"
                    cur = o.tabText(i)
                    orig = o.property(key)
                    if orig is None or cur != tr(orig):
                        orig = cur if cur in TABLE else orig
                    if orig is not None:
                        o.setProperty(key, orig)
                        o.setTabText(i, tr(orig))
            if o.windowTitle() and o.isWindow():
                _apply(o, "wt", o.windowTitle, o.setWindowTitle)

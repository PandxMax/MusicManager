# Music Manager para Android

Versión para Android de Music Manager (Kotlin + Jetpack Compose). Creada por **PandxMax**.

## Qué incluye
- **Explorador de carpetas** (rejilla o lista), buscar, incluir subcarpetas, ⟳ actualizar, nueva carpeta, renombrar,
  cortar / copiar / pegar (para mover), eliminar.
- **Reproductor** en segundo plano con notificación: cola, aleatorio, repetir, listas guardadas y mini-reproductor.
  Los colores de la app cambian según la portada de la canción.
- **Editor de metadatos** (uno o varios archivos a la vez): Título, Intérprete, Álbum, Intérprete del álbum,
  Compositor, Género, Año, Pista, Número de disco, Comentario y Directorio; etiquetas técnicas (codec, tipo de etiqueta,
  bitrate, frecuencia, duración, modo, tamaño). Los MP3 se guardan en ID3v2.3 (lo que entiende Windows).
- **Portadas**: elegir de la galería, **buscar automáticamente** (iTunes y Deezer, varias opciones), quitar, guardar como
  `cover.jpg`, ver en grande, y si no hay nada, abrir Google Imágenes.
- **Letras** con LRCLIB (sincronizadas) y edición.
- **IA** (Claude, ChatGPT o Gemini con tu propia API key): rellenar metadatos y sugerir géneros.
- **MusicBrainz** y **Discogs** (token) para rellenar etiquetas.
- **Botones web**: YouTube, Spotify, Tidal, Qobuz y Wikipedia.
- **Espectrograma y calidad** de audio, con **comparación** de canciones de distintos lugares.
- **Descargar de YouTube a MP3** (yt-dlp) y luego editar metadatos y portada.
- Aviso «¿Desea guardar los cambios?» al salir, y botón 💾 para guardar.

## Qué no incluye (todavía)
- Convertir formato (en Android no hay un ffmpeg libre mantenido que se pueda incluir fácilmente).
- Arrastrar y soltar: se usa cortar/copiar y «Pegar aquí».

## Cómo obtener el APK
1. En GitHub: **Actions → «Crear APK» → Run workflow**.
2. Cuando termine, en **Releases** aparece «Music Manager Android» con el archivo `MusicManager-Android.apk`.
3. Descárgalo en el teléfono e instálalo (permite instalar apps de origen desconocido si te lo pide).
4. La primera vez, concede el permiso **«Acceso a todos los archivos»** para poder editar etiquetas y mover carpetas.

Requiere Android 11 o superior.

> Descarga solo música o contenido que tengas derecho a guardar.

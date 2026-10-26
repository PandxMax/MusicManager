<div align="center">

<img src="logo.png" width="140" alt="Music Manager"/>

# 🎵 Music Manager

**Organiza tu música como un profesional: explora, mueve, edita etiquetas, portadas y letras, analiza la calidad real de tus archivos y deja que una IA te ayude con los géneros.**

<br/>

<a href="https://github.com/PandxMax/MusicManager/releases/latest/download/MusicManager-Windows.zip">
  <img src="https://img.shields.io/badge/%E2%AC%87%20DESCARGAR%20PARA%20WINDOWS-7C5CFF?style=for-the-badge&logoColor=white" alt="Descargar Music Manager" height="48"/>
</a>

<sub>Descarga el .zip, descomprímelo y abre <b>MusicManager.exe</b>. Después se actualiza solo desde <i>Ayuda → Buscar actualizaciones</i>.</sub>

<br/>

![Versión](https://img.shields.io/badge/Versi%C3%B3n-1.15-7C5CFF)
![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![PyQt6](https://img.shields.io/badge/Interfaz-PyQt6-41CD52?logo=qt&logoColor=white)
![IA](https://img.shields.io/badge/IA-Claude%20%7C%20ChatGPT%20%7C%20Gemini-7C5CFF)
![Idiomas](https://img.shields.io/badge/Idiomas-ES%20%7C%20EN%20%7C%20RU-orange)

</div>

---

## ✨ ¿Qué es?

**Music Manager** es un programa de escritorio todo en uno para tu biblioteca musical. Une un **explorador de archivos** (con arrastrar y soltar), un **editor de etiquetas** (metadatos), un **analizador de calidad de audio** tipo *Spek* y un **asistente de IA** para reconocer géneros y subgéneros, todo en una sola ventana, con tema oscuro o claro.

---

## 🚀 Funciones

### 📁 Explorador de carpetas
- **Arrastra y suelta** canciones o carpetas sobre otra carpeta para moverlas.
- **Dos árboles** de carpetas a la vez (activables y en vertical u horizontal) para mover de uno a otro sin perderte.
- Mover entre árboles fácil: la **carpeta destino se resalta** al arrastrar, **Ctrl al soltar = copiar** y clic derecho → *Mover / Copiar al otro árbol*.
- **Barra horizontal** en los árboles para ver nombres largos y carpetas muy anidadas.
- **Cortar, copiar, pegar, renombrar y eliminar** archivos y carpetas (Ctrl+X, Ctrl+C, Ctrl+V, F2, Supr). Eliminar usa la papelera.
- Botones **◀ ▶ ▲** (atrás, adelante, subir) como en el Explorador de Windows, también con `Alt+←/→/↑` y los botones laterales del ratón.
- Vista de **iconos con portadas** o de **lista**.
- **Búsqueda** de canciones, con opción de incluir subcarpetas.
- Selección múltiple rápida: arrastra el ratón y baja con la rueda.

### 🏷️ Editor de metadatos
Edita **título, artista, álbum, artista del álbum, compositor, género, año, pista, disco y BPM** de una o de muchas canciones a la vez.
Compatible con **MP3, FLAC, OGG, Opus y M4A/MP4**. Los cambios quedan marcados hasta que pulsas **Guardar** (Ctrl+S).

Además del editor, el panel muestra la **información técnica** de cada archivo: **códec, tasa de bits, frecuencia, duración, modo (CBR/VBR) y tamaño**.

### 👤 Información del artista
Clic derecho sobre el artista (en el panel de metadatos o en la lista): **historia en Wikipedia**, búsqueda en **YouTube**, **Spotify**, **Tidal** y **Qobuz**, todo en tu navegador.

### 🌐 Fuentes de etiquetas (MusicBrainz y Discogs)
- Menú **Fuente de etiquetas**: busca la canción en **MusicBrainz** (gratis) o en **Discogs** (con un token personal gratuito).
- Elige el resultado correcto y aplica **título, artista, álbum, año, pista, género y portada** con casillas para decidir qué copiar.
- Los cambios quedan pendientes (en naranja) hasta que pulses Guardar.

### 🖼️ Portadas
- Panel con botones **➕ cambiar, 💾 guardar, ❌ quitar y 👁 ver en grande**, y los datos de la imagen (formato, píxeles y peso).
- **Cambiar, quitar, copiar y pegar** portada: copia la de una canción y pégala en otras.
- **Guardar la portada como imagen**.
- **Redimensionar** a 300, 500, 600, 800, 1000, 1200 px u otro tamaño (nunca agranda).
- Todo desde el **clic derecho** sobre la portada.

### 📝 Letras sincronizadas (LRCLIB)
- **Panel flotante de lista de reproducción** (☰), volumen que sube hacia arriba y cuadritos que bailan al ritmo de la canción.
- **🔄 Se actualiza solo**: Ayuda ▸ Buscar actualizaciones descarga e instala la versión nueva desde GitHub.
- **Portadas con varias opciones**, **lista de reproducción propia** (arrastrar, ordenar, guardar), disco giratorio y volumen desplegable.
- **📊 Espectrograma en el mismo panel**, botones ☰ ⏮ ⏭ ⏹ en el reproductor, colores que cambian con la portada y búsqueda en Google Imágenes si no hay portada.
- **✨ Portada automática**: un botón busca en iTunes y Deezer la portada en alta calidad y la pone sola.
- El panel derecho tiene dos botones, **🎼 Géneros** y **📝 Letra**, que se turnan el mismo espacio bajo la portada.
- **Buscar letra en LRCLIB** (gratis, sin clave): trae la letra **sincronizada** con el minuto de cada línea (formato LRC).
- Se guarda en la etiqueta del archivo (y como letra sincronizada SYLT en MP3) y, si quieres, en un **archivo `.lrc`** junto a la canción para otros reproductores.

### 🤖 IA para géneros
- Funciona con **Claude, ChatGPT o Gemini** (usas tu propia clave API).
- **Sugerir género** muestra una lista de géneros y subgéneros; **tú eliges**, la IA no aplica nada sola.
- **Chat con la IA** para cuestionar si el subgénero elegido es correcto.
- Los ajustes (proveedor, modelo y clave) están en **Ajustes → Ajustes de IA**.

### 📊 Espectrograma y análisis de calidad
Selecciona una o varias canciones y abre **Herramientas → Espectrograma**.
- **Espectrograma estilo Spek**: frecuencia en kHz, tiempo y nivel en dB.
- Datos técnicos: **frecuencia de muestreo, bits, bitrate, frecuencia de corte, pico, RMS y rango dinámico**.
- **Veredicto de calidad**: *Alta fidelidad*, *Calidad normal* o *Calidad baja*, con los motivos.
- Detecta archivos **convertidos desde MP3/AAC a FLAC** (sin pérdida solo en apariencia) y recortes (clipping).
- **Comparación de varias canciones**: tabla lado a lado y curvas de espectro superpuestas.
- Limita la frecuencia máxima y **guarda la imagen** como PNG.

> El veredicto es una estimación basada en el espectro, no una prueba definitiva.

### 🔄 Convertir formatos
- Selecciona canciones y abre **Herramientas → Convertir formato**.
- Salida en **MP3, FLAC, M4A (AAC), OGG (Vorbis), Opus o WAV**, con la calidad (kbps) que elijas.
- Conserva **etiquetas y portada** (la portada solo en MP3, FLAC y M4A).
- Guarda junto a los originales o en otra carpeta; nunca sobrescribe nada.

### ▶️ Reproductor y YouTube
- Reproductor compacto en la **línea de estado, abajo a la derecha**: play/pausa, barra de avance y volumen. El **altavoz silencia**, la **rueda del ratón** cambia el volumen y al pasar el ratón por las barras se ve el **minuto** y el **% de volumen**. Doble clic en una canción para reproducirla. **Haz clic en la barra** donde quieras para saltar a ese punto.
- **Buscar en YouTube**: clic derecho en una canción y se abre tu navegador con esa canción.

### 🎨 Personalización
- **Tema oscuro o claro** y **color de acento** a tu gusto.
- **Idiomas:** Español, English y Русский.
- **Ajustes con árbol de categorías** (General, Apariencia, Idioma, Etiquetas, Fuentes de etiquetas, IA, Reproductor), con *Aceptar* y *Cancelar*. Elige qué campos ver en el panel, abrir la última carpeta al iniciar, confirmaciones y más.
- Todo organizado en menús para ocupar el mínimo espacio.

---

## 📥 Cómo obtener el programa (.exe)

No necesitas instalar nada: GitHub lo construye por ti.

1. Entra en la pestaña **Actions** de este repositorio.
2. Elige **Crear EXE** → **Run workflow**.
3. Espera unos minutos. Al terminar, baja a **Artifacts** y descarga **MusicManager-Windows**.
4. Descomprime la carpeta y abre **`MusicManager.exe`**.

> Copia siempre la **carpeta completa**, no solo el `.exe`.
> Si Windows muestra la pantalla azul de SmartScreen: *Más información → Ejecutar de todas formas*.

### 🛠️ Alternativa: ejecutarlo desde el código

```bash
pip install -r requirements.txt
python music_manager.py
```

En Windows también puedes hacer doble clic en `CREAR_PROGRAMA.bat` para crear el `.exe`, instalarlo y generar los accesos directos.

---

## 🧭 Guía rápida

| Quiero… | Hago… |
|---|---|
| Mover una canción o carpeta | Arrástrala sobre otra carpeta |
| Copiar / cortar / pegar | `Ctrl+C` · `Ctrl+X` · `Ctrl+V` |
| Reproducir | Doble clic en la canción |
| Editar etiquetas | Selecciona, cambia los campos y `Ctrl+S` |
| Opciones de portada | Clic derecho sobre la portada |
| Sugerir género con IA | Pon tu clave en *Ajustes → Ajustes de IA* y pulsa *Sugerir género* |
| Analizar la calidad | *Herramientas → Espectrograma y calidad* |
| Buscar la canción en YouTube | Clic derecho en la canción → *Buscar en YouTube* |
| Convertir a otro formato | *Herramientas → Convertir formato* |
| Copiar en vez de mover al arrastrar | Mantén `Ctrl` al soltar |
| Cambiar tema, color o idioma | Menú **Ajustes** |

---

## 🧩 Tecnología

**Python** · **PyQt6** (interfaz y reproductor) · **mutagen** (etiquetas) · **MusicBrainz / Discogs** (fuentes de etiquetas) · **numpy** + **ffmpeg** (espectrogramas y conversión) · **PyInstaller** (el `.exe`).

---

<div align="center">

Hecho con 🎶 para quien ama tener su música en orden.

</div>

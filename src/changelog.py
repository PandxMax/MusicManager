"""Historial de novedades de cada versión (lo más nuevo arriba)."""

CHANGELOG = [
    ('2.26', [
        'El reproductor vuelve a ser siempre la barra clásica de abajo (se quitó la elección de estilo en Ajustes). En la barra hay dos botones nuevos: el de celular abre o cierra el reproductor grande (modo celular) y el de ventanita abre el modo ventana, con solo la portada.',
    ]),
    ('2.25', [
        'Reproductor separado: el botón de arriba a la izquierda ahora es «Ocultar editor» (queda solo el reproductor) y, con el editor escondido, «Mostrar editor»; en el panel del editor hay además un botón para dejar solo el reproductor. Ventanita «solo la portada»: cambiar su tamaño ya es fluido (no parpadea).',
    ]),
    ('2.24', [
        'Nuevo «Separar el reproductor» (botón de ventanita del panel, o Reproducción → Separar, Ctrl+Shift+M): el reproductor pasa a su propia ventana con todas sus opciones y el editor sigue abierto; son dos ventanas en la barra de tareas. Ventanita «solo la portada» más cuidada: portada limpia, botones redondos de vidrio y una franja con el título, el artista, la barrita fina y el volumen. Ayuda → «Primeros pasos» (recorrido corto, sale solo en instalaciones nuevas) y «Reportar un problema» (prepara el informe con la versión y los últimos errores para enviarlo).',
    ]),
    ('2.23', [
        'Windows ahora sabe qué canción suena (título, artista, álbum y portada): aparece en Wallpaper Engine, en el panel multimedia de Windows y en la pantalla de bloqueo, y funcionan las teclas multimedia del teclado. Ventanita «solo la portada»: la carátula se ve entera y limpia; la barrita, los tiempos y el nuevo botón de volumen van en una franja debajo de la imagen.',
    ]),
    ('2.22', [
        'Los atajos de música (AvPág, RePág, Pausa o los que elijas) ahora funcionan también fuera del programa: escribiendo un documento, jugando o con el programa minimizado. Se puede desactivar en Ajustes → Atajos de música. Correcciones internas: la actualización comprueba que la descarga esté completa y sea la publicada antes de instalar; las claves de IA, Discogs y AcoustID se guardan cifradas; los fallos menores quedan anotados en «errores_menores.txt»; versiones de componentes fijadas para que las compilaciones sean siempre iguales; el panel y la ventanita comparten la biblioteca ya leída.',
    ]),
    ('2.21', [
        'Guardar muchos cambios y mover muchos archivos ahora van en segundo plano con barra de progreso (la ventana ya no se congela). Nuevo «Deshacer último mover / renombrar» (Edición, Ctrl+Alt+Z). Atajos de música: AvPág = siguiente, RePág = anterior, Pausa = reproducir/pausa, en todas las ventanas; se cambian en Ajustes → Atajos de música. Barrita de volumen desplegable en el reproductor (botón de altavoz bajo la onda). En la ventanita «solo la portada» ya no aparece ni desaparece nada sobre la carátula: queda un botoncito fijo y discreto, y lo demás está en el clic derecho.',
    ]),
    ('2.20', [
        'Mejoras internas del reproductor nuevo: la Cola ya no salta al principio mientras la miras (solo se vuelve a llenar si de verdad cambió algo en las carpetas, y conserva dónde estabas); usa menos memoria con bibliotecas grandes (las portadas pequeñas se sueltan y se recargan al volver); y el programa abre un poco más ligero (las portadas de la Cola se preparan recién cuando la abres).',
    ]),
    ('2.19', [
        'El reproductor del editor (el panel de la derecha) ahora tiene el mismo diseño nuevo: portada difuminada, «REPRODUCIENDO · n de N», calidad, barra con la onda, controles y la barra Cola · Letra · Ajustes · Editar · Calidad, con la Cola (canciones, carpetas del árbol, artistas, géneros) dentro del panel. El estilo de portada elegido vale para los dos.',
    ]),
    ('2.18', [
        'Modo reproductor: la portada difuminada ahora sale entera, adaptada al ancho (sin recortarse); la versión extendida queda como opción en el menú ⋮, junto con la portada normal. Botón «← Editor» bien visible para volver. Nuevo modo «solo la portada»: una ventanita con la portada, anterior / pausa / siguiente y una barrita con la onda de la canción; se agranda o achica tirando de los bordes o de la esquina.',
    ]),
    ('2.17', [
        'Modo reproductor: nueva portada grande difuminada (ocupa todo lo de arriba y se funde con el fondo, con el título encima, como en la imagen); en el menú ⋮ se elige «Portada grande difuminada» o «Portada normal». La Cola ahora refleja el árbol de carpetas: «Carpetas» muestra las mismas carpetas principales que el árbol (si agregas o quitas una, cambia), y «Canciones» tiene todas las canciones de todas esas carpetas.',
    ]),
    ('2.16', [
        'Modo reproductor con el diseño de la app del celular: portada en tarjeta, «REPRODUCIENDO · 1483 de 3786», título, artista, calidad (MP3 · 44.1 kHz · 320 kbps · Alta), barra de avance con la onda, controles con el botón blanco grande y la barra Cola · Letra · Ajustes · Editar · Calidad; el fondo sigue mezclando y difuminando los colores de la portada. «Cola» abre todas las canciones, carpetas, artistas y géneros, ahora con la portada de cada canción y de cada carpeta.',
    ]),
    ('2.15', [
        'Modo reproductor: ya no se traba (la ventanita se redibujaba entera muchas veces por segundo; ahora el fondo se dibuja una sola vez). Nuevo: el primer botón de abajo abre la Biblioteca con «Canciones» (todas las de la carpeta que estabas editando, incluidas todas sus subcarpetas, con la cantidad cargada), «Carpetas», «Artistas» y «Géneros», con buscador. Al tocar una canción suena y «siguiente» sigue esa lista.',
    ]),
    ('2.14', [
        'Nuevo «modo reproductor»: botón 🪟 en el reproductor (o Ctrl+M). El editor se esconde y queda solo un reproductor pequeño que puedes mover a cualquier parte de la pantalla, con la portada que se funde con el color de la canción, la onda para avanzar, los controles encima, la calidad del archivo, letra y cola. Esc o el botón de cuadritos vuelve al editor.',
    ]),
    ('2.13', [
        'Búsqueda en carpetas con miles de canciones (por ejemplo 3500 con «Incluir subcarpetas»): ya no parpadea ni se traba. La lista se arma solo con lo que coincide, en vez de esconder canción por canción, y cada búsqueda tarda menos de una décima de segundo.',
    ]),
    ('2.12', [
        'Nuevo: clic derecho en una canción → «Ir a la carpeta». Ideal tras buscar (o con «Incluir subcarpetas»): abre la carpeta donde está la canción, quita la búsqueda y la deja marcada y a la vista. También «Mostrar en el Explorador de Windows».',
    ]),
    ('2.11', [
        'Buscar en carpetas grandes (miles de canciones, con subcarpetas): los resultados ya no salen con huecos ni «escondidos», y se puede bajar para ver todos. La búsqueda espera a que dejes de escribir (no se recalcula letra por letra) y las portadas de lo encontrado se cargan primero.',
    ]),
    ('2.10', [
        'Eliminar varias carpetas ya no congela el programa: se mandan todas juntas a la papelera en una sola operación (mucho más rápido) y en segundo plano. Desaparecen de la lista y los árboles al instante y el programa sigue respondiendo mientras tanto.',
    ]),
    ('2.09', [
        'Nuevo: Herramientas → Audio y calidad → «Reparar recortes (clipping)». Reconstruye los golpes fuertes «aplastados» que suenan ásperos; conserva etiquetas y portada; se guarda como copia «(reparada)» o reemplaza el original.',
        'Espectrograma: cuando una canción sale «Sospechosa» (FLAC que en realidad viene de un MP3), aparece la recomendación de convertirla a MP3 320 kbps —cuánto espacio ahorrarías— con un botón «Convertir a MP3…». Solo en esos casos.',
    ]),
    ('2.08', [
        'Redimensionar portada: si la portada no es cuadrada (por ejemplo 712×1000), se abre una ventanita para recortarla en cuadrado. Mueves el recuadro hasta la parte que quieres, lo agrandas o achicas con las esquinas o la rueda del ratón y eliges el tamaño final (500, 600, 800, 1000 o 1200 px). Las portadas que ya son cuadradas se redimensionan solas como antes.',
        'Con varias portadas no cuadradas, puedes recortar una a mano y marcar «recortar centradas las demás», o saltar alguna.',
    ]),
    ('2.07', [
        'Arrastrar muchas canciones (20, 50…) a una carpeta: ahora se mueven TODAS. Antes, si al empezar a arrastrar tenías Shift o Ctrl apretado (por ejemplo justo después de elegirlas con Shift+clic), la selección se recortaba y solo se pasaban unas cuantas.',
        'Cortar (Ctrl+X) se ve como en el Explorador: las canciones y carpetas cortadas quedan medio transparentes hasta que las pegas.',
    ]),
    ('2.06', [
        'Nuevo: copiar y pegar metadatos. Clic derecho en una canción → «Copiar metadatos» (Ctrl+Shift+C); luego eliges otras canciones → «Pegar metadatos…» (Ctrl+Shift+V) y marcas qué pegar: intérprete, álbum, género, año, portada… (título y pista vienen desmarcados). También en el menú Edición.',
    ]),
    ('2.05', [
        'Barra de arriba más despejada: solo queda el botón «Espectro». «Buscar etiquetas en MusicBrainz» y «Buscar etiquetas en Discogs» están ahora en Herramientas → Etiquetas y portadas.',
    ]),
    ('2.04', [
        'Arreglo: si había algo escrito en «Buscar canción», al cambiar de carpeta las canciones parecían desaparecer (solo se veían las que coincidían). Ahora, como en el Explorador, la búsqueda se quita sola al cambiar de carpeta.',
        'Mientras hay una búsqueda activa, encima de la lista se ve «Mostrando X de Y canciones · búsqueda «…»» con un botón «Quitar búsqueda»; si ninguna coincide, también se avisa.',
    ]),
    ('2.03', [
        'La carpeta del programa queda limpia: el analizador fpcalc.exe ahora va escondido dentro de «_internal» (junto a MusicManager.exe solo queda el programa). La copia vieja se borra sola al abrir.',
    ]),
    ('2.02', [
        'Menú Herramientas más corto: 4 categorías (Audio y calidad · Etiquetas y portadas · Organizar la biblioteca · Internet y servidor); al pasar el ratón por una se despliegan sus herramientas al lado.',
        'El botón «Apoyar» ya no es blanco: tiene el mismo estilo que los demás botones y su icono de taza con corazón sigue el tema y el color de acento.',
    ]),
    ('2.01', [
        'Nuevo botón «Apoyar» con el logo de Ko-fi junto al cambio de idioma, y un recuadro en «Acerca de» para apoyar el programa invitándome un café (ko-fi.com/pandxmax). ¡Gracias!',
    ]),
    ('2.00', [
        '¡Versión 2.00! Revisión general: se probó el programa entero de forma automática (todas las herramientas, guardar, renombrar, mover, vistas, temas e idiomas) y se corrigieron los fallos encontrados.',
        'Más estable: si algo falla dentro del programa, ya no se cierra de golpe; se anota en un registro y se avisa abajo. Nuevo: Ayuda → «Registro de errores» para ver o enviar los detalles.',
        'Renombrar en modo iconos: el cuadro forma parte de la tarjeta de la canción (mismo ancho y color). Si el nombre es largo, la tarjeta crece hacia abajo para que se vea entero; si es corto, se queda de su tamaño.',
        'Todas las ventanas de herramientas tienen el mismo aspecto: título grande arriba y márgenes amplios.',
        'Nuevo: Ayuda → «Atajos de teclado», con todas las teclas rápidas del programa.',
        'Organizar en carpetas: la columna «Ahora en» muestra «(aquí)» en vez de un punto.',
        'Al cambiar de idioma, la barra de enviar entre árboles y sus títulos también se traducen al momento.',
    ]),
    ('1.99', [
        'Renombrar en modo iconos, más limpio: la tarjeta de color de la canción se queda igual (mismo tamaño) y el cuadro para escribir va dentro de ella, justo donde estaba el nombre. Ya no se mueve ni cambia de tamaño mientras escribes; los nombres largos se parten en líneas dentro del cuadro.',
    ]),
    ('1.98', [
        'Renombrar en modo iconos: mientras escribes, el recuadro grande de color desaparece y solo queda sombreada la portada (como en el Explorador); el cuadro del nombre ya no parece «flotar» sobre el color. Al terminar, todo vuelve a la normalidad.',
    ]),
    ('1.97', [
        'Renombrar en modo iconos: el cuadro se adapta al largo del nombre. Un nombre corto da un cuadro estrecho; uno largo lo ensancha (hasta un poco más que el icono) y, si aún no cabe, pasa a varias líneas. Cambia en vivo mientras escribes o borras.',
    ]),
    ('1.96', [
        'Renombrar en modo iconos como en el Explorador de Windows: el cuadro mide lo mismo que el icono, el nombre se parte en varias líneas y el cuadro crece hacia abajo según lo que escribas. Enter guarda, Esc cancela y hacer clic fuera también guarda.',
    ]),
    ('1.95', [
        'Renombrar en modo iconos: el cuadro vuelve a ser pequeño, justo donde va el nombre; mientras escribes, el nombre viejo de debajo se oculta (ya no asoma ni hace falta taparlo).',
        'El menú «Ajustes» ya no despliega una lista: al pulsarlo se abre directamente la ventana de opciones (IA, apariencia, idioma… están todas dentro).',
    ]),
    ('1.94', [
        'Nuevo: clic derecho en canciones → «Quitar paréntesis del nombre…». Quita lo que va entre paréntesis (y si quieres entre corchetes) en el nombre del archivo y en el título: «Summer (Official Video) [HD]» → «Summer». Antes de aplicar ves la lista con cómo quedará cada una.',
        'El repositorio de GitHub está ordenado: el código en «src», el icono y el logo en «assets». La portada del proyecto (README) se ve enseguida, sin bajar por una lista larga de archivos.',
    ]),
    ('1.93', [
        'Menú Herramientas ordenado en 4 grupos con título: Audio y calidad · Etiquetas y portadas · Organizar la biblioteca · Internet y servidor. Todas las opciones con su icono.',
        'Árboles de carpetas: ahora sí se pueden sombrear varias carpetas arrastrando hacia arriba o abajo (antes se empezaba a arrastrar la carpeta). Arrastrar hacia un lado sigue moviendo la carpeta.',
        'Renombrar carpetas (F2 o clic derecho, en el árbol o en la lista) se hace ahí mismo sobre el nombre, sin ventana. Si estabas dentro de esa carpeta, sigues en ella con su nombre nuevo.',
        'Renombrar canciones en modo iconos: el cuadro tapa todo el nombre viejo (ya no asoma por debajo).',
        'El recuadro de selección al sombrear en la lista tiene el color de acento, más suave y con bordes redondeados.',
    ]),
    ('1.92', [
        'Identificar por sonido: con la clave de AcoustID ya guardada, el cuadro de la clave se oculta y solo queda una línea «🔑 Clave guardada · Cambiar». Nueva cabecera y tabla más clara.',
        'Diseño más pulido en todo el programa: desplegables, casillas y opciones redondas con el color de acento, pestañas tipo «píldora», tablas con filas alternas y sin rejilla, barras de progreso redondeadas, cabeceras en las ventanas de herramientas y barras de desplazamiento más finas.',
        'La portada de la canción elegida ya no se ve teñida de color en la lista.',
        'La selección en los árboles de carpetas se ve como una sola barra (antes salía un trozo suelto a la izquierda).',
        'Los campos de metadatos muestran el principio del texto (antes a veces se veía «.uces de Ciudad» en vez de «Luces de Ciudad»).',
    ]),
    ('1.91', [
        'Arrastrar muchas canciones a una carpeta: ya no se quedan la mayoría sin mover. Si un archivo está «en uso» un instante (miniatura, tonalidad, antivirus), se reintenta hasta 3 segundos; las miniaturas se pausan mientras se mueve, y al final solo quedan marcadas las que de verdad no se pudieron mover (con el motivo).',
        'Sombrear bajando: al llevar el ratón por debajo de la lista, se desplaza rápido (más lejos = más rápido) en vez de ir lento.',
        'Árboles: sombrear varias carpetas ya no abre cada carpeta por la que pasas (se abre al soltar). Arrastrar hacia arriba/abajo desde una carpeta no elegida sombrea; hacia un lado, la arrastra.',
    ]),
    ('1.90', [
        'El analizador de audio fpcalc (para «Identificar por sonido») ya viene incluido en el programa: no hay que descargar nada al usarlo por primera vez.',
    ]),
    ('1.89', [
        'Nuevo (idea de Picard): Herramientas → «Identificar por sonido (AcoustID)». Reconoce las canciones escuchando el audio, aunque se llamen «track01.mp3» y no tengan etiquetas. Muestra los resultados con su porcentaje de seguridad y eliges el correcto. Necesita una clave gratuita de AcoustID (botón «Conseguir clave gratis»); el analizador fpcalc (1,5 MB) se descarga solo la primera vez.',
        'Nuevo (idea de Picard): Herramientas → «Emparejar álbum con MusicBrainz». Busca el álbum, eliges el lanzamiento (fecha, país, formato, sello, nº de pistas) y coloca cada archivo en su pista según título, duración y número. Corrige de una vez título, intérprete, pista, disco, año e intérprete del álbum, pone la portada del Cover Art Archive y guarda los IDs de MusicBrainz.',
        'Los IDs de MusicBrainz y AcoustID se guardan en las etiquetas: Navidrome, Plex, Jellyfin y otros agrupan los álbumes sin errores.',
    ]),
    ('1.88', [
        'Nuevo: Herramientas → «Navidrome (servidor de música)». Conecta con tu Navidrome (dirección, usuario y contraseña; la contraseña no se guarda, solo un código de acceso) y: actualiza la biblioteca al momento (o automáticamente cada vez que guardas), revisa tus carpetas y te dice lo que se verá mal en Navidrome (álbumes partidos, años distintos, sin pista, sin portada o pequeña, discos sin número, géneros generales…) y muestra tus canciones más escuchadas, favoritas y álbumes más escuchados.',
    ]),
    ('1.87', [
        'Renombrar en la lista: el cuadro para escribir ahora es ancho, con borde de color y se ve entero (antes salía pequeño y cortado en el modo iconos). Al abrirse ya tiene el nombre seleccionado.',
        'Modo iconos: los nombres largos se ven en hasta 3 líneas en vez de cortarse con «…» a la primera.',
        'Renombrar ya no falla si el archivo estaba abierto un instante (miniatura o tonalidad): se reintenta solo.',
    ]),
    ('1.86', [
        'Arreglo importante: al eliminar (o mover / renombrar) una carpeta que se veía en el árbol, el programa podía quedarse colgado («No responde»). La vigilancia de carpetas de la 1.83 dejaba la carpeta «en uso» y Windows no podía llevarla a la papelera. Ahora se deja de vigilar antes de tocarla.',
    ]),
    ('1.85', [
        'Los árboles de carpetas ya no saltan hacia abajo al eliminar, mover, arrastrar, crear o renombrar algo: se quedan desplazados donde estaban.',
        'La lista de canciones tampoco vuelve arriba al recargar la misma carpeta (tras borrar, mover o renombrar): se queda en la misma posición.',
    ]),
    ('1.84', [
        'Letra: nuevos botones «🌐 Buscar en musica.com» (abre la letra de la canción en musica.com) y «📋 Pegar letra» (pone lo que copiaste como letra, limpiando espacios y líneas de sobra). También en la ventana que sale cuando no se encuentra la letra.',
    ]),
    ('1.83', [
        'Abrir carpetas con muchas canciones ya no traba el programa: la lista se llena de una vez, las miniaturas se ponen por tandas (antes se repintaba cientos de veces por segundo), la carpeta se lee más rápido y la búsqueda vacía no recorre la lista.',
        'Si ordenas por una columna (artista, álbum, bitrate…) en una carpeta grande que aún no se ha leído, se muestra ya ordenada por nombre y se reordena sola cuando termina de leerse, en vez de congelarse.',
        'Los árboles de carpetas se actualizan solos: al crear, borrar o renombrar carpetas (aquí o desde el Explorador de Windows) aparecen enseguida. La carpeta nueva se abre y queda marcada en el árbol.',
        'La lista de canciones también se actualiza sola si se agregan o quitan canciones de la carpeta desde fuera del programa.',
    ]),
    ('1.82', [
        'Arreglo: con la barrita «Ocultar metadatos» la fila de abajo crecía y en pantallas pequeñas se cortaba la última fila (Directorio y «Rellenar con IA»). Ahora el botón para ocultar es una flechita al lado de las etiquetas técnicas y no ocupa altura.',
    ]),
    ('1.81', [
        'Nuevo: clic derecho en varias canciones → Herramientas → «Crear carpetas por…» (también en el menú Herramientas). Reparte las canciones elegidas en carpetas por intérprete, intérprete principal, álbum, año - álbum, género, año, década, compositor, primera letra o formato, con hasta tres niveles (por ejemplo Género → Intérprete → Álbum). Vista previa en árbol, mover o copiar, elegir dónde crearlas, qué hacer si falta el dato y juntar las carpetas de una sola canción en «Varios». Funciona en segundo plano con barra de progreso, también para miles de canciones.',
        'Vista detalles: al activar una columna con clic derecho en los títulos, ahora aparece de verdad (la lista se ensancha y se desplaza hasta ella).',
    ]),
    ('1.80', [
        'Modo lista y detalles: ahora puedes sombrear varias canciones arrastrando hacia arriba o abajo (como en el Explorador). Para mover archivos, arrastra una canción ya elegida o hacia un lado.',
        'Letras: si la conexión falla, se reintenta solo. Si LRCLIB no la tiene, se busca también en NetEase (sincronizada) y en lyrics.ovh, y se limpia el título («feat.», «Official Video», «Remastered»…) para encontrarla mejor.',
        'Si aun así no aparece, sale una ventana con opciones: Reintentar, Buscar en Google, Cargar archivo .lrc… o Escribirla / pegarla.',
    ]),
    ('1.79', [
        'Más rápido al seleccionar muchas canciones: los datos técnicos (formato, bitrate, frecuencia…) ahora se leen en segundo plano junto con las miniaturas y se guardan en la caché, así no se vuelve a abrir cada archivo al seleccionar.',
        'Si seleccionas muchas canciones que todavía no se han leído, el programa ya no se traba leyéndolas todas: muestra lo que tiene y se completa solo en un momento.',
        'Vista detalles más fluida al desplazarte: ya no se pregunta al disco por cada celda cada vez que se repinta.',
        'Marcar canciones como pendientes/sonando solo toca las que cambian (antes se repintaba la lista entera).',
        'El visualizador de la barra de abajo consume mucho menos (la «pantalla» apagada se dibuja una sola vez) y no trabaja con la ventana minimizada.',
        'Las carpetas con muchas canciones se colocan por partes, sin congelar la ventana.',
    ]),
    ('1.78', [
        'Vista detalles: la fila de títulos de las columnas (Nombre, Título, Intérprete, Álbum, Género, Año…) a veces se quedaba cortada a la mitad al cambiar el tamaño de la lista; ahora ocupa siempre todo el ancho.',
    ]),
    ('1.77', [
        'La barrita ahora oculta SOLO los metadatos: la lista de canciones baja hasta abajo, y la portada y Géneros/Letra se quedan a la derecha como siempre. «Mostrar metadatos» (debajo de la lista) los vuelve a sacar.',
    ]),
    ('1.76', [
        'Los metadatos y la letra se pueden plegar y desplegar con la barrita que tienen encima: al plegarlos, la lista y la portada ocupan todo el espacio. El programa recuerda cómo lo dejaste.',
        'Ajustes → General: «Barrita para plegar y desplegar los metadatos y la letra», para activarla o quitarla cuando quieras.',
    ]),
    ('1.75', [
        'Renombrar una canción (F2 o clic derecho → Renombrar) ahora se hace ahí mismo, sobre el nombre en la lista, como en el Explorador de Windows: escribes y pulsas Enter (Esc cancela). Ya no sale la ventanita.',
    ]),
    ('1.74', [
        'Botones en la miniatura de la barra de tareas: al pasar el ratón por el icono de Music Manager en la barra de Windows aparecen «Anterior», «Reproducir / Pausa» y «Siguiente», como en los reproductores de música.',
        'Solo una ventana del programa: si lo vuelves a abrir estando ya abierto, el anterior se cierra y se abre de nuevo (si tenías cambios sin guardar, te pregunta antes).',
    ]),
    ('1.73', [
        'Rellenar metadatos: cada opción del desplegable dice de dónde salió («Tusa ← iTunes, Deezer», «Reggaeton ← MusicBrainz», «Latin Trap ← IA»). Si varias fuentes dan lo mismo, aparece una vez con todas sus fuentes. Al elegir una, en el campo queda solo el valor.',
    ]),
    ('1.72', [
        'Barra de abajo (estilo celular): el mensaje ya no sale en un recuadro negro con toda la ruta. Ahora es una pastilla discreta con los colores del tema y solo dice la carpeta y cuántas canciones tiene («Armonía 10 · 37 canciones»); si un texto es largo se recorta por el medio.',
    ]),
    ('1.71', [
        '«Rellenar con IA» ahora busca en iTunes, Deezer, MusicBrainz (gratis) y Discogs (si pusiste tu token en Ajustes), además de la IA.',
        'En el resultado, cada campo es un desplegable con las opciones que dio cada fuente (por ejemplo, el álbum según iTunes, Deezer o MusicBrainz): eliges la que prefieras o escribes otra. Los campos con varias opciones se marcan con un borde de color y, al pasar el ratón por cada opción, se ve de qué fuente viene.',
    ]),
    ('1.70', [
        'Corregido: después de arrastrar canciones se quedaba pintado el recuadro morado de selección encima de la lista.',
        'Clic derecho más ordenado: arriba lo de siempre (reproducir, cortar, copiar, pegar, renombrar, eliminar) y el resto agrupado en submenús: Herramientas, el artista, «Al otro árbol» y «Vista y orden».',
        'Iconos más claros: ojo para la vista, flechas para ordenar, etiqueta para géneros, persona para el artista, video para YouTube, libro para Wikipedia, lista con + para añadir a la lista y carpeta con flecha para el Explorador.',
        'Géneros en lote: puedes elegir cualquier carpeta (botón «Elegir carpeta…») y también abrirlo con clic derecho sobre una carpeta o en el árbol.',
    ]),
    ('1.69', [
        'Géneros con varias canciones seleccionadas: «Sugerir género» ya no te saca de la selección; las opciones de todas se juntan (con cuántas canciones la sugieren) y al pulsar una se pone a TODAS las seleccionadas.',
        'Nuevo cuadro «Otro género» debajo de las sugerencias: escribe o elige un género de la lista y pulsa «Poner» para ponérselo a la canción o a todas las seleccionadas, sin necesidad de la IA.',
    ]),
    ('1.68', [
        'Nuevo: Herramientas → «Géneros en lote» (también con clic derecho en canciones). Para la carpeta, la carpeta con subcarpetas o las canciones elegidas: agrupa por álbum, encuentra los géneros demasiado generales («Electronic», «Rock», «Pop»…) o vacíos y sugiere géneros específicos.',
        'Las sugerencias salen primero de MusicBrainz (gratis, géneros votados por la comunidad) y la IA solo rellena lo que falte, de 25 en 25 álbumes por consulta para no gastar el límite gratuito. Lo encontrado se guarda: puedes parar y seguir otro día.',
        'Puedes elegir varias filas y ponerles el mismo género de una vez (con una lista de géneros comunes), escribir uno a mano con doble clic, marcar o desmarcar cada álbum, y luego «Aplicar» (pendiente) o «Aplicar y guardar».',
    ]),
    ('1.67', [
        'Nueva vista «Lista con detalles» (como Mp3tag o el Explorador): columnas con nombre de archivo, título, intérprete, álbum, género, año, pista, duración, tasa de bits, frecuencia, códec, etiqueta y tamaño. Clic en el título de una columna para ordenar (otra vez para invertir); arrastra los bordes para cambiar el ancho y clic derecho en la cabecera para elegir qué columnas se ven.',
        'Botones de vista junto a la ruta: iconos, lista y lista con detalles. También en clic derecho → «Ver como».',
        'Ordenar en cualquier vista: clic derecho → «Ordenar por» (nombre, título, intérprete, álbum, género, año, pista, duración, bitrate, tamaño o fecha), ascendente o descendente. Se recuerda la vista y el orden elegidos.',
    ]),
    ('1.66', [
        'Spotify y Tidal: si tienes el programa instalado, la búsqueda se abre directamente en él; si no, en la página web.',
        'Arrastrar varias canciones: al sombrear varias y arrastrar desde cualquiera de ellas, ahora se mueven todas (antes solo una).',
        'Mientras arrastras archivos, la rueda del ratón desplaza el árbol o la lista que está debajo del cursor, para llegar con calma a la carpeta de destino.',
    ]),
    ('1.65', [
        'Nuevo: clic derecho en la portada → «Mejorar calidad con IA (agrandar)». Usa Real-ESRGAN en tu PC (gratis, sin internet ni claves) para agrandar portadas de baja calidad a 1000–2000 px reconstruyendo la nitidez. Estilos «Anime / ilustración» y «General / foto», vista de antes y después, y se puede usar en todas las canciones seleccionadas. El motor (unos 45 MB) se descarga solo la primera vez.',
    ]),
    ('1.64', [
        'Con dos árboles: el primero se llama «De» (eliges lo que vas a enviar) y el segundo «A» (eliges a dónde va). Abajo se ve «De: … / A: …» con el botón «Enviar» (mueve), «Copiar» y «Invertir» para cambiar el sentido. Con un solo árbol se llama «Carpetas».',
    ]),
    ('1.63', [
        'Árboles escondidos: al abrirlos con la flechita ahora empujan el resto del programa hacia la derecha (ya no se montan encima), y al cerrarlos todo vuelve a ocupar el ancho. La flechita queda en su propio canal del borde izquierdo y recuerda si los dejaste abiertos.',
    ]),
    ('1.62', [
        'Árboles de carpetas plegables: en Ajustes → General → «Árboles de carpetas» elige «Siempre visibles (normal)» o «Escondidas». Escondidas, la lista de canciones gana todo el ancho y las carpetas salen deslizándose con la flechita del borde izquierdo; la misma flechita, pegada al lado del panel, las vuelve a esconder.',
    ]),
    ('1.61', [
        'Pasar entre árboles sin arrastrar (como el explorador de Kodi): con el 2.º árbol visible aparece abajo una barra que dice qué vas a pasar y a dónde («3 canciones ➜ Rock»), con los botones «Copiar al otro árbol» (F7) y «Mover al otro árbol» (F6). Sirve para canciones elegidas en la lista o carpetas elegidas en un árbol; el destino es la carpeta abierta en el otro árbol. Arrastrar sigue funcionando igual.',
        'Clic derecho en canciones: «Mover / Copiar al otro árbol».',
    ]),
    ('1.60', [
        'Estilo celular: la barra de abajo ahora tiene cuadritos a todo lo ancho que bailan al ritmo de la canción (en espejo, con los graves al centro, tapitas que caen despacio y los colores del programa). Los mensajes se siguen leyendo encima.',
    ]),
    ('1.59', [
        'Reproductor celular: al abrir el programa ya no aparece a mitad de la ventana; siempre queda pegado al borde derecho y ocupa todo el alto.',
        'Volumen más suave: la barra sigue una curva de oído, así cada movimiento se siente parejo (antes casi todo el cambio estaba en la parte baja). La barra del reproductor celular salta adonde haces clic.',
        'Al abrir el programa el volumen empieza a la mitad; mientras lo usas se queda donde lo dejes.',
    ]),
    ('1.58', [
        'Reproductor estilo celular: al hacer doble clic en una canción, pulsar «Reproducir» o darle a play, el reproductor grande se despliega solo. Al pasar sola a la siguiente canción no se abre. Se puede desactivar en Ajustes → Reproductor.',
    ]),
    ('1.57', [
        'Datos técnicos de la canción más grandes y ordenados en dos filas fijas que ocupan todo el ancho; si un texto no cabe se recorta con «…» (al pasar el ratón se ve completo), así nada se empuja.',
        'Nuevo dato: Tonalidad (key) de la canción, por ejemplo «Am · 8A» (La menor, con su código Camelot para DJ). Se lee de la etiqueta si la tiene; si no, se calcula analizando el audio (es una estimación).',
        'Nuevo dato: canales (Mono / Estéreo).',
    ]),
    ('1.56', [
        'Reproductor celular: la lista de reproducción ahora se ve dentro del propio reproductor (en lugar de abrir otra ventana encima), con la canción actual resaltada; doble clic para reproducir otra.',
        'Reproductor celular: ya no aparece el botón redondo de la lista (ese es solo del reproductor clásico).',
        'Reproductor celular: la flechita tiene su propio espacio en el borde y ya no tapa nada; con el reproductor abierto se coloca pegada a su lado izquierdo con «›» para ocultarlo.',
    ]),
    ('1.55', [
        'Corregido: en Ajustes salían dos apartados «Reproductor» y la opción del estilo (clásico / celular) no se veía. Ahora hay uno solo con el estilo del reproductor y «Pasar a la siguiente canción al terminar».',
    ]),
    ('1.54', [
        'Ajustes → Reproductor: elige el estilo del reproductor. «Barra de reproducción abajo (clásico)» o «Reproductor estilo celular». Solo se usa uno a la vez: con el estilo celular desaparece la barra de abajo y el reproductor grande se abre desde la flechita del borde derecho.',
    ]),
    ('1.53', [
        'Nuevo reproductor grande «estilo celular»: pulsa la flechita del borde derecho de la ventana y sale deslizándose un reproductor con la portada grande, fondo con los colores de la canción, barra de avance con tiempo restante, botones grandes, aleatorio, repetir (todas / una), volumen y la letra (sincronizada si tiene minutos). El reproductor de abajo sigue igual.',
        'Aleatorio y repetir también funcionan con el reproductor normal y se recuerdan al cerrar el programa.',
        'Se quitó la barra que desplazaba todo el programa hacia arriba y hacia abajo.',
    ]),
    ('1.52', [
        'Debajo de la portada, los botones de YouTube, Spotify, Tidal, Qobuz y Wikipedia se amontonaban y tapaban la etiqueta de la portada. Ahora es un solo botón «Buscar la canción en…» con un menú, y la portada ya no se puede aplastar.',
    ]),
    ('1.51', [
        'Nuevo: Herramientas → «Informe de la biblioteca»: cuántas canciones no tienen portada (o la tienen pequeña), letra, género, año, álbum, artista/título o son de calidad baja. Doble clic en cualquiera para ir a ella y arreglarla.',
        'Nuevo: Herramientas → «Organizar en carpetas»: mueve las canciones a «Artista / Álbum» (u otras estructuras) según sus etiquetas, con vista previa antes de mover y la letra .lrc acompañando a su canción.',
        'Nuevo: Herramientas → «Etiquetas desde el nombre del archivo»: saca artista, título, pista, álbum… de nombres como «Artista - Título.mp3». Elige solo el formato que más archivos reconoce.',
        'Nuevo: Herramientas → «Normalizar volumen»: deja las canciones seleccionadas con el mismo volumen (-14, -16 o -11 LUFS), en copias o reemplazando, conservando etiquetas y portada.',
    ]),
    ('1.50', [
        'Nuevo: Herramientas → «Buscar canciones repetidas». Encuentra duplicados (mismo artista y título, solo título o archivo idéntico), en la carpeta o también en subcarpetas, y deja marcadas las copias de peor calidad para enviarlas a la papelera. La mejor copia de cada grupo nunca se marca.',
        'Portada: la etiqueta con formato y tamaño (JPEG · 1000×1000 px · 190 KB) va centrada justo debajo de la imagen y ya no se monta encima aunque la ventana sea pequeña.',
    ]),
    ('1.49', [
        'El archivo .lrc (copia de la letra sincronizada junto a la canción) ya no se crea por defecto. Quien lo quiera puede activarlo en Ajustes → Etiquetas. La letra sigue guardándose dentro de la canción.',
    ]),
    ('1.48', [
        'Descargas de YouTube / SoundCloud: ya no quedan archivos sueltos sin icono junto al MP3 (el audio original, .part o .ytdl). Se borran solos al terminar o si la descarga falla.',
    ]),
    ('1.47', [
        'Inglés y ruso mucho más completos: ahora se traducen también los textos que cambian mientras usas el programa (letra, análisis del espectrograma, comparación, portadas, fuentes de etiquetas, avisos con nombres y cantidades…).',
        'Si usas la IA sin clave, aparece una guía paso a paso para conseguir gratis una clave de Gemini, con un botón que abre la página de Google y otro para pegarla.',
    ]),
    ('1.46', [
        'Nuevo selector de idioma con banderitas arriba a la derecha: cambia entre Español, English y Русский al instante, sin reiniciar.',
        'Mucho más traducido al inglés y al ruso: ventanas de IA, ajustes de la canción, descargas, espectrograma, portadas, listas de reproducción, avisos, mensajes de la barra de estado, guía rápida y «Acerca de».',
        'Los botones «Sí / No / Aceptar / Cancelar» de los avisos ahora salen en el idioma elegido (antes salían en inglés).',
    ]),
    ('1.45', [
        '«Rellenar con IA» ahora rellena todos los campos: título, intérprete, álbum, intérprete del álbum, compositor, género, año, pista, número de disco y comentario (sello, productor…).',
        'Antes de preguntar a la IA busca la canción en iTunes y Deezer, así el álbum, el año, la pista y el disco salen del catálogo real y no adivinados.',
        'Corregido: la pista y el número de disco a veces no se rellenaban.',
    ]),
    ('1.44', [
        'Se quitó la pantalla de carga del panda: el programa se abre directamente.',
    ]),
    ('1.43', [
        'Más fluido: las portadas de la lista se cargan en segundo plano, así la ventana ya no se traba mientras aparecen.',
        'Las miniaturas se guardan en caché: volver a una carpeta que ya abriste es casi instantáneo.',
        'Para no ocupar espacio, cada hora se borran solas las miniaturas que no se usaron en la última hora.',
    ]),
    ('1.42', [
        'Logo rediseñado con un estilo más profesional: panda con auriculares y ondas de sonido sobre fondo oscuro, en los colores del programa.',
        'La pantalla de carga usa el mismo estilo nuevo.',
    ]),
    ('1.41', [
        'Nuevo logo: un panda con auriculares escuchando música (también en el icono del programa).',
        'Nueva pantalla de carga animada: el panda abre una carpeta y van saliendo canciones volando mientras el programa se prepara.',
    ]),
    ('1.40', [
        'El programa pesa menos: se quitaron archivos que no se usaban (OpenGL por software, visor de PDF de Qt, OpenSSL duplicado, traducciones de Qt y formatos de imagen raros) y el componente de descargas ya no incluye su código fuente suelto.',
    ]),
    ('1.39', [
        'Nuevo botón «Ajustes de la canción» junto al reproductor (también en Herramientas): graves, medios, agudos, volumen, normalizar, tempo, tono, velocidad (tasa), recorte, bucle (repetir), al revés, eco, reverberación, ancho estéreo, mono, quitar la voz y entrada/salida gradual.',
        'Puedes escuchar una muestra de 30 s con los ajustes antes de guardar, y guardarla como canción nueva «(editada)» o reemplazar la original. Se conservan las etiquetas y la portada (MP3, M4A, MP4 y FLAC).',
        'Botones de verdad: los emojis de los botones, menús y del reproductor (guardar, atrás/adelante, actualizar, volumen, IA, buscar, descargar…) se sustituyen por iconos dibujados que siguen el tema y el color del programa.',
    ]),
    ('1.38', [
        'Portadas: además de iTunes y Deezer, ahora también se buscan en SoundCloud (aparecen como opción para elegir).',
        'Herramientas → «Descargar de YouTube / SoundCloud a MP3»: ahora también acepta enlaces de SoundCloud.',
        'Deezer: no se pueden descargar canciones completas (están protegidas con DRM); si pegas un enlace de Deezer el programa te lo explica en vez de fallar.',
    ]),
    ('1.37', [
        'Metadatos más compactos y estables: las etiquetas técnicas son más pequeñas y tienen su sitio reservado (los campos ya no bajan ni suben), y el botón de guardar es solo el icono 💾, pegado a la derecha.',
        'La rueda del ratón ya no desplaza toda la ventana.',
        'La ventana de cambios sin guardar ahora pregunta solo «¿Desea guardar los cambios?» con Sí / No.',
    ]),
    ('1.36', [
        'Metadatos: ahora son los mismos que ves en las propiedades de Windows: Título, Intérprete, Álbum, Intérprete del álbum, Compositor, Género, Año, Pista, Número de disco y Comentario, más el Directorio (solo lectura). Se quitó BPM.',
    ]),
    ('1.35', [
        'Datos técnicos: ahora también se ve la etiqueta que usa el archivo (ID3v2.3, ID3v2.4, Vorbis Comment, MP4…) y el codec con detalle (por ejemplo «MPEG-1 Layer III · LAME 3.100» o «AAC-LC»).',
    ]),
    ('1.34', [
        'Nuevo botón «✨ Rellenar metadatos con IA…» debajo de los metadatos: pide el nombre de la canción y el artista, la IA busca los datos (álbum, género, año, pista…) y los rellena. Antes de aplicar puedes revisarlos y corregirlos.',
    ]),
    ('1.33', [
        'Portada: la etiqueta con formato y tamaño (JPEG · 600×600 px · 93 KB) ya no se pega ni tapa la imagen; tiene su propio espacio debajo.',
        'Vuelve «Herramientas → Descargar de YouTube a MP3» (se había quitado por error en la 1.29).',
        'Árboles de carpetas: al mover archivos o carpetas ya no se abre solo el 2.º árbol ni aparece la fila «…»; cada árbol conserva exactamente lo que tenías abierto.',
    ]),
    ('1.32', [
        'En «Acerca de» ahora aparece el creador: PandxMax.',
    ]),
    ('1.31', [
        'Metadatos: las etiquetas técnicas (formato, bitrate, frecuencia, duración, modo, tamaño) se ven siempre, también sin canción seleccionada, así nada salta de sitio.',
        'El botón «Guardar» ahora está en la cabecera de los metadatos (arriba a la derecha) y solo se activa cuando hay cambios.',
    ]),
    ('1.30', [
        'Metadatos: los campos quedan pegados a las etiquetas técnicas (sin hueco en medio); el espacio sobrante queda abajo.',
        'El botón «Guardar» ahora está al costado derecho de la portada (aparece solo cuando hay cambios).',
    ]),
    ('1.29', [
        'Se quitó «Reparar portadas»: ahora basta con guardar. Cada vez que guardas un MP3 queda en el formato que el Explorador de Windows entiende.',
        'Las portadas en FLAC se guardan con sus medidas (ancho, alto y profundidad) para que Windows las muestre como miniatura.',
    ]),
    ('1.28', [
        'Arreglo importante: los MP3 ahora se guardan en ID3v2.3 con texto UTF-16 (el formato que entiende el Explorador de Windows). Antes la portada se guardaba bien, pero Windows no la mostraba como miniatura.',
    ]),
    ('1.27', [
        'Nuevo botón ⟳ «Actualizar» junto a atrás/adelante/subir, y clic derecho en el espacio en blanco → «Actualizar» (también F5), para que aparezcan las canciones que añades desde fuera.',
        'Herramientas → «Descargar de YouTube a MP3»: pega el enlace, descarga el audio y se selecciona en la lista para ponerle metadatos y portada.',
    ]),
    ('1.26', [
        'Se quitaron los botones «Deshacer cambios» y «Guardar cambios» de los metadatos.',
        'Cuando hay un cambio en el archivo aparece un botón «Guardar» encima de la portada (y desaparece al guardar).',
        'Si cambias a otra canción (o carpeta) con cambios sin guardar, sale una ventana para guardar, descartar o quedarte.',
    ]),
    ('1.25', [
        'Al guardar, el programa avisa al Explorador de Windows para que refresque el icono y muestre la portada del archivo.',
        'Los archivos .mp4 de solo audio no muestran portada en Windows: al guardar una portada, el programa ofrece renombrarlos a .m4a (es el mismo archivo y así Windows sí muestra la imagen).',
    ]),
    ('1.24', [
        'El programa abre más rápido: aparece una pantalla de carga al instante y lo pesado (reproductor, comprobar actualizaciones, guía) se carga después de mostrar la ventana.',
        'El ejecutable es más ligero (se quitaron módulos que no se usan), así que arranca antes.',
    ]),
    ('1.23', [
        'Comparación: ahora puedes arrastrar canciones o carpetas de cualquier lugar (del explorador de Windows o de las listas del programa) para añadirlas y compararlas.',
        'Debajo de la portada hay botones para buscar la canción en YouTube, Spotify, Tidal, Qobuz y Wikipedia.',
    ]),
    ('1.22', [
        'Al arrastrar archivos o carpetas ya no aparece el signo de «prohibido», y la carpeta que tienes debajo se resalta para soltar encima.',
    ]),
    ('1.21', [
        'La división entre la lista y la portada (y entre metadatos y géneros) ya no se puede mover: se queda quieta.',
        'Con los metadatos a la vista, la fila de abajo tiene siempre el mismo tamaño y posición; al cerrar el espectrograma vuelve exactamente al mismo sitio.',
        'Sin canción seleccionada, los campos de metadatos aparecen vacíos con una sola línea «-» y se rellenan al elegir una canción.',
    ]),
    ('1.20', [
        'Con los metadatos a la vista, la barra roja para estirar la fila de abajo ya no aparece (solo se puede estirar con el espectrograma abierto).',
        'Corregido: ahora sí se puede arrastrar un archivo o carpeta sobre otra carpeta de la misma lista; la carpeta de destino se resalta al pasar por encima.',
    ]),
    ('1.19', [
        'Corregido: tras arrastrar archivos y soltarlos en el mismo sitio, ya no queda el recuadro de selección fantasma ni la selección «pegada».',
        'Corregido: se puede soltar carpetas y archivos sobre otra carpeta dentro de la misma lista.',
        'Corregido: la pestaña Comparación del espectrograma ahora se desplaza y se puede ver completa, aunque la ventana sea pequeña.',
    ]),
    ('1.18', [
        'El espectrograma ocupa toda la fila de abajo (también bajo la portada) y la portada se queda arriba a la derecha, sin estirarse.',
        'Ctrl + rueda del ratón sobre los archivos cambia su tamaño, de grandes a pequeños (en vista de iconos y de lista).',
    ]),
    ('1.17', [
        'Los botones Espectro, MusicBrainz y Discogs pasaron a la derecha de la barra de la lista.',
        'Los botones del reproductor (lista, anterior, siguiente y detener) ahora están dibujados con el color del programa y cambian junto con el botón de reproducir.',
    ]),
    ('1.16', [
        'Los botones Espectro, MusicBrainz y Discogs ahora están arriba, a la izquierda, junto a las flechas de navegación; ya no ocupan lugar en los metadatos.',
    ]),
    ('1.15', [
        'Datos técnicos más ordenados: las etiquetas a la izquierda y los botones Espectro / MusicBrainz / Discogs siempre juntos a la derecha.',
        'Panel de portada más compacto: botones más pequeños, menos espacio vacío y la columna derecha un poco más angosta.',
    ]),
    ('1.14', [
        'Corregido: la ventana ya no se sale de la pantalla ni se corta por los lados (se ajusta al tamaño de tu pantalla al abrir).',
        'La fila de datos técnicos y los botones (Espectro, MusicBrainz, Discogs) pasa a otra línea cuando no cabe, en vez de ensanchar la ventana.',
        'Si aun así la ventana es muy pequeña, aparecen barras de desplazamiento en lugar de cortar el contenido.',
    ]),
    ('1.13', [
        'Junto a «📊 Espectro» hay ahora dos botones, «🎼 MusicBrainz» y «💿 Discogs», para buscar y poner las etiquetas de la canción.',
    ]),
    ('1.12', [
        'Al actualizar, aparece una pantallita con las novedades de la versión (Ayuda ▸ «Novedades de esta versión» para verla cuando quieras).',
    ]),
    ('1.11', [
        'Actualización automática más robusta: descomprime antes de cerrar, cierra el proceso por completo, reintenta si hay archivos en uso y avisa al abrir si salió bien o mal.',
    ]),
    ('1.10', [
        'Clic derecho en el artista: ahora también «Buscar en Tidal» y «Buscar en Qobuz».',
    ]),
    ('1.09', [
        'Volumen: la barra aparece hacia arriba, flotando (no mueve nada).',
        'Botón flotante ☰ al costado: despliega por encima de portada, géneros y letra la lista de reproducción; arriba muestra lo que suena ahora, y puedes arrastrar canciones y crear/guardar listas con nombre.',
        'Cuadritos de fondo en la barra de posición que bailan con el ritmo real de la canción y caen al detenerla.',
    ]),
    ('1.08', [
        'Actualización desde el propio programa: Ayuda ▸ «Buscar actualizaciones…» descarga la versión nueva y se reemplaza sola (también avisa al abrir).',
    ]),
    ('1.07', [
        '✨ Portada automática: muestra varias opciones (iTunes y Deezer) para elegir; Google Imágenes solo si no hay ninguna.',
        'Volumen en una sola barrita que se despliega al pasar el ratón, y un disco que gira con la portada que suena.',
        'Metadatos: solo «Deshacer cambios» y «Guardar cambios»; se quitó la palabra «Portada» sobre la imagen.',
        'Lista de reproducción propia: arrastra canciones o carpetas, ordénalas, guárdala o cárgala (.m3u8). «Reproducir carpeta» con clic derecho. Canciones separadas y legibles.',
        'El espectrograma aparece solo en el panel de abajo (no agranda la ventana).',
    ]),
    ('1.06', [
        'El espectrograma, la comparación y el análisis de calidad ahora reemplazan a los metadatos y la letra en la misma ventana; un botón «Volver» los recupera.',
        'Reproductor: botones de lista de reproducción, anterior, siguiente y detener junto a reproducir.',
        'Los colores del programa se adaptan a la portada de la canción que suena (se puede desactivar en Ver).',
        'Si no se encuentra una portada, se abre Google Imágenes con «artista título portada» y el programa ofrece ponerla al copiar la imagen.',
    ]),
    ('1.05', [
        'Botón ✨ de portada automática: busca en iTunes y Deezer la portada en alta calidad (hasta 1200 px) y la pone sola en las canciones seleccionadas.',
    ]),
    ('1.04', [
        'Géneros y Letra comparten el panel derecho con dos botones: se acabó el desbordamiento lateral de la ventana.',
    ]),
    ('1.03', [
        'El panel de carpetas ya no se puede aplastar al abrir la letra.',
        'LRCLIB: reintentos automáticos si el servicio está saturado (error 503).',
        'Panel de portada más cuidado: esquinas redondeadas, sombra y botones con iconos.',
        'Botón «📊 Espectro» junto a los datos técnicos de la canción.',
    ]),
    ('1.02', [
        'Letras sincronizadas desde LRCLIB (con los minutos de cada línea y archivo .lrc); se quitó la letra con IA.',
        'Botones de portada (cambiar, guardar, quitar, ver) y datos de la imagen.',
        'Se quitaron títulos y textos repetidos del panel de metadatos y de la portada.',
    ]),
    ('1.01', [
        'Menús en lugar de barra de herramientas; reproductor compacto en la línea de estado.',
        'Botones atrás / adelante / subir para navegar por las carpetas.',
        'Árboles de carpetas con barra horizontal, destino resaltado y copiar con Ctrl.',
        'Espectrograma y análisis de calidad (comparación de varias canciones).',
        'Convertir formatos: MP3, FLAC, M4A, OGG, Opus y WAV.',
        'Fuentes de etiquetas: MusicBrainz y Discogs.',
        'Información técnica del archivo (códec, tasa de bits, frecuencia…).',
        'Clic derecho en el artista: Wikipedia, YouTube, Spotify, Tidal y Qobuz.',
        'Ajustes con categorías, tema y color de acento, y 3 idiomas (ES / EN / RU).',
        'Volumen: silenciar, rueda del ratón y globos con el minuto y el volumen.',
    ]),
    ('1.0', [
        'Explorador con arrastrar y soltar entre dos árboles.',
        'Editor de etiquetas, portadas (copiar, pegar, redimensionar) y letras.',
        'IA (Claude, ChatGPT, Gemini) para géneros y letras.',
        'Reproductor integrado y búsqueda en YouTube.',
    ]),
]

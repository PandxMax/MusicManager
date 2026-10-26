package com.pandxmax.musicmanager

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.net.URLEncoder

private sealed class EDlg {
    object AiFill : EDlg()
    object Genres : EDlg()
    object MusicBrainz : EDlg()
    object Discogs : EDlg()
    object CoverSearch : EDlg()
    object CoverView : EDlg()
}

fun openUrl(ctx: android.content.Context, url: String) {
    try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Exception) {
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun EditorScreen(paths: List<String>) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val files = remember(paths) { paths.map { File(it) } }
    val values = remember { mutableStateMapOf<String, String>() }
    val multi = remember { mutableStateMapOf<String, Boolean>() }
    val edited = remember { mutableStateListOf<String>() }
    var tech by remember { mutableStateOf<Tech?>(null) }
    var lyrics by remember { mutableStateOf("") }
    var lyricsEdited by remember { mutableStateOf(false) }
    var coverBytes by remember { mutableStateOf<ByteArray?>(null) }
    var pendingCover by remember { mutableStateOf<ByteArray?>(null) }
    var coverRemoved by remember { mutableStateOf(false) }
    var dlg by remember { mutableStateOf<EDlg?>(null) }
    var msg by remember { mutableStateOf<String?>(null) }
    var askBack by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var lyrBusy by remember { mutableStateOf(false) }

    LaunchedEffect(files) {
        withContext(Dispatchers.IO) {
            val reads = files.map { Tags.read(it) }
            for ((id, _) in FIELDS) {
                val vs = reads.map { it[id] ?: "" }.toSet()
                values[id] = if (vs.size == 1) vs.first() else ""
                multi[id] = vs.size > 1
            }
            if (files.size == 1) {
                tech = Tags.tech(files[0])
                lyrics = Tags.lyrics(files[0])
            }
            val p = files[0].absolutePath
            coverBytes = Covers.embedded(p) ?: files[0].parentFile?.let { Covers.folderImage(it) }?.readBytes()
        }
    }

    val dirty = edited.isNotEmpty() || pendingCover != null || coverRemoved || lyricsEdited
    val shownBytes: ByteArray? = if (coverRemoved) null else (pendingCover ?: coverBytes)
    val bmp by produceState<Bitmap?>(null, shownBytes) {
        value = withContext(Dispatchers.IO) { shownBytes?.let { Covers.decode(it, 900) } }
    }
    val coverInfo by produceState("", shownBytes) {
        value = withContext(Dispatchers.IO) {
            val b = shownBytes
            if (b == null) "" else {
                val o = BitmapFactory.Options()
                o.inJustDecodeBounds = true
                BitmapFactory.decodeByteArray(b, 0, b.size, o)
                val kind = if (b.size > 4 && b[1] == 'P'.code.toByte()) "PNG" else "JPEG"
                "$kind · ${o.outWidth}×${o.outHeight} px · ${b.size / 1024} KB" + if (pendingCover != null) " · pendiente" else ""
            }
        }
    }

    fun markEdited(id: String) { if (id !in edited) edited.add(id) }
    fun applyVals(m: Map<String, String>) {
        for ((k, v) in m) if (v.isNotBlank() && FIELDS.any { it.first == k }) { values[k] = v; markEdited(k) }
    }

    fun save(after: () -> Unit = {}) {
        if (busy) return
        busy = true
        val vals = edited.associateWith { values[it] ?: "" }
        val pc = pendingCover
        val rc = coverRemoved
        val ly = if (lyricsEdited && files.size == 1) lyrics else null
        scope.launch {
            val errs = withContext(Dispatchers.IO) {
                val e = ArrayList<String>()
                for (f in files) {
                    try { Tags.write(f, vals, pc, rc, ly) } catch (t: Throwable) { e.add("${f.name}: ${t.message ?: t.javaClass.simpleName}") }
                }
                e
            }
            busy = false
            if (errs.isEmpty()) {
                if (pc != null) coverBytes = pc
                if (rc) coverBytes = null
                edited.clear(); pendingCover = null; coverRemoved = false; lyricsEdited = false
                Covers.forget("")
                Store.coverVersion++
                Store.libVersion++
                if (files.size == 1) tech = withContext(Dispatchers.IO) { Tags.tech(files[0]) }
                msg = "${files.size} archivo(s) guardado(s)"
                after()
            } else {
                msg = errs.first()
            }
        }
    }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) scope.launch {
            val b = withContext(Dispatchers.IO) {
                try {
                    ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() }?.let { Covers.prepare(it, Store.coverMax) }
                } catch (_: Throwable) { null }
            }
            if (b != null) { pendingCover = b; coverRemoved = false } else msg = "No se pudo leer esa imagen"
        }
    }

    BackHandler(enabled = true) { if (dirty) askBack = true else Nav.pop() }

    val title = if (files.size == 1) files[0].nameWithoutExtension else "${files.size} canciones"
    val artist = values["artist"] ?: ""
    val songTitle = values["title"] ?: ""

    Column(Modifier.fillMaxSize()) {
        Bar(title, { if (dirty) askBack = true else Nav.pop() }) {
            IconBtn("💾", enabled = dirty && !busy, accent = true) { save() }
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 14.dp)) {
            Row(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    IconBtn("🖼") { picker.launch("image/*") }
                    IconBtn("✨") { dlg = EDlg.CoverSearch }
                    IconBtn("💾", enabled = shownBytes != null) {
                        val b = shownBytes
                        if (b != null) {
                            scope.launch {
                                val ok = withContext(Dispatchers.IO) {
                                    try { File(files[0].parentFile, "cover.jpg").writeBytes(b); true } catch (_: Throwable) { false }
                                }
                                msg = if (ok) "Guardada como cover.jpg en la carpeta" else "No se pudo guardar la imagen"
                                Store.libVersion++
                            }
                        }
                    }
                    IconBtn("🗑", enabled = shownBytes != null) { coverRemoved = true; pendingCover = null }
                    IconBtn("🔍", enabled = bmp != null) { dlg = EDlg.CoverView }
                }
                Spacer(Modifier.width(12.dp))
                Box(
                    Modifier.size(200.dp).clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
                    contentAlignment = Alignment.Center
                ) {
                    val b = bmp
                    if (b != null) Image(b.asImageBitmap(), null, Modifier.fillMaxSize(), contentScale = ContentScale.Crop)
                    else Text(if (files.size > 1) "Varias canciones" else "Sin portada", color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (coverInfo.isNotEmpty()) {
                Box(Modifier.fillMaxWidth().padding(top = 6.dp), contentAlignment = Alignment.Center) { Chip(coverInfo) }
            }

            FlowRow(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                val q = (artist + " " + songTitle).trim().ifBlank { files[0].nameWithoutExtension }
                fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
                TextButton(onClick = { openUrl(ctx, "https://www.youtube.com/results?search_query=" + enc(q)) }) { Text("▶ YouTube") }
                TextButton(onClick = { openUrl(ctx, "https://open.spotify.com/search/" + enc(q)) }) { Text("🟢 Spotify") }
                TextButton(onClick = { openUrl(ctx, "https://tidal.com/search?q=" + enc(q)) }) { Text("🌊 Tidal") }
                TextButton(onClick = { openUrl(ctx, "https://www.qobuz.com/search?q=" + enc(q)) }) { Text("🎧 Qobuz") }
                TextButton(onClick = { openUrl(ctx, "https://es.wikipedia.org/wiki/Special:Search?go=Go&search=" + enc(artist.ifBlank { q })) }) { Text("📖 Wikipedia") }
            }

            tech?.let { t ->
                FlowRow(Modifier.fillMaxWidth().padding(vertical = 6.dp), horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    Chip("🎵 ${t.codec}"); Chip("🧩 ${t.enc}"); Chip("🏷 ${t.tag}"); Chip("⚡ ${t.bitrate}")
                    Chip("🔊 ${t.freq}"); Chip("⏱ ${t.dur}"); Chip("⚙ ${t.mode}"); Chip("💾 ${t.size}")
                }
            }

            Spacer(Modifier.height(4.dp))
            for ((id, label) in FIELDS) {
                OutlinedTextField(
                    value = values[id] ?: "",
                    onValueChange = { values[id] = it; markEdited(id) },
                    label = { Text(label) },
                    placeholder = { if (multi[id] == true) Text("‹varios valores›") },
                    singleLine = true,
                    keyboardOptions = if (id == "date" || id == "track" || id == "disc") KeyboardOptions(keyboardType = KeyboardType.Number) else KeyboardOptions.Default,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)
                )
            }
            OutlinedTextField(
                value = files.map { it.parent ?: "" }.toSet().let { if (it.size == 1) it.first() else "‹varios›" },
                onValueChange = {}, readOnly = true, singleLine = true, label = { Text("Directorio") },
                modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)
            )

            FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Button(onClick = { dlg = EDlg.AiFill }) { Text("✨ Rellenar con IA") }
                OutlinedButton(onClick = { dlg = EDlg.Genres }) { Text("🎼 Géneros con IA") }
                OutlinedButton(onClick = { dlg = EDlg.MusicBrainz }) { Text("MusicBrainz") }
                OutlinedButton(onClick = { dlg = EDlg.Discogs }) { Text("Discogs") }
            }

            if (files.size == 1) {
                Text("Letra", Modifier.padding(top = 16.dp, bottom = 4.dp), fontWeight = androidx.compose.ui.text.font.FontWeight.SemiBold)
                OutlinedTextField(
                    value = lyrics, onValueChange = { lyrics = it; lyricsEdited = true },
                    minLines = 6, maxLines = 14, modifier = Modifier.fillMaxWidth()
                )
                OutlinedButton(
                    enabled = !lyrBusy, modifier = Modifier.padding(top = 6.dp),
                    onClick = {
                        lyrBusy = true
                        scope.launch {
                            val secs = tech?.dur?.split(":")?.let { if (it.size == 2) (it[0].toIntOrNull() ?: 0) * 60 + (it[1].toIntOrNull() ?: 0) else 0 } ?: 0
                            val r = withContext(Dispatchers.IO) {
                                Sources.lrclib(artist.ifBlank { "" }, songTitle.ifBlank { files[0].nameWithoutExtension }, values["album"] ?: "", secs)
                            }
                            lyrBusy = false
                            if (r != null) { lyrics = r; lyricsEdited = true; msg = "Letra encontrada (pendiente de guardar)" } else msg = "No encontré la letra en LRCLIB"
                        }
                    }
                ) { Text(if (lyrBusy) "Buscando…" else "🔎 Buscar letra en LRCLIB (sincronizada)") }
            }
            Spacer(Modifier.height(24.dp))
        }
        msg?.let { m ->
            Snackbar(Modifier.padding(12.dp), action = { TextButton(onClick = { msg = null }) { Text("OK") } }) { Text(m) }
        }
    }

    if (askBack) {
        AlertDialog(
            onDismissRequest = { askBack = false },
            title = { Text("Cambios sin guardar") },
            text = { Text("¿Desea guardar los cambios?") },
            confirmButton = { TextButton(onClick = { askBack = false; save { Nav.pop() } }) { Text("Sí") } },
            dismissButton = { TextButton(onClick = { askBack = false; Nav.pop() }) { Text("No") } }
        )
    }

    val firstName = files[0].nameWithoutExtension
    val guessTitle = songTitle.ifBlank { if (" - " in firstName) firstName.split(" - ", limit = 2)[1] else firstName }
    val guessArtist = artist.ifBlank { if (" - " in firstName) firstName.split(" - ", limit = 2)[0] else "" }

    when (dlg) {
        is EDlg.AiFill -> AiFillDialog(guessTitle, guessArtist, { applyVals(it); dlg = null }, { dlg = null })
        is EDlg.Genres -> GenresDialog(guessTitle, guessArtist, values["album"] ?: "", { g -> values["genre"] = g; markEdited("genre"); dlg = null }, { dlg = null })
        is EDlg.MusicBrainz -> CandidatesDialog("MusicBrainz", guessArtist, guessTitle, { applyVals(it); dlg = null }, { dlg = null })
        is EDlg.Discogs -> CandidatesDialog("Discogs", guessArtist, guessTitle, { applyVals(it); dlg = null }, { dlg = null })
        is EDlg.CoverSearch -> CoverSearchDialog(guessArtist, guessTitle, { b -> pendingCover = b; coverRemoved = false; dlg = null }, { dlg = null })
        is EDlg.CoverView -> {
            val b = bmp
            AlertDialog(
                onDismissRequest = { dlg = null }, confirmButton = { TextButton(onClick = { dlg = null }) { Text("Cerrar") } },
                text = { if (b != null) Image(b.asImageBitmap(), null, Modifier.fillMaxWidth(), contentScale = ContentScale.Fit) }
            )
        }
        null -> {}
    }
}

@Composable
private fun AiFillDialog(initTitle: String, initArtist: String, onApply: (Map<String, String>) -> Unit, onDismiss: () -> Unit) {
    val scope = rememberCoroutineScope()
    var t by remember { mutableStateOf(initTitle) }
    var a by remember { mutableStateOf(initArtist) }
    val res = remember { mutableStateMapOf<String, String>() }
    var status by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var found by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("✨ Rellenar con IA") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text("Escribe la canción y el artista. La IA buscará los datos; revísalos antes de aplicar (puede equivocarse).", fontSize = 12.sp)
                OutlinedTextField(t, { t = it }, label = { Text("Canción") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                OutlinedTextField(a, { a = it }, label = { Text("Artista") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                Button(enabled = !loading && t.isNotBlank(), modifier = Modifier.padding(top = 8.dp), onClick = {
                    loading = true
                    status = "Buscando con la IA…"
                    scope.launch {
                        try {
                            val r = withContext(Dispatchers.IO) { Ai.fillMetadata(t, a) }
                            res.clear(); res.putAll(r)
                            found = r.isNotEmpty()
                            status = if (found) "Revisa los datos y pulsa Aplicar." else "La IA no encontró datos fiables."
                        } catch (e: Throwable) {
                            status = "No se pudo: ${e.message}"
                        }
                        loading = false
                    }
                }) { Text("🔎 Buscar con IA") }
                if (status.isNotEmpty()) Text(status, Modifier.padding(top = 6.dp), fontSize = 12.sp)
                if (found) for ((id, label) in FIELDS) {
                    OutlinedTextField(res[id] ?: "", { res[id] = it }, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 6.dp))
                }
            }
        },
        confirmButton = { TextButton(enabled = found, onClick = { onApply(res.filterValues { it.isNotBlank() }) }) { Text("Aplicar") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cerrar") } }
    )
}

@Composable
private fun GenresDialog(title: String, artist: String, album: String, onPick: (String) -> Unit, onDismiss: () -> Unit) {
    var items by remember { mutableStateOf<List<String>?>(null) }
    var err by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        try { items = withContext(Dispatchers.IO) { Ai.suggestGenres(title, artist, album) } } catch (e: Throwable) { err = e.message ?: "Error"; items = emptyList() }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("🎼 Géneros sugeridos") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (items == null) Text("Consultando a la IA…")
                else if (items!!.isEmpty()) Text(if (err.isNotEmpty()) "No se pudo: $err" else "Sin sugerencias.")
                else for (g in items!!) TextButton(onClick = { onPick(g) }, modifier = Modifier.fillMaxWidth()) { Text(g, textAlign = TextAlign.Start, modifier = Modifier.fillMaxWidth()) }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Cerrar") } }
    )
}

@Composable
private fun CandidatesDialog(source: String, artist: String, title: String, onPick: (Map<String, String>) -> Unit, onDismiss: () -> Unit) {
    var items by remember { mutableStateOf<List<MetaCandidate>?>(null) }
    var err by remember { mutableStateOf("") }
    LaunchedEffect(Unit) {
        try {
            items = withContext(Dispatchers.IO) { if (source == "Discogs") Sources.discogs(artist, title) else Sources.musicBrainz(artist, title) }
        } catch (e: Throwable) { err = e.message ?: "Error"; items = emptyList() }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Resultados de $source") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (items == null) Text("Buscando…")
                else if (items!!.isEmpty()) Text(if (err.isNotEmpty()) "No se pudo: $err" else "Sin resultados.")
                else for (c in items!!) {
                    Text(c.label, Modifier.fillMaxWidth().clickable { onPick(c.values) }.padding(vertical = 10.dp), fontSize = 13.sp)
                    HorizontalDivider()
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Cerrar") } }
    )
}

@Composable
private fun CoverSearchDialog(artist: String, title: String, onPick: (ByteArray) -> Unit, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<CoverCandidate>?>(null) }
    var busy by remember { mutableStateOf(false) }
    var err by remember { mutableStateOf("") }
    LaunchedEffect(Unit) { items = withContext(Dispatchers.IO) { Covers.search(artist, title) } }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("✨ Portadas encontradas") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (items == null) Text("Buscando en iTunes y Deezer…")
                else if (items!!.isEmpty()) {
                    Text("No encontré portadas en iTunes ni Deezer. Puedes buscarla en Google Imágenes, guardarla en el teléfono y elegirla con el botón 🖼.")
                    Button(onClick = { openUrl(ctx, "https://www.google.com/search?tbm=isch&q=" + URLEncoder.encode("$artist $title portada", "UTF-8")) }, modifier = Modifier.padding(top = 8.dp)) {
                        Text("Abrir Google Imágenes")
                    }
                } else {
                    if (busy) Text("Descargando…")
                    if (err.isNotEmpty()) Text(err, fontSize = 12.sp)
                    for (c in items!!) {
                        Row(
                            Modifier.fillMaxWidth().clickable(enabled = !busy) {
                                busy = true
                                scope.launch {
                                    val b = withContext(Dispatchers.IO) {
                                        try { Net.getBytes(c.url)?.let { Covers.prepare(it, Store.coverMax) } } catch (_: Throwable) { null }
                                    }
                                    busy = false
                                    if (b != null) onPick(b) else err = "No se pudo descargar esa imagen"
                                }
                            }.padding(vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            AsyncImage(model = c.thumb, contentDescription = null, modifier = Modifier.size(64.dp).clip(RoundedCornerShape(8.dp)), contentScale = ContentScale.Crop)
                            Text(c.label, Modifier.padding(start = 10.dp), fontSize = 12.sp)
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Cerrar") } }
    )
}

package com.pandxmax.musicmanager

import android.content.ClipboardManager
import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import java.io.File

private fun fmt(ms: Long): String {
    val s = (ms / 1000).toInt()
    return "${s / 60}:${(s % 60).toString().padStart(2, '0')}"
}

// ------------------------------------------------------------------ Reproductor
@Composable
fun PlayerScreen() {
    val cur = PlayerManager.currentPath
    var showSave by remember { mutableStateOf(false) }
    var showLists by remember { mutableStateOf(false) }
    var drag by remember { mutableStateOf<Float?>(null) }
    val dur = PlayerManager.duration.toFloat().coerceAtLeast(1f)
    val pos = (drag ?: PlayerManager.position.toFloat()).coerceIn(0f, dur)

    Column(Modifier.fillMaxSize()) {
        Bar("Reproduciendo", { Nav.pop() }) {
            IconBtn("📚") { showLists = true }
            IconBtn("💾", enabled = PlayerManager.queue.isNotEmpty()) { showSave = true }
            IconBtn("✏", enabled = cur != null) { cur?.let { Nav.push(Screen.Editor(listOf(it))) } }
        }
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            if (cur != null) {
                CoverThumb(cur, 700, Modifier.fillMaxWidth(0.62f).aspectRatio(1f).clip(RoundedCornerShape(18.dp)))
                Text(
                    File(cur).nameWithoutExtension, Modifier.padding(top = 10.dp), fontSize = 17.sp, fontWeight = FontWeight.SemiBold,
                    maxLines = 2, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center
                )
            } else {
                Text("Nada en reproducción", Modifier.padding(30.dp))
            }
            Slider(
                value = pos, onValueChange = { drag = it },
                onValueChangeFinished = { drag?.let { PlayerManager.seek(it.toLong()) }; drag = null },
                valueRange = 0f..dur
            )
            Row(Modifier.fillMaxWidth()) {
                Text(fmt(pos.toLong()), fontSize = 12.sp)
                Spacer(Modifier.weight(1f))
                Text(fmt(PlayerManager.duration), fontSize = 12.sp)
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                IconBtn("🔀", accent = PlayerManager.shuffle) { PlayerManager.toggleShuffle() }
                IconBtn("⏮", accent = true) { PlayerManager.prev() }
                IconBtn(if (PlayerManager.isPlaying) "⏸" else "▶", accent = true) { PlayerManager.toggle() }
                IconBtn("⏹", accent = true) { PlayerManager.stop() }
                IconBtn("⏭", accent = true) { PlayerManager.next() }
                IconBtn(if (PlayerManager.repeat == 2) "🔂" else "🔁", accent = PlayerManager.repeat != 0) { PlayerManager.cycleRepeat() }
            }
        }
        Text(
            "Cola (${PlayerManager.queue.size})", Modifier.padding(horizontal = 16.dp, vertical = 4.dp), fontWeight = FontWeight.SemiBold
        )
        LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
            itemsIndexed(PlayerManager.queue) { i, p ->
                val isCur = p == cur
                Row(
                    Modifier.fillMaxWidth()
                        .background(if (isCur) MaterialTheme.colorScheme.primary.copy(alpha = 0.25f) else Color.Transparent)
                        .clickable { PlayerManager.playIndex(i) }.padding(horizontal = 12.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    CoverThumb(p, 96, Modifier.size(40.dp).clip(RoundedCornerShape(6.dp)))
                    Text(File(p).nameWithoutExtension, Modifier.weight(1f).padding(horizontal = 10.dp), maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 14.sp)
                    IconBtn("✕") { PlayerManager.removeAt(i) }
                }
            }
        }
    }

    if (showSave) TextPrompt("Guardar lista", "Nombre de la lista", "", { showSave = false }) { name ->
        Store.saveList(name, PlayerManager.queue)
        showSave = false
    }
    if (showLists) {
        var tick by remember { mutableIntStateOf(0) }
        val lists = remember(tick) { Store.lists() }
        AlertDialog(
            onDismissRequest = { showLists = false },
            title = { Text("📚 Listas guardadas") },
            text = {
                Column(Modifier.verticalScroll(rememberScrollState())) {
                    if (lists.isEmpty()) Text("Aún no guardaste ninguna lista. Usa 💾 para guardar la cola actual.")
                    for ((name, paths) in lists) {
                        Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("$name (${paths.size})", Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                            IconBtn("▶") { PlayerManager.playList(paths.filter { File(it).exists() }, 0); showLists = false }
                            IconBtn("➕") { PlayerManager.enqueue(paths.filter { File(it).exists() }); showLists = false }
                            IconBtn("🗑") { Store.deleteList(name); tick++ }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { showLists = false }) { Text("Cerrar") } }
        )
    }
}

// ------------------------------------------------------------------ Espectrograma y comparación
private val CURVE_COLORS = listOf(
    Color(0xFFE74C3C), Color(0xFF3498DB), Color(0xFF2ECC71), Color(0xFFF1C40F), Color(0xFF9B59B6), Color(0xFF1ABC9C), Color(0xFFE67E22), Color(0xFFEC407A)
)

private fun levelColor(l: Int) = when (l) { 0 -> Color(0xFF2ECC71); 1 -> Color(0xFFF39C12); else -> Color(0xFFE74C3C) }

@Composable
fun SpectrumScreen(initial: List<SpecItem>) {
    val ctx = LocalContext.current
    val items = remember { mutableStateListOf<SpecItem>().apply { addAll(initial) } }
    val results = remember { mutableStateMapOf<String, SpectroResult>() }
    val errors = remember { mutableStateMapOf<String, String>() }
    var current by remember { mutableStateOf("") }

    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris: List<Uri> ->
        for (u in uris) {
            var name = ctx.contentResolver.query(u, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
                if (it.moveToFirst()) it.getString(0) else null
            } ?: (u.lastPathSegment ?: "audio")
            val low = name.lowercase()
            if (items.none { it.uri == u }) items.add(SpecItem(u, name, low.endsWith(".flac") || low.endsWith(".wav")))
        }
    }

    LaunchedEffect(items.size) {
        for (it in items.toList()) {
            val k = it.uri.toString()
            if (results.containsKey(k) || errors.containsKey(k)) continue
            current = it.name
            try {
                val r = withContext(Dispatchers.Default) { Spectro.analyze(ctx, it.uri, it.name, it.lossless) }
                results[k] = r
            } catch (e: Throwable) {
                errors[k] = e.message ?: e.javaClass.simpleName
            }
        }
        current = ""
    }

    Column(Modifier.fillMaxSize()) {
        Bar("Espectrograma y calidad", { Nav.pop() }) {
            IconBtn("➕") { picker.launch(arrayOf("audio/*")) }
        }
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(12.dp)) {
            Text(
                "Pulsa ➕ para añadir canciones de cualquier lugar y compararlas entre sí.",
                fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (current.isNotEmpty()) {
                Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                    Text("  Analizando «$current»…", fontSize = 13.sp)
                }
            }
            val done = items.mapNotNull { results[it.uri.toString()] }
            items.forEachIndexed { idx, it ->
                val r = results[it.uri.toString()]
                val err = errors[it.uri.toString()]
                Card(Modifier.fillMaxWidth().padding(top = 10.dp)) {
                    Column(Modifier.padding(12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(12.dp).clip(CircleShape).background(CURVE_COLORS[idx % CURVE_COLORS.size]))
                            Text(it.name, Modifier.weight(1f).padding(start = 8.dp), fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            IconBtn("✕") { items.remove(it); results.remove(it.uri.toString()); errors.remove(it.uri.toString()) }
                        }
                        if (err != null) Text("⚠ $err", color = Color(0xFFE74C3C), fontSize = 13.sp)
                        if (r != null) {
                            Text(r.verdict, color = levelColor(r.level), fontWeight = FontWeight.Bold, fontSize = 13.sp, modifier = Modifier.padding(vertical = 4.dp))
                            Text(
                                "${"%g".format(r.sampleRate / 1000f)} kHz · corte ≈ ${"%.1f".format(r.cutoffHz / 1000f)} kHz de ${"%.1f".format(r.nyquist / 1000f)} · " +
                                    "pico ${"%.1f".format(r.peakDb)} dB · RMS ${"%.1f".format(r.rmsDb)} dB",
                                fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Box(Modifier.padding(top = 8.dp)) {
                                Image(r.bmp.asImageBitmap(), null, Modifier.fillMaxWidth().height(200.dp), contentScale = ContentScale.FillBounds)
                                Text("${r.nyquist / 1000} kHz", Modifier.align(Alignment.TopStart).padding(3.dp), fontSize = 10.sp, color = Color.White)
                                Text("0", Modifier.align(Alignment.BottomStart).padding(3.dp), fontSize = 10.sp, color = Color.White)
                            }
                        }
                    }
                }
            }
            if (done.size >= 2) {
                Text("Comparación", Modifier.padding(top = 16.dp, bottom = 4.dp), fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Text("Espectro medio superpuesto: si una curva cae antes, tiene menos agudos.", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                val maxNyq = done.maxOf { it.nyquist }.toFloat()
                Canvas(Modifier.fillMaxWidth().height(190.dp).padding(top = 8.dp).background(MaterialTheme.colorScheme.surfaceVariant)) {
                    val w = size.width
                    val h = size.height
                    items.forEachIndexed { idx, it ->
                        val r = results[it.uri.toString()] ?: return@forEachIndexed
                        val path = Path()
                        val n = r.curve.size
                        for (i in 0 until n) {
                            val x = (i.toFloat() / n) * (r.nyquist / maxNyq) * w
                            val y = (1f - ((r.curve[i] + 110f) / 90f).coerceIn(0f, 1f)) * h
                            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                        }
                        drawPath(path, CURVE_COLORS[idx % CURVE_COLORS.size], style = Stroke(width = 3f))
                    }
                }
                val best = done.maxByOrNull { it.cutoffHz }
                if (best != null) Text("🏆 Más agudos: ${best.name} (hasta ${"%.1f".format(best.cutoffHz / 1000f)} kHz)", Modifier.padding(top = 8.dp), fontWeight = FontWeight.SemiBold)
            }
            Spacer(Modifier.height(20.dp))
        }
    }
}

// ------------------------------------------------------------------ YouTube → MP3
@Composable
fun YoutubeScreen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf("") }
    var dest by remember { mutableStateOf(Store.lastDir.ifBlank { Store.musicRoot().absolutePath }) }
    var kbps by remember { mutableIntStateOf(320) }
    var running by remember { mutableStateOf(false) }
    var progress by remember { mutableFloatStateOf(0f) }
    var log by remember { mutableStateOf("") }
    var done by remember { mutableStateOf<List<File>>(emptyList()) }

    Column(Modifier.fillMaxSize()) {
        Bar("Descargar de YouTube a MP3", { Nav.pop() })
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(14.dp)) {
            Text(
                "Descarga solo música o contenido que tengas derecho a guardar (tuyo, con licencia libre o con permiso). " +
                    "Eres responsable del uso que le des.", fontSize = 12.sp, color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            OutlinedTextField(
                url, { url = it }, label = { Text("Enlace del vídeo") }, singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(top = 10.dp)
            )
            TextButton(onClick = {
                val cm = ctx.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.primaryClip?.getItemAt(0)?.text?.toString()?.let { url = it.trim() }
            }) { Text("📋 Pegar del portapapeles") }
            OutlinedTextField(dest, { dest = it }, label = { Text("Guardar en") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Text("Calidad MP3", Modifier.padding(top = 10.dp), fontSize = 12.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (k in listOf(128, 192, 256, 320)) FilterChip(selected = kbps == k, onClick = { kbps = k }, label = { Text("$k") })
            }
            Button(
                enabled = !running && url.startsWith("http"), modifier = Modifier.padding(top = 12.dp),
                onClick = {
                    val d = File(dest)
                    if (!d.isDirectory) { log = "Esa carpeta de destino no existe."; return@Button }
                    running = true; progress = 0f; log = "Empezando… (la primera vez prepara los componentes, puede tardar)"; done = emptyList()
                    scope.launch {
                        try {
                            val files = withContext(Dispatchers.IO) {
                                Ytdl.download(ctx, url.trim(), d, kbps) { p, line -> progress = p; log = line }
                            }
                            done = files
                            log = if (files.isEmpty()) "Terminó, pero no encuentro el MP3 nuevo (quizá ya existía)." else "✔ Listo. Puedes editarle metadatos y portada."
                            Store.libVersion++
                        } catch (e: Throwable) {
                            log = "No se pudo descargar: ${e.message}"
                        }
                        running = false
                    }
                }
            ) { Text("⬇ Descargar MP3") }
            if (running || progress > 0f) LinearProgressIndicator(progress = { (progress / 100f).coerceIn(0f, 1f) }, Modifier.fillMaxWidth().padding(top = 10.dp))
            if (log.isNotEmpty()) Text(log, Modifier.padding(top = 8.dp), fontSize = 12.sp)
            for (f in done) {
                Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(f.name, Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis, fontSize = 13.sp)
                    Button(onClick = { Nav.push(Screen.Editor(listOf(f.absolutePath))) }) { Text("✏ Editar") }
                }
            }
        }
    }
}

// ------------------------------------------------------------------ Ajustes
private val ACCENTS = listOf(0xFF7C5CFF, 0xFFE74C3C, 0xFF2ECC71, 0xFF3498DB, 0xFFF39C12, 0xFFEC407A, 0xFF1ABC9C)

@Composable
fun SettingsScreen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var provider by remember { mutableStateOf(Store.provider) }
    var model by remember { mutableStateOf(Store.model(provider)) }
    var key by remember { mutableStateOf(Store.key(provider)) }
    var discogs by remember { mutableStateOf(Store.discogsToken) }
    var info by remember { mutableStateOf<String?>(null) }
    var updUrl by remember { mutableStateOf<String?>(null) }
    var about by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        Bar("Ajustes", { Nav.pop() })
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(14.dp)) {
            Text("🤖 Inteligencia artificial", fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (p in listOf("Claude", "ChatGPT", "Gemini")) {
                    FilterChip(selected = provider == p, onClick = {
                        provider = p; Store.provider = p; Store.save(); model = Store.model(p); key = Store.key(p)
                    }, label = { Text(p) })
                }
            }
            OutlinedTextField(model, { model = it; Store.setModel(provider, it.trim()) }, label = { Text("Modelo") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (m in Store.defaultModels(provider)) AssistChip(onClick = { model = m; Store.setModel(provider, m) }, label = { Text(m, fontSize = 10.sp) })
            }
            OutlinedTextField(
                key, { key = it; Store.setKey(provider, it.trim()) }, label = { Text("API key de $provider") }, singleLine = true,
                visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
            )
            OutlinedTextField(
                discogs, { discogs = it; Store.discogsToken = it.trim(); Store.save() }, label = { Text("Token de Discogs (opcional)") },
                singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
            )

            Text("🎨 Aspecto", Modifier.padding(top = 20.dp), fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                Text("Tema oscuro", Modifier.weight(1f))
                Switch(checked = Store.dark, onCheckedChange = { Store.dark = it; Store.save() })
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Colores según la portada", Modifier.weight(1f))
                Switch(checked = Store.coverTint, onCheckedChange = { Store.coverTint = it; if (!it) Store.dynamicAccent = null; Store.save() })
            }
            Text("Color principal", Modifier.padding(top = 8.dp), fontSize = 12.sp)
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                for (c in ACCENTS) {
                    val ci = c.toInt()
                    Box(
                        Modifier.size(34.dp).clip(CircleShape).background(Color(ci))
                            .clickable { Store.accent = ci; Store.save() },
                        contentAlignment = Alignment.Center
                    ) { if (Store.accent == ci) Text("✓", color = Color.White, fontWeight = FontWeight.Bold) }
                }
            }

            Text("🖼 Portadas", Modifier.padding(top = 20.dp), fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Text("Tamaño máximo al poner portadas nuevas", fontSize = 12.sp)
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (s in listOf(600, 1000, 1200, 2000)) FilterChip(selected = Store.coverMax == s, onClick = { Store.coverMax = s; Store.save() }, label = { Text("$s px") })
            }

            Text("ℹ Acerca de", Modifier.padding(top = 20.dp), fontWeight = FontWeight.Bold, fontSize = 16.sp)
            Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = {
                    scope.launch {
                        info = "Buscando…"
                        try {
                            val r = withContext(Dispatchers.IO) { latestRelease() }
                            val cur = ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
                            if (r == null) info = "No encontré versiones publicadas."
                            else if (r.first == cur) info = "Ya tienes la última versión ($cur)."
                            else { info = "Hay una versión nueva: ${r.first} (tienes $cur)."; updUrl = r.second }
                        } catch (e: Throwable) {
                            info = "No se pudo comprobar: ${e.message}"
                        }
                    }
                }) { Text("Buscar actualización") }
                OutlinedButton(onClick = { about = true }) { Text("Acerca de") }
            }
            info?.let { Text(it, Modifier.padding(top = 8.dp), fontSize = 13.sp) }
            updUrl?.let { u -> Button(onClick = { openUrl(ctx, u) }, modifier = Modifier.padding(top = 6.dp)) { Text("⬇ Descargar") } }
        }
    }

    if (about) {
        AlertDialog(
            onDismissRequest = { about = false },
            title = { Text("Music Manager") },
            text = {
                Text(
                    "Organiza tu música: carpetas, etiquetas, portadas, letras, calidad de audio y ayuda de IA.\n\n" +
                        "Creado por PandxMax\ngithub.com/PandxMax/MusicManager"
                )
            },
            confirmButton = { TextButton(onClick = { openUrl(ctx, "https://github.com/PandxMax/MusicManager"); about = false }) { Text("Abrir GitHub") } },
            dismissButton = { TextButton(onClick = { about = false }) { Text("Cerrar") } }
        )
    }
}

private fun latestRelease(): Pair<String, String>? {
    val txt = Net.get("https://api.github.com/repos/PandxMax/MusicManager/releases?per_page=30", mapOf("Accept" to "application/vnd.github+json"))
    val a = JSONArray(txt)
    for (i in 0 until a.length()) {
        val r = a.getJSONObject(i)
        val tag = r.optString("tag_name")
        if (tag.startsWith("android-v")) {
            var url = r.optString("html_url")
            val assets = r.optJSONArray("assets")
            if (assets != null && assets.length() > 0) url = assets.getJSONObject(0).optString("browser_download_url", url)
            return tag.removePrefix("android-v") to url
        }
    }
    return null
}

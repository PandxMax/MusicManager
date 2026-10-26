package com.pandxmax.musicmanager

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items as gridItems
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

private fun listDir(dir: File, sub: Boolean): List<File> {
    return try {
        if (sub) {
            dir.walkTopDown().filter { it.isFile && it.extension.lowercase() in AUDIO_EXT && !it.name.startsWith(".") }
                .sortedBy { it.name.lowercase() }.toList()
        } else {
            val all = dir.listFiles()?.filter { !it.name.startsWith(".") } ?: emptyList()
            all.filter { it.isDirectory }.sortedBy { it.name.lowercase() } +
                all.filter { it.isFile && it.extension.lowercase() in AUDIO_EXT }.sortedBy { it.name.lowercase() }
        }
    } catch (_: Exception) {
        emptyList()
    }
}

private fun uniqueTarget(dir: File, name: String): File {
    var t = File(dir, name)
    if (!t.exists()) return t
    val base = t.nameWithoutExtension
    val ext = if (t.isFile && t.extension.isNotEmpty()) "." + t.extension else ""
    var n = 2
    while (true) {
        t = File(dir, if (t.isDirectory) "$name ($n)" else "$base ($n)$ext")
        if (!t.exists()) return t
        n++
    }
}

private fun moveOrCopy(paths: List<String>, target: File, cut: Boolean): Pair<Int, List<String>> {
    var ok = 0
    val errs = ArrayList<String>()
    for (p in paths) {
        val src = File(p)
        if (!src.exists()) continue
        if (src.isDirectory && (target.absolutePath == src.absolutePath || target.absolutePath.startsWith(src.absolutePath + "/"))) {
            errs.add("No puedes meter «${src.name}» dentro de sí misma"); continue
        }
        if (cut && src.parentFile?.absolutePath == target.absolutePath) continue
        val dst = uniqueTarget(target, src.name)
        try {
            if (cut) {
                if (!src.renameTo(dst)) {
                    src.copyRecursively(dst, overwrite = false)
                    src.deleteRecursively()
                }
            } else {
                src.copyRecursively(dst, overwrite = false)
            }
            ok++
        } catch (e: Exception) {
            errs.add("${src.name}: ${e.message}")
        }
    }
    return ok to errs
}

private sealed class LibDlg {
    object NewFolder : LibDlg()
    class Rename(val file: File) : LibDlg()
    class Delete(val paths: List<String>) : LibDlg()
    object Help : LibDlg()
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun LibraryScreen() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val root = Store.storageRoot()
    var dir by remember {
        mutableStateOf(File(Store.lastDir).takeIf { Store.lastDir.isNotEmpty() && it.isDirectory } ?: Store.musicRoot())
    }
    var entries by remember { mutableStateOf<List<File>>(emptyList()) }
    var query by remember { mutableStateOf("") }
    var searching by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf<Set<String>>(emptySet()) }
    var menu by remember { mutableStateOf(false) }
    var moreMenu by remember { mutableStateOf(false) }
    var tick by remember { mutableIntStateOf(0) }
    var sub by remember { mutableStateOf(false) }
    var dlg by remember { mutableStateOf<LibDlg?>(null) }
    var msg by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(dir, tick, sub, Store.libVersion) {
        Store.lastDir = dir.absolutePath
        Store.save()
        entries = withContext(Dispatchers.IO) { listDir(dir, sub) }
        selected = selected.filter { p -> entries.any { it.absolutePath == p } }.toSet()
    }

    val shown = entries.filter { query.isBlank() || it.name.contains(query, ignoreCase = true) }
    val songs = shown.filter { it.isFile }

    fun refresh() { Covers.forget(""); Store.coverVersion++; tick++ }
    fun up() {
        val p = dir.parentFile
        if (p != null && dir.absolutePath != root.absolutePath) { dir = p; selected = emptySet() }
    }

    BackHandler(enabled = selected.isNotEmpty()) { selected = emptySet() }
    BackHandler(enabled = selected.isEmpty() && searching) { searching = false; query = "" }
    BackHandler(enabled = selected.isEmpty() && !searching && dir.absolutePath != root.absolutePath) { up() }

    fun runOp(block: () -> String) {
        scope.launch {
            val m = withContext(Dispatchers.IO) { block() }
            msg = m
            refresh()
        }
    }

    Column(Modifier.fillMaxSize()) {
        if (selected.isNotEmpty()) {
            Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 2.dp) {
                Row(
                    Modifier.fillMaxWidth().height(56.dp).horizontalScroll(rememberScrollState()).padding(horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    IconBtn("✕") { selected = emptySet() }
                    Text("${selected.size}", Modifier.padding(horizontal = 6.dp), fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                    val files = selected.filter { File(it).isFile }
                    IconBtn("▶", enabled = files.isNotEmpty()) { PlayerManager.playList(files, 0); selected = emptySet() }
                    IconBtn("➕", enabled = files.isNotEmpty()) { PlayerManager.enqueue(files); msg = "Añadido a la cola"; selected = emptySet() }
                    IconBtn("✏", enabled = files.isNotEmpty()) { Nav.push(Screen.Editor(files)) }
                    IconBtn("✂") { Store.clipPaths = selected.toList(); Store.clipCut = true; msg = "Cortado: pega en otra carpeta"; selected = emptySet() }
                    IconBtn("⧉") { Store.clipPaths = selected.toList(); Store.clipCut = false; msg = "Copiado: pega en otra carpeta"; selected = emptySet() }
                    IconBtn("📊", enabled = files.isNotEmpty()) {
                        Nav.push(Screen.Spectrum(files.map {
                            val f = File(it)
                            SpecItem(Uri.fromFile(f), f.name, f.extension.lowercase() in setOf("flac", "wav"))
                        }))
                    }
                    IconBtn("🗑") { dlg = LibDlg.Delete(selected.toList()) }
                    if (selected.size == 1) IconBtn("Aa") { dlg = LibDlg.Rename(File(selected.first())) }
                    IconBtn("☑") { selected = shown.map { it.absolutePath }.toSet() }
                }
            }
        } else if (searching) {
            Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 2.dp) {
                Row(Modifier.fillMaxWidth().height(56.dp).padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(
                        query, { query = it }, Modifier.weight(1f), singleLine = true,
                        placeholder = { Text("Buscar canción o carpeta") }
                    )
                    IconBtn("✕") { searching = false; query = "" }
                }
            }
        } else {
            Bar(dir.name.ifEmpty { "Almacenamiento" }, null) {
                IconBtn("▲", enabled = dir.absolutePath != root.absolutePath) { up() }
                IconBtn("⟳") { refresh() }
                IconBtn("🔍") { searching = true }
                IconBtn(if (Store.gridView) "☰" else "▦") { Store.gridView = !Store.gridView; Store.save() }
                Box {
                    IconBtn("⋮") { menu = true }
                    DropdownMenu(menu, { menu = false }) {
                        DropdownMenuItem(text = { Text("📁 Nueva carpeta") }, onClick = { menu = false; dlg = LibDlg.NewFolder })
                        DropdownMenuItem(
                            text = { Text("📥 Pegar aquí" + if (Store.clipPaths.isNotEmpty()) " (${Store.clipPaths.size})" else "") },
                            enabled = Store.clipPaths.isNotEmpty(),
                            onClick = {
                                menu = false
                                val paths = Store.clipPaths
                                val cut = Store.clipCut
                                val target = dir
                                runOp {
                                    val (n, errs) = moveOrCopy(paths, target, cut)
                                    if (cut) Store.clipPaths = emptyList()
                                    "$n elemento(s) " + (if (cut) "movido(s)" else "copiado(s)") + if (errs.isNotEmpty()) ". " + errs.first() else ""
                                }
                            })
                        DropdownMenuItem(
                            text = { Text((if (sub) "☑" else "☐") + " Incluir subcarpetas") },
                            onClick = { menu = false; sub = !sub })
                        DropdownMenuItem(text = { Text("🎵 Ir a Música") }, onClick = { menu = false; dir = Store.musicRoot() })
                        DropdownMenuItem(text = { Text("⬇ Descargar de YouTube a MP3") }, onClick = { menu = false; Nav.push(Screen.Youtube) })
                        DropdownMenuItem(text = { Text("⚙ Ajustes") }, onClick = { menu = false; Nav.push(Screen.Settings) })
                        DropdownMenuItem(text = { Text("❔ Ayuda") }, onClick = { menu = false; dlg = LibDlg.Help })
                    }
                }
            }
        }

        if (!searching || true) {
            Text(
                dir.absolutePath, Modifier.padding(horizontal = 12.dp, vertical = 4.dp), fontSize = 11.sp, maxLines = 1,
                overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }

        Box(Modifier.weight(1f).fillMaxWidth()) {
            if (shown.isEmpty()) {
                Text(
                    "Aquí no hay música todavía.\n\nEntra en otra carpeta o pega archivos desde el menú ⋮.",
                    Modifier.align(Alignment.Center).padding(24.dp), textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else if (Store.gridView) {
                LazyVerticalGrid(
                    GridCells.Adaptive(104.dp), Modifier.fillMaxSize(), contentPadding = PaddingValues(8.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    gridItems(shown, key = { it.absolutePath }) { f ->
                        val sel = f.absolutePath in selected
                        Column(
                            Modifier.clip(RoundedCornerShape(12.dp))
                                .background(if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.35f) else androidx.compose.ui.graphics.Color.Transparent)
                                .combinedClickable(
                                    onClick = {
                                        if (selected.isNotEmpty()) selected = if (sel) selected - f.absolutePath else selected + f.absolutePath
                                        else if (f.isDirectory) { dir = f } else { PlayerManager.playList(songs.map { it.absolutePath }, songs.indexOf(f)) }
                                    },
                                    onLongClick = { selected = selected + f.absolutePath }
                                ).padding(6.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            if (f.isDirectory) {
                                Box(Modifier.size(92.dp), contentAlignment = Alignment.Center) { Text("📁", fontSize = 56.sp) }
                            } else {
                                CoverThumb(f.absolutePath, 200, Modifier.size(92.dp).clip(RoundedCornerShape(10.dp)))
                            }
                            Text(
                                if (f.isDirectory) f.name else f.nameWithoutExtension, fontSize = 12.sp, maxLines = 2,
                                overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp)
                            )
                        }
                    }
                }
            } else {
                LazyColumn(Modifier.fillMaxSize()) {
                    items(shown, key = { it.absolutePath }) { f ->
                        val sel = f.absolutePath in selected
                        Row(
                            Modifier.fillMaxWidth()
                                .background(if (sel) MaterialTheme.colorScheme.primary.copy(alpha = 0.35f) else androidx.compose.ui.graphics.Color.Transparent)
                                .combinedClickable(
                                    onClick = {
                                        if (selected.isNotEmpty()) selected = if (sel) selected - f.absolutePath else selected + f.absolutePath
                                        else if (f.isDirectory) { dir = f } else { PlayerManager.playList(songs.map { it.absolutePath }, songs.indexOf(f)) }
                                    },
                                    onLongClick = { selected = selected + f.absolutePath }
                                ).padding(horizontal = 12.dp, vertical = 6.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            if (f.isDirectory) Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) { Text("📁", fontSize = 30.sp) }
                            else CoverThumb(f.absolutePath, 120, Modifier.size(48.dp).clip(RoundedCornerShape(8.dp)))
                            Text(
                                if (f.isDirectory) f.name else f.nameWithoutExtension, Modifier.padding(start = 12.dp), maxLines = 1,
                                overflow = TextOverflow.Ellipsis
                            )
                        }
                    }
                }
            }
            msg?.let { m ->
                Snackbar(Modifier.align(Alignment.BottomCenter).padding(12.dp), action = {
                    TextButton(onClick = { msg = null }) { Text("OK") }
                }) { Text(m) }
            }
        }
    }

    when (val d = dlg) {
        is LibDlg.NewFolder -> TextPrompt("Nueva carpeta", "Nombre", "", { dlg = null }) { name ->
            dlg = null
            val target = dir
            runOp { if (File(target, name).mkdirs()) "Carpeta creada" else "No se pudo crear la carpeta" }
        }
        is LibDlg.Rename -> TextPrompt("Renombrar", "Nuevo nombre", d.file.name, { dlg = null }) { name ->
            dlg = null
            val f = d.file
            runOp {
                val t = File(f.parentFile, name)
                if (t.exists()) "Ya existe «$name»" else if (f.renameTo(t)) "Renombrado" else "No se pudo renombrar"
            }
            selected = emptySet()
        }
        is LibDlg.Delete -> AlertDialog(
            onDismissRequest = { dlg = null },
            title = { Text("Eliminar") },
            text = { Text("¿Eliminar ${d.paths.size} elemento(s)? Esta acción no se puede deshacer.") },
            confirmButton = {
                TextButton(onClick = {
                    dlg = null
                    val ps = d.paths
                    runOp { ps.forEach { File(it).deleteRecursively() }; "Eliminado" }
                    selected = emptySet()
                }) { Text("Eliminar") }
            },
            dismissButton = { TextButton(onClick = { dlg = null }) { Text("Cancelar") } }
        )
        is LibDlg.Help -> AlertDialog(
            onDismissRequest = { dlg = null },
            title = { Text("Ayuda") },
            text = {
                Text(
                    "• Toca una canción para reproducirla; mantén pulsado para seleccionar.\n" +
                        "• Con la selección: ▶ reproducir, ➕ a la cola, ✏ editar metadatos y portada, ✂ cortar, ⧉ copiar, 📊 espectrograma, 🗑 eliminar.\n" +
                        "• Para mover algo: córtalo (✂), entra en la carpeta destino y usa ⋮ → Pegar aquí.\n" +
                        "• ⟳ actualiza la carpeta si añadiste archivos desde fuera."
                )
            },
            confirmButton = { TextButton(onClick = { dlg = null }) { Text("Entendido") } }
        )
        null -> {}
    }
}

@Composable
fun TextPrompt(title: String, label: String, initial: String, onDismiss: () -> Unit, onOk: (String) -> Unit) {
    var t by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { OutlinedTextField(t, { t = it }, label = { Text(label) }, singleLine = true) },
        confirmButton = { TextButton(onClick = { if (t.isNotBlank()) onOk(t.trim()) }) { Text("Aceptar") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancelar") } }
    )
}

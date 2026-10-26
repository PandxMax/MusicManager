package com.pandxmax.musicmanager

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import java.io.File

class SpecItem(val uri: Uri, val name: String, val lossless: Boolean)

sealed class Screen {
    object Library : Screen()
    class Editor(val paths: List<String>) : Screen()
    object Player : Screen()
    class Spectrum(val items: List<SpecItem>) : Screen()
    object Youtube : Screen()
    object Settings : Screen()
}

object Nav {
    val stack = mutableStateListOf<Screen>(Screen.Library)
    fun push(s: Screen) { stack.add(s) }
    fun pop() { if (stack.size > 1) stack.removeAt(stack.size - 1) }
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PlayerManager.connect(this)
        if (Build.VERSION.SDK_INT >= 33) {
            val l = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
            l.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { MMTheme { Root() } }
    }
}

@Composable
fun Root() {
    var hasAccess by remember { mutableStateOf(Environment.isExternalStorageManager()) }
    LaunchedEffect(Unit) {
        while (true) {
            hasAccess = Environment.isExternalStorageManager()
            PlayerManager.tick()
            delay(400)
        }
    }
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        if (!hasAccess) {
            PermissionScreen()
        } else {
            val top = Nav.stack.last()
            BackHandler(enabled = Nav.stack.size > 1) { Nav.pop() }
            Column(Modifier.fillMaxSize().systemBarsPadding().imePadding()) {
                Box(Modifier.weight(1f)) {
                    when (top) {
                        is Screen.Library -> LibraryScreen()
                        is Screen.Editor -> EditorScreen(top.paths)
                        is Screen.Player -> PlayerScreen()
                        is Screen.Spectrum -> SpectrumScreen(top.items)
                        is Screen.Youtube -> YoutubeScreen()
                        is Screen.Settings -> SettingsScreen()
                    }
                }
                if (top !is Screen.Player && PlayerManager.currentPath != null) MiniPlayer()
            }
        }
    }
}

@Composable
fun PermissionScreen() {
    val ctx = androidx.compose.ui.platform.LocalContext.current
    Column(
        Modifier.fillMaxSize().padding(28.dp),
        verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text("♪", fontSize = 56.sp, color = MaterialTheme.colorScheme.primary)
        Text("Music Manager", fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(16.dp))
        Text(
            "Para organizar tu música (mover carpetas, editar etiquetas y portadas dentro de los archivos) " +
                "necesito el permiso «Acceso a todos los archivos».\n\nPulsa el botón y activa el interruptor de Music Manager.",
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(20.dp))
        Button(onClick = {
            try {
                ctx.startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:" + ctx.packageName)))
            } catch (_: Exception) {
                ctx.startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
            }
        }) { Text("Dar permiso") }
    }
}

@Composable
fun MiniPlayer() {
    val path = PlayerManager.currentPath ?: return
    val name = File(path).nameWithoutExtension
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 4.dp) {
        Column {
            val frac = if (PlayerManager.duration > 0) PlayerManager.position.toFloat() / PlayerManager.duration else 0f
            LinearProgressIndicator(progress = { frac.coerceIn(0f, 1f) }, Modifier.fillMaxWidth().height(2.dp))
            Row(
                Modifier.fillMaxWidth().clickable { Nav.push(Screen.Player) }.padding(horizontal = 8.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                CoverThumb(path, 96, Modifier.size(44.dp))
                Text(
                    name, Modifier.weight(1f).padding(horizontal = 10.dp), maxLines = 1,
                    overflow = TextOverflow.Ellipsis, fontSize = 14.sp
                )
                IconBtn("✏") { Nav.push(Screen.Editor(listOf(path))) }
                IconBtn("⏮") { PlayerManager.prev() }
                IconBtn(if (PlayerManager.isPlaying) "⏸" else "▶", accent = true) { PlayerManager.toggle() }
                IconBtn("⏭") { PlayerManager.next() }
            }
        }
    }
}
